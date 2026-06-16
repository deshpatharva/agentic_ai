"""
Resume Optimizer — FastAPI Backend
Provides endpoints for resume upload, JD analysis, pipeline execution (SSE),
and optimized resume download.
"""

import asyncio
import json
import logging
import os
import re
import signal
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend/ is on the path regardless of where uvicorn is launched from
sys.path.insert(0, str(Path(__file__).parent))
from logging_config import setup_logging
setup_logging()

# On startup, emit the checkpoint log written by init_db during the previous crash.
# This runs before heavy imports so it appears in the log stream even if we OOM again.
_dbg_path = "/home/debug_init.log"
if os.path.exists(_dbg_path):
    try:
        with open(_dbg_path) as _dbg_f:
            _dbg_contents = _dbg_f.read()
        print(f"=== CRASH DEBUG LOG (prev run) ===\n{_dbg_contents}=== END CRASH LOG ===", flush=True)
        os.remove(_dbg_path)
    except Exception:
        pass

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from limiter import limiter
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import delete, select, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

# ── Agent & utility imports ──────────────────────────────────────────────────
from agents.jd_analyzer import analyze_jd
from config import MAX_ITERATIONS, SCORE_TARGET, BACKEND_URL, FRONTEND_URL, MODEL_SCORER, MAX_RESUME_CHARS, MAX_JD_CHARS, STUCK_JOB_TIMEOUT_MINUTES, DATABASE_URL
from agents.scorer import score_combined
from agents.fact_extractor import extract_claims
from agents.fabrication_guard import fabrication_guard
from agents.humanizer import humanize_resume
from orchestration.optimizer import run_optimization_async, _WORK_THRESHOLD
from generators.docx_generator import generate_docx
from utils.skills_normalizer import normalize_skills
from utils.section_parser import detect_sections as _detect_sections
import storage as _storage
from delta.writer import write_daily_usage, write_job_matches, vacuum_old_matches
from scraper.scraper import scrape_jobs
from db.session import get_db, init_db, AsyncSessionLocal
from db.models import JobStatus, PipelineEvent, PipelineJob, Profile, Resume, User, TokenBlocklist
from utils.profile_utils import sections_to_text as _sections_to_text
from auth.router import router as auth_router, user_router
from auth.dependencies import decode_token, decode_sse_token, get_current_user, check_plan_limit
from dashboard.router import router as dashboard_router
from admin.router import router as admin_router
from profiles.router import router as profiles_router, profile_ops as profile_ops_router
from jd.router import router as jd_router
from chat.router import router as chat_router


# ── App setup ────────────────────────────────────────────────────────────────

_EVENT_TTL_HOURS = 24  # delete PipelineEvent rows older than this
_last_vacuum_ts: float = 0.0
_is_postgres = DATABASE_URL.startswith("postgresql")


async def _cleanup_events():
    """Periodically delete PipelineEvent rows older than EVENT_TTL_HOURS."""
    while True:
        await asyncio.sleep(3600)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_EVENT_TTL_HOURS)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(PipelineEvent).where(PipelineEvent.created_at < cutoff))
            await db.commit()


_logger = logging.getLogger(__name__)


