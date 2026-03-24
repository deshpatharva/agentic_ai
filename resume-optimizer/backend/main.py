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
from pathlib import Path

# Ensure backend/ is on the path regardless of where uvicorn is launched from
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# ── Agent & utility imports ──────────────────────────────────────────────────
from agents.jd_analyzer import analyze_jd
from utils import cache as result_cache
from config import MAX_ITERATIONS, SCORE_TARGET, BACKEND_URL, FRONTEND_URL
from agents.rewriter import rewrite_resume
from agents.humanizer import humanize_resume
from agents.scorer import score_ats, score_combined, score_impact, score_skills_gap, score_readability
from parsers.pdf_parser import parse_pdf
from parsers.docx_parser import parse_docx
from generators.docx_generator import generate_docx

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="Resume Optimizer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
async def run_pipeline(request: RunPipelineRequest, background_tasks: BackgroundTasks):
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

    background_tasks.add_task(_run_pipeline_task, request.job_id)

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


# ── Background pipeline task ─────────────────────────────────────────────────

async def _run_pipeline_task(job_id: str):
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

        current_resume = resume_text
        consolidated_feedback = None
        iteration = 0
        prev_average = 0

        while iteration < MAX_ITERATIONS:
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

            # ── Step 4: Score ───────────────────────────────────────────────
            await emit({"type": "stage", "message": "Running ATS Keyword Scorer...", "stage": "score"})
            ats_result = score_ats(current_resume, jd_text, jd_keywords)
            await emit({
                "type": "score",
                "platform": "ATS Match",
                "score": ats_result["score"],
                "feedback": ats_result.get("missing_keywords", [])[:8],
                "matched": ats_result.get("matched_keywords", [])[:8],
            })

            # Single Gemini Flash-8B call returns all 3 scores at once
            await emit({"type": "stage", "message": "Running Impact / Skills / Readability scorers...", "stage": "score"})
            combined = await score_combined(current_resume, jd_text)

            impact_result = combined["impact"]
            skills_result = combined["skills_gap"]
            readability_result = combined["readability"]

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
        # Send sentinel to close SSE stream
        await queue.put(None)
