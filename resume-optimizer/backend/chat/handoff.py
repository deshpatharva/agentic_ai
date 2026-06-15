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

    # The agent emits the profile UUID, but sometimes emits the LABEL instead
    # (e.g. 'Senior Data Engineer'). Accept either: try UUID, else match by label.
    profile_uuid: uuid.UUID | None = None
    try:
        profile_uuid = uuid.UUID(profile_id_str)
    except (ValueError, TypeError):
        profile_uuid = None

    async with AsyncSessionLocal() as db:
        prof = None
        if profile_uuid is not None:
            prof = await db.scalar(
                select(Profile).where(
                    Profile.id == profile_uuid,
                    Profile.user_id == user.id,
                )
            )

        if prof is None:
            # Fallback: resolve by label (handles agent emitting a label or
            # a quoted label instead of the UUID).
            candidate = profile_id_str.strip().strip('"').strip("'").lower()
            if candidate:
                user_profiles = (
                    await db.execute(select(Profile).where(Profile.user_id == user.id))
                ).scalars().all()
                # Exact label match first, then a contains-match either direction.
                prof = next(
                    (p for p in user_profiles if (p.label or "").strip().lower() == candidate),
                    None,
                )
                if prof is None:
                    prof = next(
                        (p for p in user_profiles
                         if candidate in (p.label or "").lower()
                         or ((p.label or "").strip().lower() and (p.label or "").strip().lower() in candidate)),
                        None,
                    )

        if not prof:
            raise HTTPException(
                status_code=400,
                detail="Couldn't match that profile. Please pick a profile from the list.",
            )

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


async def resolve_profile_download(user: User, profile_id: str) -> dict:
    """Validate the profile is owned by the user and return its docx download URL.

    The actual .docx is generated on the fly by GET /download-profile/{id}; this
    just confirms ownership and hands back the relative URL + label.
    Raises HTTPException on bad/foreign profile.
    """
    try:
        pid = uuid.UUID(str(profile_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Couldn't find that profile. Please pick one from the list.")

    async with AsyncSessionLocal() as db:
        prof = await db.scalar(
            select(Profile).where(Profile.id == pid, Profile.user_id == user.id)
        )
        if not prof:
            raise HTTPException(status_code=404, detail="Profile not found or not owned by user.")
        return {"download_url": f"/download-profile/{pid}", "label": prof.label or "resume"}


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
