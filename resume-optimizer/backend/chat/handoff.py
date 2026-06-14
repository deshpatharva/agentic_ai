"""Fire the existing optimizer pipeline when the agent emits [READY_TO_OPTIMIZE].
Also handles [SAVE_PROFILE] — creating a real Profile from the session's last_result.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from db.models import ChatSession, JobStatus, PipelineJob, Profile, User
from db.session import AsyncSessionLocal
from utils.profile_utils import sections_to_text


async def fire_optimizer(
    user: User,
    session: ChatSession,
    handoff: dict,
) -> tuple[str, str]:
    """Seed a PipelineJob from the agent's handoff payload and enqueue the pipeline.

    Replicates the exact steps of POST /profile/prepare-job + POST /run-pipeline so
    the optimizer behaviour is identical — the agent is just the new front door.

    Returns (job_id_str, sse_token) so the frontend can subscribe to /status/{job_id}.
    Raises HTTPException on ownership/validation failures (surfaced as SSE error events).
    """
    from auth.router import _mint_sse_token  # imported here to avoid circular at module level

    profile_id_str = handoff.get("profile_id", "")
    instruction = handoff.get("instruction", "") or ""
    jd_text = (session.context or {}).get("jd_text", "")

    if not jd_text:
        raise HTTPException(status_code=400, detail="Cannot launch: no job description in session.")

    try:
        profile_uuid = uuid.UUID(profile_id_str)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid profile_id in agent handoff.")

    async with AsyncSessionLocal() as db:
        prof = await db.scalar(
            select(Profile).where(
                Profile.id == profile_uuid,
                Profile.user_id == user.id,
            )
        )
        if not prof:
            raise HTTPException(status_code=404, detail="Profile not found or not owned by user.")

        resume_text = sections_to_text(prof.sections or {}) or "Resume text not available."

        now = datetime.now(timezone.utc)
        job = PipelineJob(
            user_id=user.id,
            profile_id=prof.id,
            original_filename=f"{prof.label or 'profile'}.txt",
            resume_text=resume_text,
            jd_text=jd_text,
            status=JobStatus.running,
            created_at=now,
            updated_at=now,
        )
        if instruction:
            # Append instruction as a comment in jd_text (run-pipeline already reads it via
            # RunPipelineRequest.instruction which overwrites job.jd_text — we embed it here
            # so _run_pipeline_task can pick it up from the persisted row).
            job.jd_text = f"{jd_text}\n\n[USER INSTRUCTION: {instruction}]"

        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = str(job.id)

        # Link the conversation to its pipeline run.
        sess = await db.get(ChatSession, session.id)
        if sess:
            sess.job_id = job.id
            sess.updated_at = datetime.now(timezone.utc)
            await db.commit()

    # Enqueue using the same background task the legacy route uses.
    from main import _run_pipeline_task  # noqa: PLC0415 — intentional late import (circular)
    asyncio.create_task(_run_pipeline_task(job_id, str(user.id)))

    sse_token = _mint_sse_token(str(user.id))
    return job_id, sse_token


async def save_profile_from_session(
    user: User,
    session: ChatSession,
    payload: dict,
) -> dict:
    """Create (or update) a Profile from the session's last_result.

    Called when the agent emits [SAVE_PROFILE: {"label": "..."}].
    Returns {"profile_id": str, "label": str}.
    Raises HTTPException on failure (surfaced as SSE error event).
    """
    label = (payload.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Profile label cannot be blank.")

    ctx = session.context or {}
    last_result = ctx.get("last_result")
    if not last_result:
        raise HTTPException(
            status_code=400,
            detail="No optimized resume found in this session. Run the optimizer first.",
        )

    sections = last_result.get("sections") or {}
    raw_text = last_result.get("optimized_text") or sections_to_text(sections)

    async with AsyncSessionLocal() as db:
        # Dedup: if a profile with the same label already exists, update it.
        existing = await db.scalar(
            select(Profile).where(Profile.user_id == user.id, Profile.label == label)
        )
        now = datetime.now(timezone.utc)
        if existing:
            existing.sections = sections
            existing.raw_text = raw_text
            existing.label_confirmed = True
            existing.updated_at = now
            await db.commit()
            return {"profile_id": str(existing.id), "label": label}

        new_profile = Profile(
            user_id=user.id,
            label=label,
            label_confirmed=True,
            sections=sections,
            raw_text=raw_text,
            created_at=now,
            updated_at=now,
        )
        db.add(new_profile)
        await db.commit()
        await db.refresh(new_profile)
        return {"profile_id": str(new_profile.id), "label": label}