async def _reap_once(db: AsyncSession) -> list[str]:
    """Find stuck running jobs and mark them error. Returns list of reaped IDs."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
    result = await db.execute(
        select(PipelineJob).where(
            PipelineJob.status == JobStatus.running,
            PipelineJob.updated_at < cutoff,
        )
    )
    stuck = result.scalars().all()
    if not stuck:
        return []
    now = datetime.now(timezone.utc)
    ids = []
    for job in stuck:
        job.status = JobStatus.error
        job.error_message = "Job timed out — worker may have restarted."
        job.updated_at = now
        ids.append(str(job.id))
    await db.commit()
    return ids


async def _reap_stuck_jobs():
    """Periodically mark stuck running jobs as error (every 5 minutes).
    Also runs vacuum_old_matches weekly and cleans stale agent sessions.
    """
    global _last_vacuum_ts
    while True:
        await asyncio.sleep(300)
        try:
            async with AsyncSessionLocal() as db:
                ids = await _reap_once(db)
                if ids:
                    _logger.warning("Reaped %d stuck jobs: %s", len(ids), ids)
                # Clean up expired blocklist entries
                await db.execute(
                    delete(TokenBlocklist).where(
                        TokenBlocklist.expires_at < datetime.now(timezone.utc)
                    )
                )
                await db.commit()
            try:
                from agents.tools import cleanup_stale_sessions
                stale = cleanup_stale_sessions()
                if stale:
                    _logger.info("Cleaned up %d stale pipeline sessions", stale)
            except Exception:
                pass
        except Exception:
            _logger.exception("Reaper cycle failed — will retry in 5 minutes")

        now = time.time()
        if now - _last_vacuum_ts >= 7 * 24 * 3600:
            try:
                await asyncio.to_thread(vacuum_old_matches)
                _last_vacuum_ts = now
                _logger.info("vacuum_old_matches completed")
            except Exception:
                _logger.exception("vacuum_old_matches failed — will retry next week")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    cleanup_task = asyncio.create_task(_cleanup_events())
    reap_task = asyncio.create_task(_reap_stuck_jobs())

    # On SIGTERM (gunicorn graceful shutdown), log so operators know in-flight
    # pipeline tasks may be cancelled. The stuck-job reaper marks them as error
    # on the next worker start. A proper task queue (ARQ/Celery) would be needed
    # for zero-loss shutdown guarantees.
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(
        signal.SIGTERM,
        lambda: _logger.warning("SIGTERM received — in-flight pipeline tasks will be marked error by reaper on next start"),
    )

    yield
    cleanup_task.cancel()
    reap_task.cancel()


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        from observability.trace import _trace_id
        request_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        token = _trace_id.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            _trace_id.reset(token)
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        _logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = request_id
        return response


app = FastAPI(title="Resume Optimizer API", version="1.0.0", lifespan=lifespan)

_ALLOWED_ORIGINS = list({FRONTEND_URL, "http://localhost:5173", "http://localhost:5174"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(LoggingMiddleware)

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(profiles_router, prefix="/profiles", tags=["profiles"], dependencies=[Depends(get_current_user)])
app.include_router(profile_ops_router, prefix="/profile", tags=["profiles"], dependencies=[Depends(get_current_user)])
app.include_router(jd_router, tags=["jd"])
app.include_router(chat_router)


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Liveness probe — no auth required."""
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    storage_status = await asyncio.to_thread(_storage.ping_storage)

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
    stuck_count = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.status == JobStatus.running,
                PipelineJob.updated_at < cutoff,
            )
        )
    ).scalar() or 0

    pending_count = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.status == JobStatus.pending,
            )
        )
    ).scalar() or 0

    overall_status = "ok" if (db_ok and storage_status != "error") else "degraded"
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status": overall_status,
            "db": "ok" if db_ok else "error",
            "storage": storage_status,
            "stuck_jobs": stuck_count,
            "pending_jobs": pending_count,
        },
    )


# ── Directory setup ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

# ── Request/response models ──────────────────────────────────────────────────

class RunPipelineRequest(BaseModel):
    job_id: str
    jd_text: str
    instruction: str = ""
    profile_id: str = ""


class ScrapeJobsRequest(BaseModel):
    resume_id: str
    keywords: str
    per_source: int = Field(default=20, ge=1, le=50)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.post("/run-pipeline")
