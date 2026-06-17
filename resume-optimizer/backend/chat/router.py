"""Stateful optimize co-pilot — POST /optimize/chat returns SSE."""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth.dependencies import get_current_user
from chat.agent import render_system_prompt
from chat.tools import TOOLS, LAUNCH_TOOL, SAVE_TOOL, DOWNLOAD_TOOL, parse_tool_calls, message_text
from chat.dependencies import get_or_create_session, require_complete_profile
from chat.handoff import fire_optimizer, save_profile_from_session, resolve_profile_download
from chat.window import build_window
from config import MODEL_CHAT_AGENT, CHAT_WINDOW_TURNS
from db.models import ChatMessage, ChatSession, DailyUsageCounter, PlanLimit, User
from db.session import get_db, AsyncSessionLocal
from llm import complete_with_tools

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
    """Order profiles recommended-first with match scores for the UI profile picker.

    `all_profiles` is [{id, label}]. Matched profiles (ranked by JD relevance) come
    first; the top match is flagged `recommended`. match_pct is surfaced only when > 0.
    """
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


_URL_RE = re.compile(r"^https?://", re.I)


async def _resolve_jd(message: str, db: AsyncSession) -> tuple[str | None, bool]:
    """Attempt to resolve a job description from the message.

    Returns (jd_text, url_was_attempted):
      - (text, False) — long paste treated as JD
      - (text, True)  — URL successfully fetched
      - (None, True)  — URL was provided but fetch/parse failed
      - (None, False) — message is neither a URL nor a long paste
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
            return None, True  # URL attempted but fetch failed
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
    """Compute deterministic gaps for the top-matched profile vs the JD.

    Runs the JD analyzer (cached, reused later by the pipeline) and diffs its
    required skills against the recommended profile. Best-effort: returns [] on
    any failure so chat never breaks.
    """
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


async def _check_quota(user: User, db: AsyncSession) -> None:
    """Raise HTTP 429 if user has hit their daily pipeline limit (same guard as /run-pipeline)."""
    from auth.dependencies import _effective_plan
    from datetime import date

    plan = _effective_plan(user)
    limits = await db.scalar(select(PlanLimit).where(PlanLimit.plan == plan))
    if not limits:
        return

    today_str = date.today().isoformat()
    used = await db.scalar(
        select(DailyUsageCounter.runs).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == today_str,
        )
    ) or 0

    if used >= limits.daily_uploads:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "limit_reached",
                "limit": limits.daily_uploads,
                "used": used,
                "plan": user.plan.value,
                "upgrade_message": "Upgrade to Pro for 20 uploads/day",
            },
        )


@router.post("/chat")
async def optimize_chat(
    body: ChatTurnRequest,
    current_user: User = Depends(require_complete_profile),
    db: AsyncSession = Depends(get_db),
):
    """Stateful co-pilot turn. Returns an SSE stream read via fetch() + ReadableStream.

    Events emitted:
      session  — {"session_id": "..."}            (first, always)
      token    — {"text": "<delta>"}              (0..N, streaming tokens)
      handoff  — {"job_id": "...", "sse_token": "..."} (when optimizer fires)
      error    — {"message": "..."}               (on failure)
      done     — {"session_id": "..."}            (last, always)
    """
    # All setup is wrapped so ANY failure becomes a graceful, logged SSE error
    # instead of an opaque HTTP 500 ("Request failed" in the UI with no detail).
    try:
        # Resolve session from body.session_id (can't use Depends here — body params are
        # unavailable inside FastAPI dependency functions).
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
                # Deterministically compute gaps for the top-matched profile so the
                # agent asks grounded questions (no hallucinated gaps/companies).
                ctx["gaps"] = await _compute_jd_gaps(resolved_jd, matches, current_user, db)
                ctx_changed = True
            elif url_attempted:
                # URL provided but fetch failed — tell the AI so it doesn't hallucinate success.
                ctx["jd_fetch_error"] = True
                ctx_changed = True
            if ctx_changed:
                session.context = ctx
                session.updated_at = datetime.now(timezone.utc)
                await db.commit()

        # 2. Persist the user turn; auto-title the session from the first message.
        now = datetime.now(timezone.utc)
        db.add(ChatMessage(session_id=session.id, role="user", content=body.message, created_at=now))
        if not session.title:
            first_line = body.message.split("\n")[0].strip()
            session.title = first_line[:80] or "New chat"
            session.updated_at = now
        await db.commit()

        # 3. Load history and build window.
        history_rows = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.id)
            )
        ).scalars().all()

        # Always inject fresh profiles from DB — ctx["_jd_matched_profiles"] may be stale or
        # absent (never set when JD hasn't been captured yet), causing the AI to say "no profiles".
        from db.models import Profile as _Profile
        all_profs = (await db.execute(
            select(_Profile).where(_Profile.user_id == current_user.id)
        )).scalars().all()
        prompt_ctx = dict(ctx)
        prompt_ctx["profiles"] = [{"id": str(p.id), "label": p.label or ""} for p in all_profs]

        system_prompt = render_system_prompt(prompt_ctx)
        window = build_window(system_prompt, history_rows, n=CHAT_WINDOW_TURNS)
        session_id_str = str(session.id)
    except Exception:
        _logger.exception("optimize_chat setup failed (session_id=%s)", body.session_id)

        async def _setup_error_gen():
            yield {"event": "session", "data": json.dumps({"session_id": body.session_id or ""})}
            yield {"event": "final", "data": json.dumps({"content": "❌ Sorry — I couldn't start that turn. Please try again."})}
            yield {"event": "error", "data": json.dumps({"message": "Chat setup failed — please try again."})}
            yield {"event": "done", "data": json.dumps({"session_id": body.session_id or ""})}

        return EventSourceResponse(_setup_error_gen(), sep="\n")

    async def event_generator():
        yield {"event": "session", "data": json.dumps({
            "session_id": session_id_str,
            "has_jd": bool(ctx.get("jd_text")),
            "optimizer_launched": bool(ctx.get("_optimizer_launched")),
            "profiles": _build_picker_profiles(ctx, prompt_ctx.get("profiles", [])),
        })}

        # Single tool-calling completion. The model returns either a text reply
        # (normal chat) or validated tool calls (launch/save) — never control
        # tokens to parse, so nothing can leak into the chat. Parsing is inside the
        # try so a provider-specific response shape can never crash the stream.
        try:
            result = await complete_with_tools(window, MODEL_CHAT_AGENT, TOOLS)
            message = result["message"]
            text = message_text(message).strip()
            tool_calls = parse_tool_calls(message)
            usage = {"input_tokens": result.get("input_tokens", 0),
                     "output_tokens": result.get("output_tokens", 0)}
        except Exception:
            _logger.exception("chat completion failed for session %s", session_id_str)
            yield {"event": "final", "data": json.dumps({"content": "❌ Sorry — I hit an error. Please try again."})}
            yield {"event": "error", "data": json.dumps({"message": "Agent failed — please try again."})}
            yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
            return

        launch = next((c for c in tool_calls if c["name"] == LAUNCH_TOOL), None)
        save = next((c for c in tool_calls if c["name"] == SAVE_TOOL), None)
        download = next((c for c in tool_calls if c["name"] == DOWNLOAD_TOOL), None)

        # Persist the assistant's visible text (may be empty if it only called a tool).
        async with AsyncSessionLocal() as wdb:
            wdb.add(ChatMessage(
                session_id=session.id,
                role="assistant",
                content=text,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                created_at=datetime.now(timezone.utc),
            ))
            await wdb.commit()

        # Display text — synthesize a line if the model only called a tool silently.
        display = text or (
            "Launching the optimizer now…" if launch
            else "Generating your document…" if download
            else "Saving your profile…" if save
            else "Sorry, I didn't catch that. Could you rephrase?"
        )
        yield {"event": "final", "data": json.dumps({"content": display})}

        # ── Launch ──────────────────────────────────────────────────────────
        if launch:
            if ctx.get("_optimizer_launched"):
                yield {"event": "error", "data": json.dumps({"message": "The optimizer was already launched in this session. Start a new chat to optimize again."})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return

            try:
                await _check_quota(current_user, db)
            except HTTPException as exc:
                detail = exc.detail
                msg = (detail.get("upgrade_message", "Daily limit reached.")
                       if isinstance(detail, dict) else str(detail))
                yield {"event": "error", "data": json.dumps({"message": msg})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return

            args = launch["arguments"]
            handoff_payload = {
                "profile_id": str(args.get("profile_id", "") or ""),
                "instruction": str(args.get("added_context", "") or ""),
            }
            try:
                job_id, sse_token = await fire_optimizer(current_user, session, handoff_payload)
                # Mark session so agent and frontend both know optimizer has fired.
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
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        # ── Download profile as docx (no JD optimization) ───────────────────
        elif download:
            try:
                info = await resolve_profile_download(current_user, download["arguments"].get("profile_id", ""))
                yield {"event": "profile_docx", "data": json.dumps(info)}
            except HTTPException as exc:
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        # ── Save profile (only when not also launching) ─────────────────────
        elif save:
            payload = {"label": str(save["arguments"].get("label", "") or "")}
            try:
                saved = await save_profile_from_session(current_user, session, payload)
                yield {"event": "saved_profile", "data": json.dumps(saved)}
            except HTTPException as exc:
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}

    return EventSourceResponse(event_generator(), sep="\n")
