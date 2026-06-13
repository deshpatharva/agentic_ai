"""Stateful optimize co-pilot — POST /optimize/chat returns SSE."""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth.dependencies import get_current_user
from chat.agent import extract_handoff, in_sentinel, render_system_prompt
from chat.dependencies import get_or_create_session, require_complete_profile
from chat.handoff import fire_optimizer
from chat.window import build_window
from config import MODEL_CHAT_AGENT, CHAT_WINDOW_TURNS
from db.models import ChatMessage, ChatSession, DailyUsageCounter, PlanLimit, User
from db.session import get_db, AsyncSessionLocal
from llm import stream_chat

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/optimize", tags=["optimize-agent"])


class ChatTurnRequest(BaseModel):
    session_id: str | None = None
    message: str


async def _resolve_jd(message: str, db: AsyncSession) -> str | None:
    """If message looks like a URL, scrape it; if it's a long paste, return as-is.
    Returns the JD text or None if the message doesn't look like a JD/URL.
    """
    text = message.strip()
    if re.match(r"^https?://", text, re.I):
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
            return cached.jd_text
        try:
            jd_text = await _fetch_jd_from_url(text)
        except Exception:
            return None  # let the LLM surface the error conversationally
        old = await db.scalar(select(JdScrapeCache).where(JdScrapeCache.url_hash == url_hash))
        if old:
            old.jd_text = jd_text
            old.scraped_at = datetime.now(timezone.utc)
        else:
            db.add(_JdCache(url_hash=url_hash, jd_text=jd_text))
        await db.commit()
        return jd_text

    if len(text) > 200:
        return text

    return None


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
    # Resolve session from body.session_id (can't use Depends here — body params are unavailable
    # inside FastAPI dependency functions).
    session = await get_or_create_session(
        session_id=body.session_id, current_user=current_user, db=db
    )

    # 1. Pre-resolve JD from the message before touching the LLM.
    ctx = dict(session.context or {})
    if not ctx.get("jd_text"):
        resolved_jd = await _resolve_jd(body.message, db)
        if resolved_jd:
            ctx["jd_text"] = resolved_jd
            matches = await _match_profiles(current_user, resolved_jd, db)
            ctx["profiles"] = [{"id": m["id"], "label": m["label"]} for m in matches]
            session.context = ctx
            session.updated_at = datetime.now(timezone.utc)
            await db.commit()

    # 2. Persist the user turn.
    now = datetime.now(timezone.utc)
    db.add(ChatMessage(session_id=session.id, role="user", content=body.message, created_at=now))
    await db.commit()

    # 3. Load history and build window.
    history_rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.id)
        )
    ).scalars().all()

    system_prompt = render_system_prompt(ctx)
    window = build_window(system_prompt, history_rows, n=CHAT_WINDOW_TURNS)

    session_id_str = str(session.id)

    async def event_generator():
        yield {"event": "session", "data": json.dumps({"session_id": session_id_str})}

        assembled: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        sentinel_started = False

        try:
            async for ev in stream_chat(window, MODEL_CHAT_AGENT):
                if ev["type"] == "token":
                    assembled.append(ev["text"])
                    accumulated = "".join(assembled)
                    # Once the sentinel prefix appears, hold back output (token is internal).
                    if not sentinel_started and not in_sentinel(accumulated):
                        yield {"event": "token", "data": json.dumps({"text": ev["text"]})}
                    elif in_sentinel(accumulated):
                        sentinel_started = True
                elif ev["type"] == "usage":
                    usage = ev
        except Exception:
            _logger.exception("stream_chat failed for session %s", session_id_str)
            yield {"event": "error", "data": json.dumps({"message": "Agent stream failed — please try again."})}
            return

        full_text = "".join(assembled)
        clean_text, handoff_payload = extract_handoff(full_text)

        # 4. Persist the assistant turn.
        async with AsyncSessionLocal() as wdb:
            wdb.add(ChatMessage(
                session_id=session.id,
                role="assistant",
                content=clean_text,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                created_at=datetime.now(timezone.utc),
            ))
            await wdb.commit()

        # 5. If agent signalled launch, check quota then fire.
        if handoff_payload:
            try:
                await _check_quota(current_user, db)
            except HTTPException as exc:
                detail = exc.detail
                msg = (detail.get("upgrade_message", "Daily limit reached.")
                       if isinstance(detail, dict) else str(detail))
                yield {"event": "error", "data": json.dumps({"message": msg})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return

            try:
                job_id, sse_token = await fire_optimizer(current_user, session, handoff_payload)
                yield {"event": "handoff", "data": json.dumps({"job_id": job_id, "sse_token": sse_token})}
            except HTTPException as exc:
                yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}

        yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}

    return EventSourceResponse(event_generator())