async def run_pipeline(
    request: RunPipelineRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(check_plan_limit),
    db: AsyncSession = Depends(get_db),
):
    """
    Start the optimization pipeline for a previously uploaded resume.
    Returns immediately; progress is streamed via SSE at /status/{job_id}.
    """
    try:
        job_uuid = uuid.UUID(request.job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found.")

    result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_uuid))
    job = result.scalar_one_or_none()
    # Return 404 (not 403) to avoid leaking whether the job exists at all
    if not job or str(job.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Job not found. Upload a resume first.")

    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text cannot be empty.")

    if request.profile_id:
        try:
            pid = uuid.UUID(request.profile_id)
            prof_result = await db.execute(
                select(Profile).where(Profile.id == pid, Profile.user_id == current_user.id)
            )
            prof = prof_result.scalar_one_or_none()
            if prof and prof.sections:
                job.resume_text = _sections_to_text(prof.sections)
            if prof:
                job.profile_id = prof.id
        except ValueError:
            pass

    job.jd_text = request.jd_text
    job.status = JobStatus.running
    job.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(_run_pipeline_task, str(job_uuid), str(current_user.id))

    return {"job_id": str(job_uuid), "status": "started"}


@app.get("/status/{job_id}")
async def stream_status(
    job_id: str,
    request: Request,
    token: str = Query(None),
):
    """
    SSE endpoint — streams pipeline progress events.
    Auth: pass the JWT as ?token=<jwt> (EventSource cannot send Authorization headers).
    Reconnection: send Last-Event-ID header; resumes from that event sequence number.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Token required. Pass ?token=<jwt>.")

    user_id = decode_sse_token(token)  # raises 401 if invalid or not an SSE token

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found.")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_uuid))
        job = result.scalar_one_or_none()

    if not job or (job.user_id and str(job.user_id) != user_id):
        raise HTTPException(status_code=404, detail="Job not found.")

    # Reconnection: honour Last-Event-ID sent by EventSource on reconnect
    last_event_id_str = request.headers.get("Last-Event-ID", "0")
    try:
        last_event_id = int(last_event_id_str)
    except ValueError:
        last_event_id = 0

    async def event_generator():
        nonlocal last_event_id
        _notify = asyncio.Event()
        _pg_conn = None

        if _is_postgres:
            try:
                import asyncpg as _asyncpg
                _pg_dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
                _pg_conn = await _asyncpg.connect(_pg_dsn)
                await _pg_conn.add_listener(
                    f"pipeline_{job_id}",
                    lambda _c, _pid, _ch, _payload: _notify.set(),
                )
            except Exception:
                _pg_conn = None

        try:
            while True:
                got_events = False
                async with AsyncSessionLocal() as db:
                    evts_result = await db.execute(
                        select(PipelineEvent)
                        .where(PipelineEvent.job_id == job_uuid, PipelineEvent.id > last_event_id)
                        .order_by(PipelineEvent.id)
                        .limit(100)
                    )
                    events = evts_result.scalars().all()

                    for evt in events:
                        got_events = True
                        last_event_id = evt.id
                        yield {"id": str(evt.id), "data": json.dumps(evt.event_json)}
                        if evt.event_json.get("type") in ("done", "error"):
                            return

                    # No new events — check if job already finished (handles post-restart reconnect)
                    if not events:
                        status_result = await db.execute(
                            select(PipelineJob.status).where(PipelineJob.id == job_uuid)
                        )
                        current_status = status_result.scalar()
                        if current_status in (JobStatus.done, JobStatus.error):
                            return

                if got_events:
                    continue  # more events may have arrived, re-query immediately

                if _pg_conn:
                    _notify.clear()
                    try:
                        await asyncio.wait_for(_notify.wait(), timeout=30.0)
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(2.0)
        finally:
            if _pg_conn:
                try:
                    await _pg_conn.close()
                except Exception:
                    pass

    return EventSourceResponse(event_generator())


@app.get("/download/{resume_id}")
async def download_resume(
    resume_id: str,
    request: Request,
    token: str = Query(None),
):
    """
    Download a completed optimized resume by Resume.id.
    Accepts auth via Authorization header OR ?token= query param so that
    a plain <a href="…?token=…"> works — browsers can't set headers on navigation.
    """
    # Resolve token from query param or Authorization header
    raw_token = token
    if not raw_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:]
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user_id = decode_token(raw_token)  # raises 401 on invalid token

    async with AsyncSessionLocal() as db:
        user_result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_id), User.is_active == True)
        )
        current_user = user_result.scalar_one_or_none()
        if not current_user:
            raise HTTPException(status_code=401, detail="User not found.")

        try:
            resume_uuid = uuid.UUID(resume_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Resume not found.")

        result = await db.execute(select(Resume).where(Resume.id == resume_uuid))
        resume = result.scalar_one_or_none()
        if resume and str(resume.user_id) == str(current_user.id) and resume.file_path:
            file_path = resume.file_path
            original_filename = resume.original_filename
        else:
            # Fallback: the done-event links /download/{job_id} when the Resume
            # row failed to save — resolve the blob via the completed job instead.
            job_result = await db.execute(
                select(PipelineJob).where(PipelineJob.id == resume_uuid)
            )
            job = job_result.scalar_one_or_none()
            if (
                not job
                or str(job.user_id) != str(current_user.id)
                or job.status != JobStatus.done
                or not job.download_path
            ):
                raise HTTPException(status_code=404, detail="Resume not found.")
            file_path = job.download_path
            original_filename = job.original_filename

    url = await asyncio.to_thread(_storage.generate_download_url, file_path)
    if url.startswith("http"):
        return RedirectResponse(url, status_code=302)
    return FileResponse(
        path=url,
        filename=f"optimized_{original_filename or 'resume'}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/download-profile/{profile_id}")
async def download_profile_docx(
    profile_id: str,
    request: Request,
    token: str = Query(None),
):
    """Generate and download a .docx of a saved profile AS-IS (no JD optimization).

    Auth via Authorization header OR ?token= so a plain <a href> download works.
    The docx is generated on the fly from the profile's sections — no storage round-trip.
    """
    raw_token = token
    if not raw_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:]
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user_id = decode_token(raw_token)

    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Profile not found.")

    from db.models import Profile as _Profile
    from utils.profile_utils import sections_to_text as _sections_to_text
    async with AsyncSessionLocal() as db:
        prof = await db.scalar(
            select(_Profile).where(_Profile.id == pid, _Profile.user_id == uuid.UUID(user_id))
        )
        if not prof:
            raise HTTPException(status_code=404, detail="Profile not found.")
        label = prof.label or "resume"
        resume_text = _sections_to_text(prof.sections or {}) or (prof.raw_text or "Resume text not available.")

    tmp_docx = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _f:
            tmp_docx = _f.name
        await asyncio.to_thread(generate_docx, resume_text, tmp_docx)
        docx_bytes = await asyncio.to_thread(Path(tmp_docx).read_bytes)
    finally:
        if tmp_docx is not None:
            try:
                os.unlink(tmp_docx)
            except OSError:
                pass

    safe = re.sub(r"[^A-Za-z0-9._ -]", "", label).strip() or "resume"
    from fastapi.responses import Response as _Response
    return _Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{safe}.docx"'},
    )


# ── Job scraper endpoint ──────────────────────────────────────────────────────

@app.post("/scrape-jobs")
async def scrape_jobs_endpoint(
    request: ScrapeJobsRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Scrape job postings from all active sources using provided keywords.
    Persists results to Delta Lake and returns them.
    """
    if not request.keywords.strip():
        raise HTTPException(status_code=400, detail="keywords cannot be empty.")

    if request.resume_id:
        try:
            resume_uuid = uuid.UUID(request.resume_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid resume_id format.")
        resume = await db.scalar(
            select(Resume).where(
                Resume.id == resume_uuid,
                Resume.user_id == current_user.id,
            )
        )
        if not resume:
            raise HTTPException(status_code=403, detail="Resume not found or access denied.")

    try:
        postings = await scrape_jobs(request.keywords.strip(), per_source=request.per_source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

    user_id = str(current_user.id)

    async def _persist():
        records = [
            {"user_id": user_id, "resume_id": request.resume_id, **posting}
            for posting in postings
        ]
        try:
            # Single Delta transaction for the whole batch — avoids one
            # commit + one tiny parquet file per posting.
            await asyncio.to_thread(write_job_matches, records)
        except Exception:
            _logger.warning("write_job_matches failed for %d postings", len(records))

    background_tasks.add_task(_persist)

    return {
        "total":    len(postings),
        "keywords": request.keywords,
        "results":  postings,
    }


# ── Auto-profile helper ───────────────────────────────────────────────────────

# Matches a standalone skills-section header line (so we can preserve it).
_SKILLS_HEADER_RE = re.compile(
    r"^(skills|technical\s+skills|core\s+competencies|competencies|technologies|tools)\s*:?\s*$",
    re.IGNORECASE,
)

# Words that signal a string is a requirement phrase, not a role title.
_BAD_LABEL_RE = re.compile(
    r"\b(years?|experience|must|required|responsib|nice to have|proficien|knowledge of)\b",
    re.I,
)
# Single generic terms that are too vague to be a profile name on their own.
_GENERIC_LABELS = {
    "tech", "technology", "it", "software", "engineering", "engineer",
    "general", "developer", "development", "professional", "role", "job",
}


def _clean_role_label(raw: str) -> str:
    """Sanitize a candidate role string into a clean profile label, or "" if unusable.

    Rejects requirement sentences / overly long phrases (e.g. "5+ Years Of Experience
    In Software Development") and vague single words (e.g. "tech") so auto-profiles get
    accurate names like "Senior Data Engineer".
    """
    s = " ".join((raw or "").split()).strip(" .,:;-—")
    if not s:
        return ""
    if len(s) > 48 or len(s.split()) > 6 or _BAD_LABEL_RE.search(s):
        return ""
    if s.lower() in _GENERIC_LABELS:
        return ""
    if s.islower() or s.isupper():
        s = s.title()
    return s


def _derive_auto_label(job_title: str, industry: str, jd_keywords: list[str]) -> str:
    """Build a human auto-profile label, preferring the JD's role title."""
    base = (
        _clean_role_label(job_title)
        or _clean_role_label(industry)
        or (_clean_role_label(jd_keywords[0]) if jd_keywords else "")
        or "Optimized Resume"
    )
    return f"{base} (auto)"


async def _resolve_or_create_profile(
    *,
    job_uuid,
    user_id: str,
    optimized_text: str,
    jd_text: str,
    jd_keywords: list[str],
    industry: str,
    job_title: str = "",
) -> "uuid.UUID | None":
    """Determine which profile this Resume should link to, creating a new one
    when the JD represents a domain not yet covered by existing profiles.

    Returns the profile UUID to store on Resume.profile_id, or None on failure.
    """
    from jd.router import _score_profiles
    from profiles.router import _parse_sections
    from config import DOMAIN_MATCH_THRESHOLD

    async with AsyncSessionLocal() as db:
        # Load source profile from the job.
        job_row = await db.scalar(select(PipelineJob).where(PipelineJob.id == job_uuid))
        source_profile_id = job_row.profile_id if job_row else None

        # Load all existing profiles for this user.
        profiles = (await db.execute(
            select(Profile).where(Profile.user_id == user_id)
        )).scalars().all()

        if not profiles:
            # No profiles yet — nothing to match against; skip auto-create too
            # (user needs to create their first profile manually).
            return source_profile_id

        profile_dicts = [
            {
                "id": str(p.id),
                "label": p.label or "",
                "skills": (p.sections or {}).get("skills", []),
                "summary": (p.sections or {}).get("summary", ""),
            }
            for p in profiles
        ]

        scored = await _score_profiles(profile_dicts, jd_text)
        top = max(scored, key=lambda x: x.get("match_pct", 0)) if scored else None
        top_pct = top.get("match_pct", 0) if top else 0

        if top_pct >= DOMAIN_MATCH_THRESHOLD:
            # Same domain — link to the best-matching existing profile.
            return uuid.UUID(top["id"])

        # New domain — derive a label from the JD's role title and auto-create a profile.
        auto_label = _derive_auto_label(job_title, industry, jd_keywords)

        # Dedup guard: skip if an (auto) profile with this label already exists.
        existing_auto = next(
            (p for p in profiles if p.label == auto_label), None
        )
        if existing_auto:
            return existing_auto.id

        # Parse the optimized text into structured sections.
        try:
            sections = await _parse_sections(optimized_text)
        except Exception:
            _logger.warning("job=%s: _parse_sections failed for auto-profile — linking source profile", job_uuid)
            return source_profile_id

        new_profile = Profile(
            user_id=user_id,
            label=auto_label,
            label_confirmed=False,
            raw_text=optimized_text,
            sections=sections,
        )
        db.add(new_profile)
        await db.commit()
        await db.refresh(new_profile)
        _logger.info("job=%s: auto-created profile %s (%s)", job_uuid, new_profile.id, auto_label)
        return new_profile.id


# ── Background pipeline task ─────────────────────────────────────────────────

async def _run_pipeline_task(job_id: str, user_id: str = ""):
    """
    3-phase optimization pipeline — each DB operation uses its own short-lived session.
    LLM calls happen entirely outside any DB context to avoid holding connections for minutes.
    Phase 1 (deterministic): claims extraction, JD analysis, baseline score.
    Phase 2 (agentic):       CrewAI Optimization Strategist with 4 targeted tools.
    Phase 3 (deterministic): fabrication guard, docx generation, persistence.
    """
    job_uuid = uuid.UUID(job_id)
    _loop = asyncio.get_event_loop()

    async def emit(event: dict):
        """Each SSE event gets its own short-lived DB connection."""
        async with AsyncSessionLocal() as db:
            evt = PipelineEvent(job_id=job_uuid, event_json=event)
            db.add(evt)
            if _is_postgres:
                await db.execute(
                    text("SELECT pg_notify(:ch, '')"),
                    {"ch": f"pipeline_{job_id}"},
                )
            await db.commit()

    async def update_job(**kwargs):
        """Each status update gets its own short-lived DB connection."""
        async with AsyncSessionLocal() as db:
            kwargs["updated_at"] = datetime.now(timezone.utc)
            await db.execute(
                update(PipelineJob).where(PipelineJob.id == job_uuid).values(**kwargs)
            )
            await db.commit()

    def _on_agent_event(event: dict):
        asyncio.run_coroutine_threadsafe(emit(event), _loop)

    try:
        # ── Load job (short-lived session, closed before any LLM call) ─────
        async with AsyncSessionLocal() as db:
            job_result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_uuid))
            job_row = job_result.scalar_one()
            resume_text: str = job_row.resume_text[:MAX_RESUME_CHARS]
            jd_text: str     = job_row.jd_text[:MAX_JD_CHARS]
            original_filename = job_row.original_filename

        total_input_tokens  = 0
        total_output_tokens = 0
        total_cost_usd      = 0.0

        # ── Phase 1: Deterministic setup (no DB held) ──────────────────
        ledger = await asyncio.to_thread(extract_claims, resume_text)

        await emit({"type": "stage", "message": "Analyzing Job Description...", "stage": "jd_analysis"})
        jd_result_dict = await analyze_jd(jd_text)
        jd_result  = jd_result_dict.get("text", jd_result_dict)
        jd_tokens  = jd_result_dict.get("tokens", {"input_tokens": 0, "output_tokens": 0})
        jd_keywords: list[str]     = jd_result.get("keywords", [])
        required_hard_skills: list = jd_result.get("required_hard_skills", [])
        seniority_level: str       = jd_result.get("seniority_level", "mid")
        industry: str              = jd_result.get("industry", "")
        job_title: str             = jd_result.get("job_title", "")
        total_input_tokens  += jd_tokens["input_tokens"]
        total_output_tokens += jd_tokens["output_tokens"]
        total_cost_usd      += jd_result_dict.get("cost_usd", 0.0)
        await emit({"type": "stage", "message": f"JD analyzed — {len(jd_keywords)} keywords extracted.",
                    "stage": "jd_analysis", "keywords": jd_keywords[:20]})

        await emit({"type": "stage", "message": "Scoring original resume...", "stage": "score"})
        baseline_dict   = await score_combined(
            resume_text,
            jd_text,
            jd_keywords=jd_keywords,
            seniority_level=seniority_level,
            required_hard_skills=required_hard_skills,
        )
        baseline_scores = baseline_dict.get("text", baseline_dict)
        baseline_tokens = baseline_dict.get("tokens", {"input_tokens": 0, "output_tokens": 0})
        total_input_tokens  += baseline_tokens["input_tokens"]
        total_output_tokens += baseline_tokens["output_tokens"]
        total_cost_usd      += baseline_dict.get("cost_usd", 0.0)

        baseline_avg = round(sum(baseline_scores[k]["score"] for k in ("ats", "impact", "skills_gap", "readability")) / 4)
        await emit({"type": "average", "score": baseline_avg, "iteration": 0,
                    "scores": {k: baseline_scores[k]["score"] for k in ("ats", "impact", "skills_gap", "readability")},
                    "message": f"Original resume score: {baseline_avg}"})

        scores = {**baseline_scores, "average": baseline_avg}

        if baseline_avg >= SCORE_TARGET:
            await emit({"type": "stage",
                        "message": f"Original resume already scores {baseline_avg} — skipping optimization.",
                        "stage": "agent"})

        # ── Phase 2: Agentic optimization (no DB held) ─────────────────
        _iter = 0
        if baseline_avg < SCORE_TARGET:
            current_resume  = resume_text
            current_scores  = baseline_scores
            current_avg     = baseline_avg

            for _iter in range(1, MAX_ITERATIONS + 1):
                await emit({"type": "stage",
                            "message": f"Starting agentic optimization (iteration {_iter}/{MAX_ITERATIONS})...",
                            "stage": "agent"})
                agent_result = await run_optimization_async(
                    job_id=job_id,
                    resume_text=current_resume,
                    jd_text=jd_text,
                    jd_keywords=jd_keywords,
                    claims_ledger=ledger,
                    scores=current_scores,
                    on_event=_on_agent_event,
                )
                optimized_text = agent_result["text"]
                total_input_tokens  += agent_result.get("input_tokens", 0)
                total_output_tokens += agent_result.get("output_tokens", 0)
                total_cost_usd      += agent_result.get("cost_usd", 0.0)

                if not optimized_text or optimized_text.strip() == current_resume.strip():
                    break  # no improvement, stop early

                current_resume = optimized_text

                # Re-score to check if target reached
                iter_score_dict   = await score_combined(
                    current_resume,
                    jd_text,
                    jd_keywords=jd_keywords,
                    seniority_level=seniority_level,
                    required_hard_skills=required_hard_skills,
                )
                current_scores = iter_score_dict.get("text", iter_score_dict)
                iter_tokens    = iter_score_dict.get("tokens", {"input_tokens": 0, "output_tokens": 0})
                total_input_tokens  += iter_tokens["input_tokens"]
                total_output_tokens += iter_tokens["output_tokens"]
                total_cost_usd      += iter_score_dict.get("cost_usd", 0.0)
                current_avg = round(
                    sum(current_scores[k]["score"] for k in ("ats", "impact", "skills_gap", "readability")) / 4
                )
                await emit({"type": "average", "score": current_avg, "iteration": _iter,
                            "scores": {k: current_scores[k]["score"] for k in ("ats", "impact", "skills_gap", "readability")},
                            "message": f"Score after iteration {_iter}: {current_avg}"})

                if current_avg >= _WORK_THRESHOLD:
                    break

            # Update scores dict to reflect final iteration scores
            scores = {**current_scores, "average": current_avg}
        else:
            current_resume = resume_text

        # ── Fabrication guard — flag unverified claims before rendering ────
        # CPU-bound (spaCy NER + difflib over the whole resume) — keep it off the event loop.
        guard_result = await asyncio.to_thread(fabrication_guard, current_resume, ledger, resume_text)
        if guard_result.gaps:
            _logger.warning(
                "fabrication_guard flagged %d unverified claims for job %s",
                len(guard_result.gaps),
                job_id,
            )
        current_resume = guard_result.text

        # ── Humanize after optimization + guard ────────────────────────────
        await emit({"type": "stage", "message": "Humanizing resume language...", "stage": "humanize"})
        try:
            humanize_result = await humanize_resume(
                current_resume,
                industry=industry,
                seniority_level=seniority_level,
            )
            current_resume = humanize_result.get("text", current_resume)
            humanize_tokens = humanize_result.get("tokens", {"input_tokens": 0, "output_tokens": 0})
            total_input_tokens  += humanize_tokens["input_tokens"]
            total_output_tokens += humanize_tokens["output_tokens"]
            total_cost_usd      += humanize_result.get("cost_usd", 0.0)
        except Exception:
            _logger.exception("job=%s: humanize_resume failed — skipping humanization", job_id)

        # ── Normalize skills section ───────────────────────────────────────
        # Reconcile experience→skills, dedup, strip filler — pure CPU, no LLM.
        try:
            from utils.skills_normalizer import categorize_skills as _categorize  # noqa: PLC0415
            _resume_sections = _detect_sections(current_resume)
            _skills_raw = _resume_sections.get("skills", "")
            _exp_raw    = _resume_sections.get("experience", "")
            if _skills_raw:
                # detect_sections INCLUDES the section header line (e.g. "Skills") as the
                # first line of the block. Preserve it so the docx keeps its SKILLS header.
                _skills_lines = _skills_raw.splitlines()
                _skills_header = _skills_lines[0] if _skills_lines and _SKILLS_HEADER_RE.match(_skills_lines[0].strip()) else ""

                _normalized_skills = normalize_skills(
                    _skills_raw,
                    experience_text=_exp_raw,
                    seniority=seniority_level,
                )
                # Deterministically group skills into labeled categories (Languages: ...,
                # Cloud & Platforms: ...) via a curated taxonomy — same input always yields
                # the same grouping. The docx generator bolds "Label: values" lines, giving
                # visually distinct skill groups in the output document with zero docx changes.
                from utils.skills_normalizer import _parse_skills as _ps  # noqa: PLC0415
                _skill_tokens = _ps(_normalized_skills)
                _categories = await _categorize(_skill_tokens, role_hint=industry or "")
                if len(_categories) > 1 or (len(_categories) == 1 and "" not in _categories):
                    # Build grouped skills text: "Category: a, b, c\nCategory2: d, e"
                    _grouped_lines = []
                    for _cat, _cat_skills in _categories.items():
                        if _cat:
                            _grouped_lines.append(f"{_cat}: {', '.join(_cat_skills)}")
                        else:
                            _grouped_lines.append(", ".join(_cat_skills))
                    # Re-attach the section header so the docx renders a SKILLS heading.
                    _body = "\n".join(_grouped_lines)
                    _new_skills_text = f"{_skills_header}\n{_body}" if _skills_header else f"Skills\n{_body}"
                    current_resume = current_resume.replace(_skills_raw, _new_skills_text, 1)
                else:
                    current_resume = current_resume.replace(_skills_raw, _normalized_skills, 1)
        except Exception:
            _logger.exception("job=%s: skills normalization failed — skipping", job_id)

        # Strip placeholder metrics ("[XX%]") and LaTeX "$" leakage so the cleaned
        # text is what we render, store in last_result, and parse into sections.
        try:
            from utils.text_sanitizer import sanitize_resume_text as _sanitize_text  # noqa: PLC0415
            current_resume = _sanitize_text(current_resume)
        except Exception:
            _logger.exception("job=%s: text sanitization failed — skipping", job_id)

        # ── Phase 3: Generate .docx (no DB held during file I/O) ───────────
        await emit({"type": "stage", "message": "Generating optimized .docx file...", "stage": "generate"})
        blob_name = f"{job_id}.docx"
        tmp_docx = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _f:
                tmp_docx = _f.name
            await asyncio.to_thread(generate_docx, current_resume, tmp_docx)
            docx_bytes = await asyncio.to_thread(Path(tmp_docx).read_bytes)
            await asyncio.to_thread(_storage.upload_output, docx_bytes, blob_name)
        finally:
            if tmp_docx is not None:
                os.unlink(tmp_docx)

        # ── Resolve profile link + auto-create profile for new domains ──
        # Best-effort: wrapped in try/except so it never fails the pipeline.
        resolved_profile_id = None
        if user_id:
            try:
                resolved_profile_id = await _resolve_or_create_profile(
                    job_uuid=job_uuid,
                    user_id=user_id,
                    optimized_text=current_resume,
                    jd_text=jd_text,
                    jd_keywords=jd_keywords,
                    industry=industry,
                    job_title=job_title,
                )
            except Exception:
                _logger.exception("job=%s: auto-profile resolution failed — skipping", job_id)

        # ── Persist Resume record (short-lived session) ────────────────
        resume_record = None
        if user_id:
            try:
                async with AsyncSessionLocal() as db:
                    ver_q = await db.execute(
                        select(func.coalesce(func.max(Resume.version), 0) + 1)
                        .where(Resume.user_id == user_id)
                    )
                    next_version = ver_q.scalar() or 1
                    resume_record = Resume(
                        user_id=user_id,
                        profile_id=resolved_profile_id,
                        original_filename=original_filename,
                        file_path=blob_name,
                        jd_text=jd_text,
                        final_score=float(scores.get("average", baseline_avg)),
                        scores_json=scores,
                        iterations=max(_iter, 1),
                        version=next_version,
                    )
                    db.add(resume_record)
                    await db.commit()
                    await db.refresh(resume_record)
            except Exception:
                _logger.exception(
                    "job=%s: Resume record save failed — download URL will use job_id fallback",
                    job_id,
                )

        await update_job(
            status=JobStatus.done,
            download_path=blob_name,
            scores_json=scores,
            iteration=max(_iter, 1),
            cost_usd=total_cost_usd,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

        # ── Increment quota counter — only on success so failures are free ──
        if user_id:
            try:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        text(
                            "INSERT INTO daily_usage_counters (user_id, date, runs) "
                            "VALUES (:uid, :date, 1) "
                            "ON CONFLICT (user_id, date) DO UPDATE "
                            "SET runs = daily_usage_counters.runs + 1"
                        ),
                        {"uid": user_id, "date": date_type.today().isoformat()},
                    )
                    await db.commit()
            except Exception:
                _logger.exception("job=%s: failed to increment usage counter", job_id)

        # ── Write Delta analytics (fire-and-forget, not rate limiting) ─────
        if user_id:
            try:
                await asyncio.to_thread(write_daily_usage, {
                    "user_id":       user_id,
                    "date":          date_type.today().isoformat(),
                    "pipeline_runs": 1,
                    "uploads":       1,
                    "input_tokens":  total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "tokens_used":   total_input_tokens + total_output_tokens,
                })
            except Exception:
                pass

        download_url = (
            f"/download/{resume_record.id}" if resume_record else f"/download/{job_id}"
        )

        # Grounded report of what changed / which gaps were filled, so the co-pilot
        # (and the score card) can present facts. Built once, reused below.
        optimization_report = None
        try:
            from utils.optimization_report import build_report as _build_report  # noqa: PLC0415
            optimization_report = _build_report(
                jd_result=jd_result,
                original_text=resume_text,
                optimized_text=current_resume,
                baseline_score=baseline_avg,
                final_scores=scores,
                iterations=max(_iter, 1),
            )
        except Exception:
            _logger.exception("job=%s: optimization report build failed", job_id)

        # ── Store optimized result in chat session context (enables save-as-profile) ──
        try:
            from profiles.router import _parse_sections as _ps  # noqa: PLC0415
            from db.models import ChatSession as _ChatSession  # noqa: PLC0415
            optimized_sections = await _ps(current_resume)
            async with AsyncSessionLocal() as db:
                sess_row = await db.scalar(
                    select(_ChatSession).where(_ChatSession.job_id == job_uuid)
                )
                if sess_row:
                    ctx = dict(sess_row.context or {})
                    ctx["last_result"] = {
                        "sections":       optimized_sections or {},
                        "optimized_text": current_resume,
                        "final_score":    float(scores.get("average", baseline_avg)),
                        "scores":         {k: scores[k]["score"] if isinstance(scores.get(k), dict)
                                           else scores.get(k, 0)
                                           for k in ("ats", "impact", "skills_gap", "readability")},
                        "iterations":     max(_iter, 1),
                        "download_url":   download_url,
                        "label_hint":     (_clean_role_label(job_title) or industry or ""),
                        "report":         optimization_report,
                    }
                    sess_row.context = ctx
                    sess_row.updated_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            _logger.exception("job=%s: failed to store last_result in session context", job_id)

        await emit({
            "type":         "done",
            "message":      "Resume optimization complete! Your optimized resume is ready.",
            "download_url": download_url,
            "final_score":  scores.get("average", baseline_avg),
            "iterations":   max(_iter, 1),
            "report":       optimization_report,
            "cost_usd":     round(total_cost_usd, 6),
            "tokens":       {"input": total_input_tokens, "output": total_output_tokens},
        })

    except Exception as e:
        await update_job(status=JobStatus.error, error_message=str(e))
        await emit({"type": "error", "message": f"Pipeline error: {str(e)}"})
