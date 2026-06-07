"""
Resume Optimizer — FastAPI Backend
Provides endpoints for resume upload, JD analysis, pipeline execution (SSE),
and optimized resume download.
"""

import asyncio
import json
import logging
import os
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

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, UploadFile, File
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
from utils import cache as result_cache
from config import MAX_ITERATIONS, SCORE_TARGET, BACKEND_URL, FRONTEND_URL, MODEL_SCORER, MAX_UPLOAD_BYTES, MAX_RESUME_CHARS, MAX_JD_CHARS, STUCK_JOB_TIMEOUT_MINUTES
from agents.scorer import score_combined
from agents.fact_extractor import extract_claims
from agents.fabrication_guard import fabrication_guard
from orchestration.optimizer import run_optimization_async
from parsers.pdf_parser import parse_pdf
from parsers.docx_parser import parse_docx
from generators.docx_generator import generate_docx
import storage as _storage
from delta.writer import write_daily_usage, write_job_match, vacuum_old_matches
from scraper.scraper import scrape_jobs
from db.session import get_db, init_db, AsyncSessionLocal
from db.models import JobStatus, PipelineEvent, PipelineJob, Resume, User, ProviderCost, TokenBlocklist
from auth.router import router as auth_router, user_router
from auth.dependencies import decode_token, decode_sse_token, get_current_user, check_plan_limit
from dashboard.router import router as dashboard_router
from admin.router import router as admin_router


# ── App setup ────────────────────────────────────────────────────────────────

_EVENT_TTL_HOURS = 24  # delete PipelineEvent rows older than this
_last_vacuum_ts: float = 0.0


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
                from agents.optimizer_agent import cleanup_stale_sessions
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
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        response = await call_next(request)
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

_UPLOAD_MAGIC = {
    ".pdf":  b"%PDF-",
    ".docx": b"PK\x03\x04",
}


class AnalyzeJDRequest(BaseModel):
    jd_text: str = Field(..., max_length=MAX_JD_CHARS)


class RunPipelineRequest(BaseModel):
    job_id: str
    jd_text: str


class ScrapeJobsRequest(BaseModel):
    resume_id: str
    keywords: str
    per_source: int = Field(default=20, ge=1, le=50)


class GenerateDocRequest(BaseModel):
    resume_text: str


