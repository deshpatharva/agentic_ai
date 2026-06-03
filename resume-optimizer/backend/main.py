"""
Resume Optimizer — FastAPI Backend
Provides endpoints for resume upload, JD analysis, pipeline execution (SSE),
and optimized resume download.
"""

import asyncio
import json
import os
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend/ is on the path regardless of where uvicorn is launched from
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import delete, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

# ── Agent & utility imports ──────────────────────────────────────────────────
from agents.jd_analyzer import analyze_jd
from utils import cache as result_cache
from config import MAX_ITERATIONS, SCORE_TARGET, BACKEND_URL, FRONTEND_URL, MODEL_SCORER, MAX_UPLOAD_BYTES, MAX_RESUME_CHARS, MAX_JD_CHARS
from agents.rewriter import rewrite_resume
from agents.humanizer import humanize_resume
from agents.scorer import score_combined
from agents.fact_extractor import extract_claims
from agents.fabrication_guard import fabrication_guard
from parsers.pdf_parser import parse_pdf
from parsers.docx_parser import parse_docx
from generators.docx_generator import generate_docx
from delta.writer import write_daily_usage, write_job_match
from scraper.scraper import scrape_jobs
from db.session import get_db, init_db, AsyncSessionLocal
from db.models import JobStatus, PipelineEvent, PipelineJob, Resume, User
from auth.router import router as auth_router
from auth.dependencies import decode_token, get_current_user, check_plan_limit
from dashboard.router import router as dashboard_router


# ── App setup ────────────────────────────────────────────────────────────────

_EVENT_TTL_HOURS = 24  # delete PipelineEvent rows older than this


async def _cleanup_events():
    """Periodically delete PipelineEvent rows older than EVENT_TTL_HOURS."""
    while True:
        await asyncio.sleep(3600)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_EVENT_TTL_HOURS)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(PipelineEvent).where(PipelineEvent.created_at < cutoff))
            await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    cleanup_task = asyncio.create_task(_cleanup_events())
    yield
    cleanup_task.cancel()


app = FastAPI(title="Resume Optimizer API", version="1.0.0", lifespan=lifespan)

