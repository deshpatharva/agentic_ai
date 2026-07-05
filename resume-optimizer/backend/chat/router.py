"""Stateful optimize co-pilot — POST /optimize/chat returns SSE.

Architecture (v2 — state-machine):
  1. Resolve session, persist user message
  2. Determine conversation phase from session.context
  3. Try deterministic handling (URL paste, picker click, affirmation)
  4. If LLM needed: build phase-scoped window → complete_with_tools → retry on empty
  5. Handle tool calls (launch/save/download/edit) — same handoff logic
  6. Persist assistant message with tool-call metadata
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth.dependencies import get_current_user, reserve_run_quota, refund_run_quota
from chat.agent import render_system_prompt, render_context_message
from chat.state_machine import (
    resolve_phase, tools_for_phase, try_deterministic, fallback_response,
)
from chat.tools import LAUNCH_TOOL, SAVE_TOOL, DOWNLOAD_TOOL, EDIT_TOOL, parse_tool_calls, message_text
from chat.dependencies import get_or_create_session, require_complete_profile
from chat.handoff import fire_optimizer, save_profile_from_session, resolve_profile_download, apply_edit
from chat.window import build_window
from config import MODEL_CHAT_AGENT, CHAT_WINDOW_TURNS
from db.models import ChatMessage, ChatSession, DailyUsageCounter, PlanLimit, User
from db.session import get_db, AsyncSessionLocal
from llm import complete_with_tools, stream_chat

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/optimize", tags=["optimize-agent"])


class ChatTurnRequest(BaseModel):
    session_id: str | None = None
    message: str


class SessionRenameRequest(BaseModel):
    title: str


# ── Session management endpoints ──────────────────────────────────────────────


@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return the user's chat sessions newest-first with message counts."""
    rows = (await db.execute(
        select(ChatSession, func.count(ChatMessage.id).label("message_count"))
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == current_user.id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.updated_at.desc())
    )).all()
    return [
        {
            "id": str(sess.id),
            "title": sess.title or "New chat",
            "updated_at": sess.updated_at.isoformat(),
            "message_count": count,
            "job_id": str(sess.job_id) if sess.job_id else None,
        }
        for sess, count in rows
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a session with its full ordered transcript."""
    sess = await _get_owned_session(session_id, current_user.id, db)
    msgs = (await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == sess.id)
        .order_by(ChatMessage.id)
    )).scalars().all()
    ctx = sess.context or {}
    from db.models import Profile as _Profile
    all_profs = (await db.execute(
        select(_Profile).where(_Profile.user_id == current_user.id)
    )).scalars().all()
    return {
        "id": str(sess.id),
        "title": sess.title or "New chat",
        "updated_at": sess.updated_at.isoformat(),
        "job_id": str(sess.job_id) if sess.job_id else None,
        "last_result": ctx.get("last_result"),
        "has_jd": bool(ctx.get("jd_text")),
        "optimizer_launched": bool(ctx.get("_optimizer_launched")),
        "profiles": _build_picker_profiles(
            ctx, [{"id": str(p.id), "label": p.label or ""} for p in all_profs]
        ),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ],
    }


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    body: SessionRenameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rename a session."""
    title = body.title.strip()[:120]
    if not title:
        raise HTTPException(status_code=422, detail="title cannot be blank.")
    sess = await _get_owned_session(session_id, current_user.id, db)
    sess.title = title
    sess.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(sess.id), "title": sess.title}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a session and all its messages (cascade)."""
    sess = await _get_owned_session(session_id, current_user.id, db)
    await db.delete(sess)
    await db.commit()


def _build_picker_profiles(ctx: dict, all_profiles: list[dict]) -> list[dict]:
    matched = ctx.get("_jd_matched_profiles", [])
    pct_by_id = {m["id"]: m.get("match_pct", 0) for m in matched}
    rank = {m["id"]: i for i, m in enumerate(matched)}
    top_id = matched[0]["id"] if matched else None

    ordered = sorted(
        all_profiles,
        key=lambda p: (0, rank[p["id"]]) if p["id"] in rank else (1, 0),
    )
    out = []
    for p in ordered:
        pct = pct_by_id.get(p["id"])
        out.append({
            "id": p["id"],
            "label": p["label"],
            "match_pct": pct if pct and pct > 0 else None,
            "recommended": p["id"] == top_id,
        })
    return out


async def _get_owned_session(session_id: str, user_id, db: AsyncSession) -> ChatSession:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found.")
    sess = await db.scalar(select(ChatSession).where(ChatSession.id == sid))
    if not sess or str(sess.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return sess


# ── JD resolution helpers ────────────────────────────────────────────────────

_URL_RE = re.compile(r"^https?://", re.I)


async def _resolve_jd(message: str, db: AsyncSession) -> tuple[str | None, bool]:
    """Attempt to resolve a job description from the message.

    Returns (jd_text, url_was_attempted).
    """
    text = message.strip()
    if _URL_RE.match(text):
        from jd.router import _fetch_jd_from_url, _CACHE_TTL_HOURS
        from db.models import JdScrapeCache
        from datetime import timedelta

        url_hash = hashlib.sha256(text.encode()).hexdigest()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
        cached = await db.scalar(
            select(JdScrapeCache).where(
                JdScrapeCache.url_hash == url_hash,
                JdScrapeCache.scraped_at >= cutoff,
            )
        )
        if cached:
            return cached.jd_text, True
        try:
            jd_text = await _fetch_jd_from_url(text)
        except Exception:
            return None, True
        try:
            old = await db.scalar(select(JdScrapeCache).where(JdScrapeCache.url_hash == url_hash))
            if old:
                old.jd_text = jd_text
                old.scraped_at = datetime.now(timezone.utc)
            else:
                db.add(JdScrapeCache(url_hash=url_hash, jd_text=jd_text))
            await db.commit()
        except Exception:
            _logger.warning("JD cache write failed (url_hash=%s), continuing without cache", url_hash)
        return jd_text, True

    if len(text) > 200:
        return text, False

    return None, False


async def _match_profiles(user: User, jd_text: str, db: AsyncSession) -> list[dict]:
    from jd.router import _score_profiles
    from db.models import Profile as _Profile
    result = await db.execute(select(_Profile).where(_Profile.user_id == user.id))
    profiles = result.scalars().all()
    if not profiles:
        return []
    profile_dicts = [
        {
            "id": str(p.id),
            "label": p.label or "",
            "skills": (p.sections or {}).get("skills", []),
            "summary": (p.sections or {}).get("summary", ""),
        }
        for p in profiles
    ]
    try:
        ranked = await _score_profiles(profile_dicts, jd_text)
        return sorted(ranked, key=lambda x: x["match_pct"], reverse=True)[:3]
    except Exception:
        return [{"id": p["id"], "label": p["label"], "match_pct": 0} for p in profile_dicts[:3]]


async def _compute_jd_gaps(jd_text: str, matches: list[dict], user: User, db: AsyncSession) -> list[str]:
    if not matches:
        return []
    try:
        from agents.jd_analyzer import analyze_jd
        from chat.gaps import compute_gaps
        from db.models import Profile as _Profile

        top_id = matches[0].get("id")
        prof = await db.scalar(
            select(_Profile).where(_Profile.id == uuid.UUID(str(top_id)), _Profile.user_id == user.id)
        )
        if not prof:
            return []
        jd_dict = await analyze_jd(jd_text)
        jd_result = jd_dict.get("text", jd_dict)
        skills = (prof.sections or {}).get("skills", []) or []
        return compute_gaps(jd_result, skills, prof.raw_text or "", limit=3)
    except Exception:
        _logger.warning("gap computation failed — continuing without gaps", exc_info=True)
        return []


# ── Quota helpers ──────────────────────────────────────────────────────────────


async def _check_edit_quota(user: User, db: AsyncSession) -> None:
    from auth.dependencies import _effective_plan
    from datetime import date

    plan = _effective_plan(user)
    limits = await db.scalar(select(PlanLimit).where(PlanLimit.plan == plan))
    if not limits:
        return

    today_str = date.today().isoformat()
    used = await db.scalar(
        select(DailyUsageCounter.edits).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == today_str,
        )
    ) or 0

    if used >= limits.daily_edits:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "edit_limit_reached",
                "limit": limits.daily_edits,
                "used": used,
                "upgrade_message": "You've reached your daily edit limit. Upgrade to Pro for more edits.",
            },
        )


async def _increment_edit_counter(user_id: str, db: AsyncSession) -> None:
    import uuid as _uuid_mod
    from datetime import date
    uid_hex = _uuid_mod.UUID(user_id).hex
    await db.execute(
        text(
            "INSERT INTO daily_usage_counters (user_id, date, runs, edits) "
            "VALUES (:uid, :date, 0, 1) "
            "ON CONFLICT (user_id, date) DO UPDATE "
            "SET edits = daily_usage_counters.edits + 1"
        ),
        {"uid": uid_hex, "date": date.today().isoformat()},
    )
    await db.commit()


# ── Main chat endpoint ────────────────────────────────────────────────────────


@router.post("/chat")
async def optimize_chat(
    body: ChatTurnRequest,
    current_user: User = Depends(require_complete_profile),
    db: AsyncSession = Depends(get_db),
):
    """Stateful co-pilot turn. Returns an SSE stream.

    Architecture (v2):
      1. Pre-resolve JD if needed
      2. Determine conversation phase
      3. Try deterministic handling first
      4. Fall back to LLM with phase-scoped prompt + retry
    """
    try:
        session = await get_or_create_session(
            session_id=body.session_id, current_user=current_user, db=db
        )

        # 1. Pre-resolve JD from the message before touching the LLM.
        ctx = dict(session.context or {})
        if not ctx.get("jd_text"):
            resolved_jd, url_attempted = await _resolve_jd(body.message, db)
            ctx_changed = False
            if resolved_jd:
                ctx["jd_text"] = resolved_jd
                ctx.pop("jd_fetch_error", None)
                matches = await _match_profiles(current_user, resolved_jd, db)
                ctx["_jd_matched_profiles"] = [
                    {"id": m["id"], "label": m["label"], "match_pct": m.get("match_pct", 0)}
                    for m in matches
                ]
                ctx["gaps"] = await _compute_jd_gaps(resolved_jd, matches, current_user, db)
                ctx_changed = True
            elif url_attempted:
                ctx["jd_fetch_error"] = True
                ctx_changed = True
            if ctx_changed:
                session.context = ctx
                session.updated_at = datetime.now(timezone.utc)
                await db.commit()

        # 2. Persist user turn; auto-title.
        now = datetime.now(timezone.utc)
        db.add(ChatMessage(session_id=session.id, role="user", content=body.message, created_at=now))
        if not session.title:
            first_line = body.message.split("\n")[0].strip()
            session.title = first_line[:80] or "New chat"
            session.updated_at = now
        await db.commit()

        # 3. Determine phase + load profiles.
        phase = resolve_phase(ctx)

        from db.models import Profile as _Profile
        all_profs = (await db.execute(
            select(_Profile).where(_Profile.user_id == current_user.id)
        )).scalars().all()
        profiles_list = [{"id": str(p.id), "label": p.label or ""} for p in all_profs]

        prompt_ctx = dict(ctx)
        prompt_ctx["profiles"] = profiles_list

        # 4. Load history.
        history_rows = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.id)
            )
        ).scalars().all()

        session_id_str = str(session.id)

    except Exception:
        _logger.exception("optimize_chat setup failed (session_id=%s)", body.session_id)

        async def _setup_error_gen():
            yield {"event": "session", "data": json.dumps({"session_id": body.session_id or ""})}
            yield {"event": "final", "data": json.dumps({"content": "Sorry — I couldn't start that turn. Please try again."})}
            yield {"event": "error", "data": json.dumps({"message": "Chat setup failed — please try again."})}
            yield {"event": "done", "data": json.dumps({"session_id": body.session_id or ""})}

        return EventSourceResponse(_setup_error_gen(), sep="\n")

    # ── 5. Try deterministic handling first ──────────────────────────────────
    deterministic = try_deterministic(phase, body.message, ctx, profiles_list)

    async def event_generator():
        """SSE generator for LLM-driven turns (deterministic turns use _deterministic_generator)."""
        yield {"event": "session", "data": json.dumps({
            "session_id": session_id_str,
            "has_jd": bool(ctx.get("jd_text")),
            "optimizer_launched": bool(ctx.get("_optimizer_launched")),
            "profiles": _build_picker_profiles(ctx, profiles_list),
        })}

        # ── LLM path — phase-scoped prompt + retry ───────────────────────
        system_prompt = render_system_prompt(prompt_ctx, phase)
        context_msg = render_context_message(prompt_ctx, phase)
        window = build_window(
            system_prompt, history_rows, n=CHAT_WINDOW_TURNS,
            context_message=context_msg,
        )
        phase_tools = tools_for_phase(phase)

        display = ""
        tool_calls = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        tool_call_meta = None

        # First attempt
        try:
            if phase_tools:
                result = await complete_with_tools(window, MODEL_CHAT_AGENT, phase_tools)
                message = result["message"]
                display = message_text(message).strip()
                tool_calls = parse_tool_calls(message)
                usage = {"input_tokens": result.get("input_tokens", 0),
                         "output_tokens": result.get("output_tokens", 0)}
            else:
                # No tools available (e.g. OPTIMIZING) — stream text response
                chunks = []
                async for chunk in stream_chat(window, MODEL_CHAT_AGENT):
                    if chunk["type"] == "token":
                        chunks.append(chunk["text"])
                        yield {"event": "token", "data": json.dumps({"text": chunk["text"]})}
                    elif chunk["type"] == "usage":
                        usage = {"input_tokens": chunk.get("input_tokens", 0),
                                 "output_tokens": chunk.get("output_tokens", 0)}
                display = "".join(chunks).strip()
        except Exception:
            _logger.exception("chat completion failed for session %s", session_id_str)
            display = ""

        # Retry once on empty response
        if not display and not tool_calls:
            _logger.info("chat: empty response for session %s, retrying with temperature=0.7", session_id_str)
            try:
                if phase_tools:
                    result = await complete_with_tools(window, MODEL_CHAT_AGENT, phase_tools)
                    message = result["message"]
                    display = message_text(message).strip()
                    tool_calls = parse_tool_calls(message)
                    usage = {"input_tokens": result.get("input_tokens", 0),
                             "output_tokens": result.get("output_tokens", 0)}
            except Exception:
                _logger.exception("chat retry also failed for session %s", session_id_str)

        # Final fallback — deterministic response based on phase
        if not display and not tool_calls:
            _logger.warning("chat: both attempts empty for session %s (phase=%s), using fallback", session_id_str, phase)
            display = fallback_response(phase, ctx)

        # ── Process tool calls ──────────────────────────────────────────────
        launch = next((c for c in tool_calls if c["name"] == LAUNCH_TOOL), None)
        save = next((c for c in tool_calls if c["name"] == SAVE_TOOL), None)
        download = next((c for c in tool_calls if c["name"] == DOWNLOAD_TOOL), None)
        edit = next((c for c in tool_calls if c["name"] == EDIT_TOOL), None)

        # Synthesize display text if the model only called a tool silently.
        if not display:
            display = (
                "Launching the optimizer now…" if launch
                else "Generating your document…" if download
                else "Saving your profile…" if save
                else "Editing your resume…" if edit
                else display
            )

        # Build tool-call metadata for persistence
        if tool_calls:
            tool_call_meta = {"tool_calls": [
                {"name": tc["name"], "arguments": tc["arguments"]} for tc in tool_calls
            ]}

        # Persist assistant message with metadata.
        async with AsyncSessionLocal() as wdb:
            wdb.add(ChatMessage(
                session_id=session.id,
                role="assistant",
                content=display,
                meta=tool_call_meta,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                created_at=datetime.now(timezone.utc),
            ))
            await wdb.commit()

        yield {"event": "final", "data": json.dumps({"content": display})}

        # ── Launch ──────────────────────────────────────────────────────────
        if launch:
            if ctx.get("_optimizer_launched"):
                yield {"event": "error", "data": json.dumps({"message": "The optimizer was already launched in this session. Start a new chat to optimize again."})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return

            # Atomically reserve a run slot (own session — the request db may be
            # closed by the time this streaming generator runs).
            async with AsyncSessionLocal() as qdb:
                reserved = await reserve_run_quota(current_user, qdb)
            if not reserved:
                yield {"event": "error", "data": json.dumps({"message": "You've reached your daily limit. Upgrade to Pro for more runs/day."})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return

            args = launch["arguments"]
            handoff_payload = {
                "profile_id": str(args.get("profile_id", "") or ""),
                "instruction": str(args.get("added_context", "") or ""),
            }
            try:
                job_id, sse_token = await fire_optimizer(current_user, session, handoff_payload)
                async with AsyncSessionLocal() as wdb:
                    from sqlalchemy import select as _sel
                    launched_sess = await wdb.scalar(_sel(ChatSession).where(ChatSession.id == session.id))
                    if launched_sess:
                        _ctx = dict(launched_sess.context or {})
                        _ctx["_optimizer_launched"] = True
                        launched_sess.context = _ctx
                        await wdb.commit()
                yield {"event": "handoff", "data": json.dumps({"job_id": job_id, "sse_token": sse_token})}
            except HTTPException as exc:
                # The pipeline task never started — return the reserved slot.
                async with AsyncSessionLocal() as qdb:
                    await refund_run_quota(str(current_user.id), qdb)
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        # ── Download ───────────────────────────────────────────────────────
        elif download:
            try:
                info = await resolve_profile_download(current_user, download["arguments"].get("profile_id", ""))
                yield {"event": "profile_docx", "data": json.dumps(info)}
            except HTTPException as exc:
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        # ── Save ───────────────────────────────────────────────────────────
        elif save:
            payload = {"label": str(save["arguments"].get("label", "") or "")}
            try:
                saved = await save_profile_from_session(current_user, session, payload)
                yield {"event": "saved_profile", "data": json.dumps(saved)}
            except HTTPException as exc:
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        # ── Edit ───────────────────────────────────────────────────────────
        elif edit:
            try:
                await _check_edit_quota(current_user, db)
            except HTTPException as exc:
                detail = exc.detail
                msg = (detail.get("upgrade_message", "Daily edit limit reached.")
                       if isinstance(detail, dict) else str(detail))
                yield {"event": "error", "data": json.dumps({"message": msg})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return
            try:
                edit_result = await apply_edit(current_user, session, edit["arguments"])
                async with AsyncSessionLocal() as wdb:
                    await _increment_edit_counter(str(current_user.id), wdb)
                yield {"event": "resume_edited", "data": json.dumps(edit_result)}
            except HTTPException as exc:
                msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                yield {"event": "error", "data": json.dumps({"message": msg})}

        yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}

    async def _deterministic_generator():
        """SSE generator for deterministic (no-LLM) turns."""
        yield {"event": "session", "data": json.dumps({
            "session_id": session_id_str,
            "has_jd": bool(ctx.get("jd_text")),
            "optimizer_launched": bool(ctx.get("_optimizer_launched")),
            "profiles": _build_picker_profiles(ctx, profiles_list),
        })}

        display = deterministic["response"]
        action = deterministic["action"]

        # Persist assistant reply
        async with AsyncSessionLocal() as wdb:
            wdb.add(ChatMessage(
                session_id=session.id, role="assistant",
                content=display, created_at=datetime.now(timezone.utc),
            ))
            await wdb.commit()

        yield {"event": "final", "data": json.dumps({"content": display})}

        if action == "launch":
            if ctx.get("_optimizer_launched"):
                yield {"event": "error", "data": json.dumps({"message": "The optimizer was already launched in this session. Start a new chat to optimize again."})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return

            async with AsyncSessionLocal() as qdb:
                reserved = await reserve_run_quota(current_user, qdb)
            if not reserved:
                yield {"event": "error", "data": json.dumps({"message": "You've reached your daily limit. Upgrade to Pro for more runs/day."})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return

            handoff_payload = {
                "profile_id": deterministic["profile_id"],
                "instruction": "",
            }
            try:
                job_id, sse_token = await fire_optimizer(current_user, session, handoff_payload)
                async with AsyncSessionLocal() as wdb:
                    from sqlalchemy import select as _sel
                    launched_sess = await wdb.scalar(_sel(ChatSession).where(ChatSession.id == session.id))
                    if launched_sess:
                        _ctx = dict(launched_sess.context or {})
                        _ctx["_optimizer_launched"] = True
                        launched_sess.context = _ctx
                        await wdb.commit()
                yield {"event": "handoff", "data": json.dumps({"job_id": job_id, "sse_token": sse_token})}
            except HTTPException as exc:
                async with AsyncSessionLocal() as qdb:
                    await refund_run_quota(str(current_user.id), qdb)
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        elif action == "download":
            try:
                info = await resolve_profile_download(current_user, deterministic["profile_id"])
                yield {"event": "profile_docx", "data": json.dumps(info)}
            except HTTPException as exc:
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}

    if deterministic:
        return EventSourceResponse(_deterministic_generator(), sep="\n")
    return EventSourceResponse(event_generator(), sep="\n")