# ── Routes ───────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(check_plan_limit),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a .pdf or .docx resume file, parse it, store a PipelineJob row, and return the job_id.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx"):
        raise HTTPException(status_code=400, detail="Only .pdf and .docx files are supported.")

    job_id = str(uuid.uuid4())

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    expected_magic = _UPLOAD_MAGIC.get(ext, b"")
    if not contents[:8].startswith(expected_magic):
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match {ext} extension.",
        )

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(contents)
        tmp_path = f.name

    try:
        parser = parse_pdf if ext == ".pdf" else parse_docx
        parsed = await asyncio.wait_for(
            asyncio.to_thread(parser, tmp_path),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Resume parsing timed out. Try a simpler PDF or convert to .docx.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {str(e)}")
    finally:
        os.unlink(tmp_path)

    job = PipelineJob(
        id=uuid.UUID(job_id),
        user_id=current_user.id,
        original_filename=file.filename,
        resume_text=parsed["raw_text"],
        status=JobStatus.pending,
    )
    db.add(job)
    await db.commit()

    return {
        "job_id": job_id,
        "text": parsed["raw_text"],
        "structure": parsed["sections"],
    }


@app.post("/analyze-jd")
async def analyze_jd_endpoint(
    request: AnalyzeJDRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Analyze a job description and return extracted keywords, requirements, and skills.
    """
    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text cannot be empty.")

    try:
        result_dict = await analyze_jd(request.jd_text[:MAX_JD_CHARS])
        result = result_dict.get("text", result_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"JD analysis failed: {str(e)}")

    return result


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
        while True:
            async with AsyncSessionLocal() as db:
                evts_result = await db.execute(
                    select(PipelineEvent)
                    .where(PipelineEvent.job_id == job_uuid, PipelineEvent.id > last_event_id)
                    .order_by(PipelineEvent.id)
                    .limit(100)
                )
                events = evts_result.scalars().all()

                for evt in events:
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

            await asyncio.sleep(2.0)

    return EventSourceResponse(event_generator())


@app.get("/download/{resume_id}")
async def download_resume(
    resume_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download a completed optimized resume by Resume.id.
    Works for both pipeline-generated downloads and dashboard links.
    """
    try:
        resume_uuid = uuid.UUID(resume_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Resume not found.")

    result = await db.execute(select(Resume).where(Resume.id == resume_uuid))
    resume = result.scalar_one_or_none()
    if not resume or str(resume.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Resume not found.")

    if not resume.file_path:
        raise HTTPException(status_code=404, detail="Output file not found.")

    url = await asyncio.to_thread(_storage.generate_download_url, resume.file_path)
    if url.startswith("http"):
        return RedirectResponse(url, status_code=302)
    return FileResponse(
        path=url,
        filename=f"optimized_{resume.original_filename or 'resume'}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ── Generate-doc endpoint ────────────────────────────────────────────────────

@app.post("/generate-doc")
async def generate_doc_endpoint(
    request: GenerateDocRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Generate a formatted .docx from the provided resume text without running
    the optimization pipeline. The user's text is trusted as-is — no AI rewriting.
    Works for raw uploads, inline-edited text, and (future) saved profiles.
    """
    if not request.resume_text.strip():
        raise HTTPException(status_code=400, detail="resume_text cannot be empty.")

    doc_id = str(uuid.uuid4())
    blob_name = f"gen_{doc_id}.docx"

    tmp_docx = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _f:
            tmp_docx = _f.name
        await asyncio.to_thread(generate_docx, request.resume_text, tmp_docx)
        docx_bytes = await asyncio.to_thread(Path(tmp_docx).read_bytes)
        await asyncio.to_thread(_storage.upload_output, docx_bytes, blob_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate document: {str(e)}")
    finally:
        if tmp_docx is not None:
            os.unlink(tmp_docx)

    url = await asyncio.to_thread(_storage.generate_download_url, blob_name)
    if url.startswith("http"):
        return RedirectResponse(url, status_code=302)
    return FileResponse(
        path=url,
        filename="resume.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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
        for posting in postings:
            record = {
                "user_id":   user_id,
                "resume_id": request.resume_id,
                **posting,
            }
            try:
                await asyncio.to_thread(write_job_match, record)
            except Exception:
                _logger.warning("write_job_match failed for posting: %s", posting.get("title", "unknown"))

    background_tasks.add_task(_persist)

    return {
        "total":    len(postings),
        "keywords": request.keywords,
        "results":  postings,
    }


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

        # ── Increment rate-limit counter at job START (transactional) ──────
        # Upsert so the first run of the day creates the row atomically.
        # Counter is read in check_plan_limit before this runs, so incrementing
        # at start (not end) prevents concurrent bypass of daily limits.
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
                _logger.warning("job=%s: failed to increment daily usage counter", job_id)

        total_input_tokens  = 0
        total_output_tokens = 0

        # ── Phase 1: Deterministic setup (no DB held) ──────────────────
        ledger = await asyncio.to_thread(extract_claims, resume_text)

        await emit({"type": "stage", "message": "Analyzing Job Description...", "stage": "jd_analysis"})
        jd_result_dict = await analyze_jd(jd_text)
        jd_result  = jd_result_dict.get("text", jd_result_dict)
        jd_tokens  = jd_result_dict.get("tokens", {"input_tokens": 0, "output_tokens": 0})
        jd_keywords: list[str] = jd_result.get("keywords", [])
        total_input_tokens  += jd_tokens["input_tokens"]
        total_output_tokens += jd_tokens["output_tokens"]
        await emit({"type": "stage", "message": f"JD analyzed — {len(jd_keywords)} keywords extracted.",
                    "stage": "jd_analysis", "keywords": jd_keywords[:20]})

        await emit({"type": "stage", "message": "Scoring original resume...", "stage": "score"})
        baseline_dict   = await score_combined(resume_text, jd_text, jd_keywords)
        baseline_scores = baseline_dict.get("text", baseline_dict)
        baseline_tokens = baseline_dict.get("tokens", {"input_tokens": 0, "output_tokens": 0})
        total_input_tokens  += baseline_tokens["input_tokens"]
        total_output_tokens += baseline_tokens["output_tokens"]

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
        if baseline_avg < SCORE_TARGET:
            await emit({"type": "stage", "message": "Starting agentic optimization...", "stage": "agent"})
            agent_result = await run_optimization_async(
                job_id=job_id,
                resume_text=resume_text,
                jd_keywords=jd_keywords,
                claims_ledger=ledger,
                scores=baseline_scores,
                on_event=_on_agent_event,
            )
            current_resume      = agent_result["text"]
            total_input_tokens  += agent_result.get("input_tokens", 0)
            total_output_tokens += agent_result.get("output_tokens", 0)
        else:
            current_resume = resume_text

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
                        original_filename=original_filename,
                        file_path=blob_name,
                        jd_text=jd_text,
                        final_score=float(scores.get("average", baseline_avg)),
                        scores_json=scores,
                        iterations=1,
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
            iteration=1,
        )

        # ── Calculate cost (short-lived session) ─────────────────────
        cost_cents = 0
        try:
            async with AsyncSessionLocal() as db:
                cost_result = await db.execute(
                    select(ProviderCost).where(
                        (ProviderCost.provider == "Google") & (ProviderCost.active == True)
                    )
                )
                cost_row = cost_result.scalar_one_or_none()
                if cost_row:
                    input_cost_dollars  = (total_input_tokens  / 1_000_000) * cost_row.input_cost_per_1m_tokens
                    output_cost_dollars = (total_output_tokens / 1_000_000) * cost_row.output_cost_per_1m_tokens
                    cost_cents = int((input_cost_dollars + output_cost_dollars) * 100)
        except Exception:
            pass

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
        await emit({
            "type":         "done",
            "message":      "Resume optimization complete! Your optimized resume is ready.",
            "download_url": download_url,
            "final_score":  scores.get("average", baseline_avg),
            "iterations":   1,
            "cost_cents":   cost_cents,
            "tokens":       {"input": total_input_tokens, "output": total_output_tokens},
        })

    except Exception as e:
        await update_job(status=JobStatus.error, error_message=str(e))
        await emit({"type": "error", "message": f"Pipeline error: {str(e)}"})
