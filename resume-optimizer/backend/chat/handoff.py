"""Fire the existing optimizer pipeline when the agent emits [READY_TO_OPTIMIZE]."""

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
