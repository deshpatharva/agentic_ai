"""Fire the existing optimizer pipeline when the agent emits [READY_TO_OPTIMIZE].
Also handles [SAVE_PROFILE] — creating a real Profile from the session's last_result.
"""

import asyncio
import uuid
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from agents.fact_extractor import extract_claims
from agents.jd_analyzer import analyze_jd
from agents.scorer import score_combined
from agents.tools import ResumeState
from config import SCORE_DIMENSIONS
from db.models import ChatSession, JobStatus, PipelineJob, Profile, User
from db.session import AsyncSessionLocal
from orchestration.agent_loop import run_agent
from utils.optimization_report import build_report, merge_honest_gaps
from utils.profile_utils import sections_to_text
from utils.section_parser import detect_sections

# Strong refs to fire-and-forget pipeline tasks so the event loop doesn't
# garbage-collect them mid-run (per asyncio docs) — a dropped task would silently
# abort the user's optimization.
_background_tasks: set = set()


async def _parse_sections(raw_text: str) -> dict:
    """Lazy wrapper around profiles.router._parse_sections.

    Defined at module level so tests can patch ``handoff._parse_sections``.
    The actual import is deferred to avoid heavy startup dependencies from
    profiles.router being pulled in at module load time.
    """
    from profiles.router import _parse_sections as _ps  # noqa: PLC0415
    return await _ps(raw_text)


def _resolve_profile_by_label(profile_id_str: str, user_profiles: list) -> "Profile | None":
    """Resolve an agent-emitted label to one of the user's profiles.

    Delegates to the hardened state_machine matcher (exact match, else a
    length/ratio-guarded substring) so a short or generic label ('eng') can't
    incidentally select — and launch a paid run against — the wrong profile.
    This is the paid path, so it must not be looser than the deterministic one.
    """
    from chat.state_machine import _find_profile_by_label  # noqa: PLC0415 — avoid circular
    by_label = [{"label": p.label or "", "_prof": p} for p in user_profiles]
    match = _find_profile_by_label(profile_id_str, by_label)
    return match["_prof"] if match is not None else None