_ALLOWED_ORIGINS = list({FRONTEND_URL, "http://localhost:5173", "http://localhost:5174"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(dashboard_router)

# ── Directory setup ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

# ── Request/response models ──────────────────────────────────────────────────

class AnalyzeJDRequest(BaseModel):
    jd_text: str


class RunPipelineRequest(BaseModel):
    job_id: str
    jd_text: str


class ScrapeJobsRequest(BaseModel):
    resume_id: str
    keywords: str
    per_source: int = 20


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
        result = await analyze_jd(request.jd_text[:MAX_JD_CHARS])
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

    user_id = decode_token(token)  # raises 401 if invalid

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

            await asyncio.sleep(0.5)

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

    if not resume.file_path or not Path(resume.file_path).exists():
        raise HTTPException(status_code=404, detail="Output file not found.")

    return FileResponse(
        path=resume.file_path,
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
    output_path = str(OUTPUTS_DIR / f"gen_{doc_id}.docx")

    try:
        await asyncio.to_thread(generate_docx, request.resume_text, output_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate document: {str(e)}")

    return FileResponse(
        path=output_path,
        filename="resume.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ── Job scraper endpoint ──────────────────────────────────────────────────────

@app.post("/scrape-jobs")
async def scrape_jobs_endpoint(
    request: ScrapeJobsRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Scrape job postings from all active sources using provided keywords.
    Persists results to Delta Lake and returns them.
    """
    if not request.keywords.strip():
        raise HTTPException(status_code=400, detail="keywords cannot be empty.")

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
                pass

    asyncio.create_task(_persist())

    return {
        "total":    len(postings),
        "keywords": request.keywords,
        "results":  postings,
    }


# ── Background pipeline task ─────────────────────────────────────────────────

async def _run_pipeline_task(job_id: str, user_id: str = ""):
    """
    Main optimization loop. Reads/writes state via Postgres; emits SSE events as
    PipelineEvent rows so any worker or reconnecting client can consume them.
    """
    job_uuid = uuid.UUID(job_id)

    async with AsyncSessionLocal() as db:

        async def emit(event: dict):
            evt = PipelineEvent(job_id=job_uuid, event_json=event)
            db.add(evt)
            await db.commit()

        async def update_job(**kwargs):
            kwargs["updated_at"] = datetime.now(timezone.utc)
            await db.execute(update(PipelineJob).where(PipelineJob.id == job_uuid).values(**kwargs))
            await db.commit()

        try:
            result_cache.clear()

            # Load job state from DB
            job_result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_uuid))
            job_row = job_result.scalar_one()
            resume_text: str = job_row.resume_text[:MAX_RESUME_CHARS]
            jd_text: str     = job_row.jd_text[:MAX_JD_CHARS]

            # Build claims ledger once from the original resume text.
            # Used by the rewriter (constrain invented facts) and the guard (verify output).
            ledger = await asyncio.to_thread(extract_claims, resume_text)

            # ── Step 1: Analyze JD ──────────────────────────────────────────
            await emit({"type": "stage", "message": "Analyzing Job Description...", "stage": "jd_analysis"})
            jd_result = await analyze_jd(jd_text)
            jd_keywords: list[str] = jd_result.get("keywords", [])
            await emit({
                "type": "stage",
                "message": f"JD analyzed — {len(jd_keywords)} keywords extracted.",
                "stage": "jd_analysis",
                "keywords": jd_keywords[:20],
            })

            current_resume = resume_text
            consolidated_feedback = None
            iteration = 0
            prev_average = 0

            # ── Initial score ───────────────────────────────────────────────
            await emit({"type": "stage", "message": "Scoring original resume...", "stage": "score"})
            initial_combined = await score_combined(current_resume, jd_text, jd_keywords)
            initial_avg = round(sum(initial_combined[k]["score"] for k in ("ats", "impact", "skills_gap", "readability")) / 4)
            await emit({
                "type": "average",
                "score": initial_avg,
                "iteration": 0,
                "scores": {k: initial_combined[k]["score"] for k in ("ats", "impact", "skills_gap", "readability")},
                "message": f"Original resume score: {initial_avg}",
            })

            if initial_avg >= SCORE_TARGET:
                await emit({
                    "type": "stage",
                    "message": f"Original resume already scores {initial_avg} — no optimization needed. Finalizing...",
                    "stage": "finalize",
                })

            scores = {
                "ats": initial_combined["ats"],
                "impact": initial_combined["impact"],
                "skills_gap": initial_combined["skills_gap"],
                "readability": initial_combined["readability"],
                "average": initial_avg,
            }

            while iteration < MAX_ITERATIONS and initial_avg < SCORE_TARGET:
                iteration += 1
                is_fast_iter = iteration > 1 and prev_average >= 75

                await emit({
                    "type": "iterate",
                    "message": (
                        f"Starting iteration {iteration} (fast mode — rewrite only)..."
                        if is_fast_iter else
                        f"Starting optimization iteration {iteration}..."
                    ),
                    "iteration": iteration,
                })

                # ── Step 2: Rewrite ─────────────────────────────────────────
                await emit({"type": "stage", "message": "Rewriting resume to align with JD...", "stage": "rewrite"})
                current_resume = await rewrite_resume(
                    resume_text=current_resume,
                    jd_keywords=jd_keywords,
                    consolidated_feedback=consolidated_feedback,
                    claims_ledger=ledger,
                )

                # ── Fabrication guard — verify the rewrite ──────────────────
                guard = await asyncio.to_thread(fabrication_guard, current_resume, ledger, resume_text)
                current_resume = guard.text
                if guard.stripped or guard.gaps:
                    await emit({
                        "type":    "guard",
                        "message": f"Fabrication guard: removed {len(guard.stripped)} unverified claim(s).",
                        "stripped": guard.stripped[:10],
                        "gaps":     guard.gaps[:5],
                    })

                await emit({"type": "stage", "message": "Resume rewrite complete.", "stage": "rewrite"})

                # ── Step 3: Humanize ────────────────────────────────────────
                if not is_fast_iter:
                    await emit({"type": "stage", "message": "Humanizing resume language...", "stage": "humanize"})
                    current_resume = await humanize_resume(current_resume)
                    await emit({"type": "stage", "message": "Humanization complete.", "stage": "humanize"})

                # ── Step 4: Score ───────────────────────────────────────────
                await emit({"type": "stage", "message": "Running all 4 scorers...", "stage": "score"})
                combined = await score_combined(current_resume, jd_text, jd_keywords)

                ats_result         = combined["ats"]
                impact_result      = combined["impact"]
                skills_result      = combined["skills_gap"]
                readability_result = combined["readability"]

                await emit({"type": "score", "platform": "ATS Match",
                            "score": ats_result["score"],
                            "feedback": ats_result.get("missing_keywords", [])[:3],
                            "matched": ats_result.get("matched_keywords", [])[:3]})
                await emit({"type": "score", "platform": "Impact Score",
                            "score": impact_result["score"],
                            "feedback": impact_result.get("suggestions", [])[:3],
                            "weak_bullets": impact_result.get("weak_bullets", [])[:3]})
                await emit({"type": "score", "platform": "Skills Gap",
                            "score": skills_result["score"],
                            "feedback": skills_result.get("missing_skills", [])[:3],
                            "matched": skills_result.get("matched_skills", [])[:3]})
                await emit({"type": "score", "platform": "Readability",
                            "score": readability_result["score"],
                            "feedback": readability_result.get("issues", [])[:3],
                            "strengths": readability_result.get("strengths", [])[:3]})

                average = round((
                    ats_result.get("score", 0) +
                    impact_result.get("score", 0) +
                    skills_result.get("score", 0) +
                    readability_result.get("score", 0)
                ) / 4)
                prev_average = average
                scores = {
                    "ats": ats_result, "impact": impact_result,
                    "skills_gap": skills_result, "readability": readability_result,
                    "average": average,
                }

                await emit({
                    "type": "average", "score": average, "iteration": iteration,
                    "scores": {
                        "ats": ats_result.get("score", 0),
                        "impact": impact_result.get("score", 0),
                        "skills_gap": skills_result.get("score", 0),
                        "readability": readability_result.get("score", 0),
                    },
                })

                if average >= SCORE_TARGET:
                    await emit({"type": "stage",
                                "message": f"Target score {SCORE_TARGET} reached (average: {average}). Finalizing...",
                                "stage": "finalize"})
                    break

                if iteration >= MAX_ITERATIONS:
                    await emit({"type": "stage",
                                "message": f"Maximum iterations ({MAX_ITERATIONS}) reached. Average score: {average}. Finalizing...",
                                "stage": "finalize"})
                    break

                consolidated_feedback = {
                    "ats": ats_result, "impact": impact_result,
                    "skills_gap": skills_result, "readability": readability_result,
                }
                await emit({"type": "stage",
                            "message": f"Score {average} < {SCORE_TARGET}. Consolidating feedback for iteration {iteration + 1}...",
                            "stage": "consolidate"})

            # ── Step 5: Generate .docx ──────────────────────────────────────
            await emit({"type": "stage", "message": "Generating optimized .docx file...", "stage": "generate"})
            output_path = str(OUTPUTS_DIR / f"{job_id}.docx")
            generate_docx(current_resume, output_path)

            # ── Persist Resume record ───────────────────────────────────────
            resume_record = None
            if user_id:
                try:
                    ver_q = await db.execute(
                        select(func.coalesce(func.max(Resume.version), 0) + 1)
                        .where(Resume.user_id == user_id)
                    )
                    next_version = ver_q.scalar() or 1

                    resume_record = Resume(
                        user_id=user_id,
                        original_filename=job_row.original_filename,
                        file_path=output_path,
                        jd_text=jd_text,
                        final_score=float(scores.get("average", 0)),
                        scores_json=scores,
                        iterations=iteration,
                        version=next_version,
                    )
                    db.add(resume_record)
                    await db.commit()
                    await db.refresh(resume_record)
                except Exception:
                    pass

            # ── Update PipelineJob ──────────────────────────────────────────
            await update_job(
                status=JobStatus.done,
                download_path=output_path,
                scores_json=scores,
                iteration=iteration,
            )

            # ── Write Delta usage ───────────────────────────────────────────
            if user_id:
                try:
                    await asyncio.to_thread(write_daily_usage, {
                        "user_id":       user_id,
                        "date":          date_type.today().isoformat(),
                        "pipeline_runs": 1,
                        "uploads":       1,
                        "tokens_used":   0,
                    })
                except Exception:
                    pass

            # download_url points to the persisted Resume so it's durable across restarts
            download_url = (
                f"/download/{resume_record.id}" if resume_record else f"/download/{job_id}"
            )
            await emit({
                "type": "done",
                "message": "Resume optimization complete! Your optimized resume is ready.",
                "download_url": download_url,
                "final_score": scores.get("average", 0),
                "iterations": iteration,
            })

        except Exception as e:
            await update_job(status=JobStatus.error, error_message=str(e))
            await emit({"type": "error", "message": f"Pipeline error: {str(e)}"})
