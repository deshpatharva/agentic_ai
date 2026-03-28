"""
Resume Optimizer — FastAPI Backend
Provides endpoints for resume upload, JD analysis, pipeline execution (SSE),
and optimized resume download.
"""

import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import date as date_type
from pathlib import Path

# Ensure backend/ is on the path regardless of where uvicorn is launched from
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

# ── Agent & utility imports ──────────────────────────────────────────────────
from agents.jd_analyzer import analyze_jd
from utils import cache as result_cache
from config import MAX_ITERATIONS, SCORE_TARGET, BACKEND_URL, FRONTEND_URL, MODEL_SCORER
from agents.rewriter import rewrite_resume
from agents.humanizer import humanize_resume
from agents.scorer import score_combined
from parsers.pdf_parser import parse_pdf
from parsers.docx_parser import parse_docx
from generators.docx_generator import generate_docx
from llm import create_gemini_cache, delete_gemini_cache
from delta.writer import (
    write_daily_usage,
    write_job_match,
    read_usage_last_n_days,
    read_job_matches,
)
from scraper.scraper import scrape_jobs
from db.session import get_db, init_db, AsyncSessionLocal
from db.models import Resume
from auth.router import router as auth_router
from auth.dependencies import get_current_user, check_plan_limit
from dashboard.router import router as dashboard_router


# ── App setup ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Resume Optimizer API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(dashboard_router)

# ── Directory setup ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# ── In-memory job store ──────────────────────────────────────────────────────
jobs: dict[str, dict] = {}

# ── Request/response models ──────────────────────────────────────────────────

class AnalyzeJDRequest(BaseModel):
    jd_text: str


class RunPipelineRequest(BaseModel):
    job_id: str
    jd_text: str
    user_id: str = ""  # populated from auth token in authenticated flow


class ScrapeJobsRequest(BaseModel):
    user_id: str
    resume_id: str
    keywords: str
    per_source: int = 20


# ── Helper ───────────────────────────────────────────────────────────────────