async def fire_optimizer(
    user: User,
    session: ChatSession,
    handoff: dict,
    reserved_on: date | None = None,
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

        if prof is None and profile_id_str.strip():
            # Fallback: resolve by label (handles agent emitting a label or a
            # quoted label instead of the UUID), using the hardened matcher.
            user_profiles = (
                await db.execute(select(Profile).where(Profile.user_id == user.id))
            ).scalars().all()
            prof = _resolve_profile_by_label(profile_id_str, user_profiles)

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
            quota_reserved_on=reserved_on,
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
    _task = asyncio.create_task(_run_pipeline_task(job_id, str(user.id)))
    _background_tasks.add(_task)
    _task.add_done_callback(_background_tasks.discard)

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


def _flat_scores(scores: dict) -> dict:
    """Pull the scoring dimensions into a flat {dim: int} dict."""
    return {
        d: (scores[d]["score"] if isinstance(scores.get(d), dict) else int(scores.get(d, 0) or 0))
        for d in SCORE_DIMENSIONS
    }


def _avg_dims(flat: dict) -> int:
    """Average across all canonical scoring dimensions.

    Must iterate the same SCORE_DIMENSIONS tuple the pipeline uses (config.py) so
    an edit-path final_score is computed identically to a pipeline final_score —
    otherwise the two are silently incomparable.
    """
    return round(sum(flat.get(k, 0) for k in SCORE_DIMENSIONS) / len(SCORE_DIMENSIONS))


async def apply_edit(user, session, arguments: dict) -> dict:
    """Apply a targeted, user-instructed edit via the optimizer agent."""
    instruction = (arguments.get("instruction") or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Tell me what you'd like to change.")

    ctx = dict(session.context or {})
    last_result = ctx.get("last_result")

    # Block edits while an optimization is still running (launched but no result yet).
    if ctx.get("_optimizer_launched") and not last_result:
        raise HTTPException(
            status_code=409,
            detail="An optimization is in progress — wait for it to finish before making manual edits.",
        )

    # ── Resolve source text + pre-edit scores ────────────────────────────────
    if last_result:
        source_text = last_result.get("optimized_text") or sections_to_text(last_result.get("sections") or {})
        raw_scores = last_result.get("scores") or {}
        scores_before = _flat_scores(raw_scores)
    else:
        profile_id = str(arguments.get("profile_id", "") or "")
        try:
            pid = uuid.UUID(profile_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Nothing to edit yet — run the optimizer first, or tell me which saved profile to update.",
            )
        async with AsyncSessionLocal() as db:
            from db.models import Profile
            prof = await db.scalar(
                select(Profile).where(Profile.id == pid, Profile.user_id == user.id)
            )
            if not prof:
                raise HTTPException(
                    status_code=400,
                    detail="Couldn't find that profile. Please pick one from the list.",
                )
            source_text = prof.raw_text or sections_to_text(prof.sections or {})
        scores_before = None  # computed below from baseline scoring

    if not source_text.strip():
        raise HTTPException(status_code=400, detail="That resume has no text to edit.")

    jd_text = ctx.get("jd_text", "") or ""

    # ── Phase-1-lite: claims, JD analysis, baseline scoring ──────────────────
    ledger = await asyncio.to_thread(extract_claims, source_text)
    if jd_text:
        jd_dict = await analyze_jd(jd_text)
        jd_result = jd_dict.get("text", jd_dict) or {}
    else:
        jd_result = {}
    jd_keywords = jd_result.get("keywords", []) or []
    seniority = jd_result.get("seniority_level", "mid")
    required_hard_skills = jd_result.get("required_hard_skills", []) or []

    baseline_dict = await score_combined(
        source_text, jd_text, jd_keywords=jd_keywords,
        seniority_level=seniority, required_hard_skills=required_hard_skills,
    )
    baseline_scores = baseline_dict.get("text", {}) or {}
    if scores_before is None:
        scores_before = _flat_scores(baseline_scores)

    # ── Run the agent with the user's instruction injected ───────────────────
    sections = detect_sections(source_text)
    available_metrics = ""
    if ledger and hasattr(ledger, "metrics") and ledger.metrics:
        available_metrics = ", ".join(sorted(ledger.metrics)[:15])
    state = ResumeState(sections=sections, available_metrics=available_metrics, capabilities=ledger.capabilities)

    agent_result = await run_agent(
        state=state,
        scores=baseline_scores,
        jd_text=jd_text,
        jd_keywords=jd_keywords,
        ledger=ledger,
        original_resume=source_text,
        seniority_level=seniority,
        required_hard_skills=required_hard_skills,
        user_instruction=instruction,
        max_reflections=2,
    )

    edited_text = (agent_result.get("text") or "").strip()
    if not edited_text or edited_text == source_text.strip():
        raise HTTPException(
            status_code=422,
            detail="The edit produced no change — your resume is unchanged.",
        )

    from agents.fabrication_guard import fabrication_guard  # noqa: PLC0415
    from agents.verifier import verify_final_draft  # noqa: PLC0415
    guard = await asyncio.to_thread(fabrication_guard, edited_text, ledger, source_text)
    edited_text = guard.text
    vr = await verify_final_draft(edited_text, ledger, source_text)
    verifier_flagged = vr.flagged
    honest_gaps = merge_honest_gaps(agent_result.get("honest_gaps", []), guard.capability_gaps)

    # ── Re-score the edited draft ─────────────────────────────────────────────
    new_dict = await score_combined(
        edited_text, jd_text, jd_keywords=jd_keywords,
        seniority_level=seniority, required_hard_skills=required_hard_skills,
    )
    new_scores = new_dict.get("text", {}) or {}
    new_flat = _flat_scores(new_scores)
    new_scores_for_report = {**new_scores, "average": _avg_dims(new_flat)}

    report = build_report(
        jd_result=jd_result,
        original_text=source_text,
        optimized_text=edited_text,
        baseline_score=_avg_dims(scores_before),
        final_scores=new_scores_for_report,
        iterations=agent_result.get("iterations", 1),
        honest_gaps=honest_gaps,
    )

    # ── Re-parse into rich profile sections (for save/docx) ──────────────────
    new_sections = await _parse_sections(edited_text)

    sections_changed = list((report.get("section_diff") or {}).keys())

    # ── Write back to session.context["last_result"] ─────────────────────────
    async with AsyncSessionLocal() as db:
        sess_row = await db.get(ChatSession, session.id)
        if sess_row:
            new_ctx = dict(sess_row.context or {})
            prev = dict(new_ctx.get("last_result") or {})
            prev.update({
                "sections":         new_sections or {},
                "optimized_text":   edited_text,
                "final_score":      float(new_scores_for_report["average"]),
                "scores":           new_flat,
                "report":           report,
                "verifier_flagged": list(verifier_flagged),
                "honest_gaps":      honest_gaps,
            })
            new_ctx["last_result"] = prev
            sess_row.context = new_ctx
            sess_row.updated_at = datetime.now(timezone.utc)
            await db.commit()

    return {
        "sections_changed": sections_changed,
        "scores":           new_flat,
        "scores_before":    scores_before,
        "verifier_flagged": list(verifier_flagged),
        "honest_gaps":      honest_gaps,
    }