def _new_job(resume_text: str = "", jd_text: str = "") -> dict:
    return {
        "status": "pending",
        "resume_text": resume_text,
        "jd_text": jd_text,
        "jd_keywords": [],
        "current_resume": resume_text,
        "scores": {},
        "iteration": 0,
        "queue": asyncio.Queue(),
        "download_path": None,
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    """
    Accept a .pdf or .docx resume file, parse it, and return structured text.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=400, detail="Only .pdf and .docx files are supported."
        )

    job_id = str(uuid.uuid4())
    save_path = UPLOADS_DIR / f"{job_id}{ext}"

    contents = await file.read()
    await asyncio.to_thread(save_path.write_bytes, contents)

    # Run sync parsers in a thread so they don't block the event loop
    try:
        parser = parse_pdf if ext == ".pdf" else parse_docx
        parsed = await asyncio.wait_for(
            asyncio.to_thread(parser, str(save_path)),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Resume parsing timed out. Try a simpler PDF or convert to .docx.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {str(e)}")

    # Create job entry
    jobs[job_id] = _new_job(resume_text=parsed["raw_text"])
    jobs[job_id]["original_filename"] = file.filename

    return {
        "job_id": job_id,
        "text": parsed["raw_text"],
        "structure": parsed["sections"],
    }


@app.post("/analyze-jd")
async def analyze_jd_endpoint(request: AnalyzeJDRequest):
    """
    Analyze a job description and return extracted keywords, requirements, and skills.
    """
    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text cannot be empty.")

    try:
        result = await analyze_jd(request.jd_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"JD analysis failed: {str(e)}")

    return result


@app.post("/run-pipeline")
async def run_pipeline(request: RunPipelineRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Start the optimization pipeline for a previously uploaded resume.
    Returns immediately; progress is streamed via SSE at /status/{job_id}.
    """
    if request.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found. Upload a resume first.")

    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text cannot be empty.")

    job = jobs[request.job_id]
    job["jd_text"] = request.jd_text
    job["status"] = "running"
    # Reset queue in case of re-run
    job["queue"] = asyncio.Queue()

    background_tasks.add_task(_run_pipeline_task, request.job_id, request.user_id, db)

    return {"job_id": request.job_id, "status": "started"}


@app.get("/status/{job_id}")
async def stream_status(job_id: str):
    """
    SSE endpoint — streams pipeline progress events to the client.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    queue: asyncio.Queue = jobs[job_id]["queue"]

    async def event_generator():
        while True:
            data = await queue.get()
            if data is None:
                # Sentinel — pipeline finished
                break
            yield {"data": data}

    return EventSourceResponse(event_generator())


@app.get("/download/{job_id}")
async def download_resume(job_id: str):
    """
    Download the generated .docx resume for a completed job.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    job = jobs[job_id]
    if job["status"] != "done" or not job["download_path"]:
        raise HTTPException(
            status_code=400,
            detail="Resume not ready yet. Wait for pipeline to complete.",
        )

    output_path = job["download_path"]
    if not Path(output_path).exists():
        raise HTTPException(status_code=404, detail="Output file not found.")

    return FileResponse(
        path=output_path,
        filename=f"optimized_resume_{job_id[:8]}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ── Dashboard & analytics endpoints ──────────────────────────────────────────

@app.get("/dashboard/usage/{user_id}")
async def dashboard_usage(user_id: str, days: int = 30):
    """
    Return aggregated daily usage for user_id over the last N days (from Delta Lake).
    """
    try:
        df = await asyncio.to_thread(read_usage_last_n_days, user_id, days)
        return {"user_id": user_id, "days": days, "rows": df.to_dict(orient="records")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read usage: {str(e)}")


@app.get("/dashboard/job-matches/{user_id}")
async def dashboard_job_matches(
    user_id: str,
    days: int = 30,
    page: int = 1,
    per_page: int = 20,
):
    """
    Return paginated job matches for user_id scraped in the last N days (from Delta Lake).
    """
    try:
        result = await asyncio.to_thread(read_job_matches, user_id, days, page, per_page)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read job matches: {str(e)}")


# ── Job scraper endpoint ──────────────────────────────────────────────────────

@app.post("/scrape-jobs")
async def scrape_jobs_endpoint(request: ScrapeJobsRequest):
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

    # Persist each posting to Delta Lake in a background thread
    async def _persist():
        for posting in postings:
            record = {
                "user_id":   request.user_id,
                "resume_id": request.resume_id,
                **posting,
            }
            try:
                await asyncio.to_thread(write_job_match, record)
            except Exception:
                pass  # Best-effort — don't fail the request if Delta write fails

    asyncio.create_task(_persist())

    return {
        "total":    len(postings),
        "keywords": request.keywords,
        "results":  postings,
    }


# ── Background pipeline task ─────────────────────────────────────────────────

async def _run_pipeline_task(job_id: str, user_id: str = "", db: AsyncSession = None):
    """
    Main optimization loop:
    1. Analyze JD
    2. Rewrite resume (with optional consolidated feedback)
    3. Humanize resume
    4. Run all 4 scorers
    5. If average < 90 and iterations < 5, loop back to step 2
    6. Generate .docx output
    """
    job = jobs[job_id]
    queue: asyncio.Queue = job["queue"]

    async def emit(event: dict):
        await queue.put(json.dumps(event))

    jd_cache_name = None
    task_db = AsyncSessionLocal() if user_id else None
    try:
        result_cache.clear()  # Fresh cache per pipeline run
        resume_text: str = job["resume_text"]
        jd_text: str = job["jd_text"]
        # loaded from config.py

        # ── Step 1: Analyze JD ──────────────────────────────────────────────
        await emit({"type": "stage", "message": "Analyzing Job Description...", "stage": "jd_analysis"})
        jd_result = await analyze_jd(jd_text)
        jd_keywords: list[str] = jd_result.get("keywords", [])
        job["jd_keywords"] = jd_keywords
        await emit({
            "type": "stage",
            "message": f"JD analyzed — {len(jd_keywords)} keywords extracted.",
            "stage": "jd_analysis",
            "keywords": jd_keywords[:20],
        })

        # ── Create Gemini context cache for JD (reused across all iterations) ──
        try:
            jd_cache_name = await create_gemini_cache(jd_text, MODEL_SCORER)
        except Exception:
            jd_cache_name = None  # Cache creation is optional — fall back gracefully

        current_resume = resume_text
        consolidated_feedback = None
        iteration = 0
        prev_average = 0

        # ── Initial score of original resume before any rewriting ───────────
        await emit({"type": "stage", "message": "Scoring original resume...", "stage": "score"})
        initial_combined = await score_combined(current_resume, jd_text, jd_keywords, gemini_cache_name=jd_cache_name)
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
            job["scores"] = {
                "ats": initial_combined["ats"],
                "impact": initial_combined["impact"],
                "skills_gap": initial_combined["skills_gap"],
                "readability": initial_combined["readability"],
                "average": initial_avg,
            }

        while iteration < MAX_ITERATIONS and initial_avg < SCORE_TARGET:
            iteration += 1
            job["iteration"] = iteration
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

            # ── Step 2: Rewrite ─────────────────────────────────────────────
            await emit({"type": "stage", "message": "Rewriting resume to align with JD...", "stage": "rewrite"})
            current_resume = await rewrite_resume(
                resume_text=current_resume,
                jd_keywords=jd_keywords,
                consolidated_feedback=consolidated_feedback,
            )
            job["current_resume"] = current_resume
            await emit({"type": "stage", "message": "Resume rewrite complete.", "stage": "rewrite"})

            # ── Step 3: Humanize (skipped in fast iterations) ───────────────
            if not is_fast_iter:
                await emit({"type": "stage", "message": "Humanizing resume language...", "stage": "humanize"})
                current_resume = await humanize_resume(current_resume)
                job["current_resume"] = current_resume
                await emit({"type": "stage", "message": "Humanization complete.", "stage": "humanize"})

            # ── Step 4: Score (all 4 in one LLM call) ──────────────────────
            await emit({"type": "stage", "message": "Running all 4 scorers...", "stage": "score"})
            combined = await score_combined(current_resume, jd_text, jd_keywords, gemini_cache_name=jd_cache_name)

            ats_result         = combined["ats"]
            impact_result      = combined["impact"]
            skills_result      = combined["skills_gap"]
            readability_result = combined["readability"]

            await emit({
                "type": "score", "platform": "ATS Match",
                "score": ats_result["score"],
                "feedback": ats_result.get("missing_keywords", [])[:3],
                "matched": ats_result.get("matched_keywords", [])[:3],
            })
            await emit({
                "type": "score", "platform": "Impact Score",
                "score": impact_result["score"],
                "feedback": impact_result.get("suggestions", [])[:3],
                "weak_bullets": impact_result.get("weak_bullets", [])[:3],
            })
            await emit({
                "type": "score", "platform": "Skills Gap",
                "score": skills_result["score"],
                "feedback": skills_result.get("missing_skills", [])[:3],
                "matched": skills_result.get("matched_skills", [])[:3],
            })
            await emit({
                "type": "score", "platform": "Readability",
                "score": readability_result["score"],
                "feedback": readability_result.get("issues", [])[:3],
                "strengths": readability_result.get("strengths", [])[:3],
            })

            # ── Compute average ─────────────────────────────────────────────
            average = round((
                ats_result.get("score", 0) +
                impact_result.get("score", 0) +
                skills_result.get("score", 0) +
                readability_result.get("score", 0)
            ) / 4)
            prev_average = average
            job["scores"] = {
                "ats": ats_result,
                "impact": impact_result,
                "skills_gap": skills_result,
                "readability": readability_result,
                "average": average,
            }

            await emit({
                "type": "average",
                "score": average,
                "iteration": iteration,
                "scores": {
                    "ats": ats_result.get("score", 0),
                    "impact": impact_result.get("score", 0),
                    "skills_gap": skills_result.get("score", 0),
                    "readability": readability_result.get("score", 0),
                },
            })

            # ── Check threshold ─────────────────────────────────────────────
            if average >= SCORE_TARGET:
                await emit({
                    "type": "stage",
                    "message": f"Target score {SCORE_TARGET} reached (average: {average}). Finalizing...",
                    "stage": "finalize",
                })
                break

            if iteration >= MAX_ITERATIONS:
                await emit({
                    "type": "stage",
                    "message": f"Maximum iterations ({MAX_ITERATIONS}) reached. Average score: {average}. Finalizing...",
                    "stage": "finalize",
                })
                break

            # ── Consolidate feedback for next iteration ──────────────────────
            consolidated_feedback = {
                "ats": ats_result,
                "impact": impact_result,
                "skills_gap": skills_result,
                "readability": readability_result,
            }
            await emit({
                "type": "stage",
                "message": f"Score {average} < {SCORE_TARGET}. Consolidating feedback for iteration {iteration + 1}...",
                "stage": "consolidate",
            })

        # ── Step 5: Generate .docx ──────────────────────────────────────────
        await emit({"type": "stage", "message": "Generating optimized .docx file...", "stage": "generate"})
        output_path = str(OUTPUTS_DIR / f"{job_id}.docx")
        generate_docx(current_resume, output_path)
        job["download_path"] = output_path
        job["status"] = "done"

        # ── Persist resume record to PostgreSQL ─────────────────────────────
        if user_id and task_db:
            try:
                # Get next version number for this user
                ver_q = await task_db.execute(
                    select(func.coalesce(func.max(Resume.version), 0) + 1)
                    .where(Resume.user_id == user_id)
                )
                next_version = ver_q.scalar() or 1

                resume_record = Resume(
                    user_id=user_id,
                    original_filename=jobs[job_id].get("original_filename", "resume"),
                    file_path=output_path,
                    jd_text=jd_text,
                    final_score=float(job["scores"].get("average", 0)),
                    scores_json=job["scores"],
                    iterations=iteration,
                    version=next_version,
                )
                task_db.add(resume_record)
                await task_db.commit()
            except Exception:
                pass  # Don't fail the pipeline if DB write fails

        # ── Write daily usage to Delta Lake ─────────────────────────────────
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
                pass  # Don't fail the pipeline if Delta write fails

        await emit({
            "type": "done",
            "message": "Resume optimization complete! Your optimized resume is ready.",
            "download_url": f"/download/{job_id}",
            "final_score": job["scores"].get("average", 0),
            "iterations": iteration,
        })

    except Exception as e:
        job["status"] = "error"
        await emit({"type": "error", "message": f"Pipeline error: {str(e)}"})

    finally:
        # Best-effort cleanup of Gemini context cache
        if jd_cache_name:
            await delete_gemini_cache(jd_cache_name)
        # Close task-local DB session
        if task_db:
            await task_db.close()
        # Send sentinel to close SSE stream
        await queue.put(None)
