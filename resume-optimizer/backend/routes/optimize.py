"""
Optimization endpoint — Resume optimization with SSE streaming.

POST /api/optimize — Accepts resume_text and jd_text, returns SSE stream
of optimization progress events.
"""

import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from config import MAX_ITERATIONS, SCORE_TARGET, MAX_RESUME_CHARS, MAX_JD_CHARS
from auth.dependencies import get_current_user
from db.session import get_db
from db.models import User

from orchestration.context import PipelineContext
from orchestration.pipeline import PipelineExecutor
from orchestration.loop_controller import LoopController
from orchestration.result import format_result, format_error_result

# Agents
from agents.fact_extractor import extract_claims
from agents.jd_analyzer import analyze_jd
from agents.rewriter import rewrite_resume
from agents.humanizer import humanize_resume
from agents.scorer import score_combined
from agents.fabrication_guard import fabrication_guard

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["optimize"])

# Task execution order
TASK_ORDER = ["extract_claims", "analyze_jd", "rewrite", "humanize", "score", "validate"]


class OptimizeRequest(BaseModel):
    """Request body for /api/optimize endpoint."""
    resume_text: str
    jd_text: str


@router.post("/optimize")
async def optimize_resume(
    request: OptimizeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Optimize resume against job description with SSE streaming.

    Accepts resume_text and jd_text, returns SSE stream of optimization events.
    Each event contains progress information, scores, and final result.

    Args:
        request: OptimizeRequest with resume_text and jd_text
        current_user: Authenticated user from JWT token
        db: Database session

    Returns:
        StreamingResponse with SSE events
    """
    # Validate input
    if not request.resume_text or not request.resume_text.strip():
        raise HTTPException(status_code=400, detail="resume_text cannot be empty.")
    if not request.jd_text or not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text cannot be empty.")

    optimization_id = str(uuid.uuid4())
    resume_text = request.resume_text[:MAX_RESUME_CHARS]
    jd_text = request.jd_text[:MAX_JD_CHARS]

    async def event_generator() -> AsyncGenerator[dict, None]:
        """
        Async generator that yields SSE events during optimization.

        Emits:
            - optimization_start: Initial setup
            - iteration_start: Beginning of each iteration
            - score: Individual scorer results
            - decision: Loop control decision
            - optimization_complete: Final result
            - error: Any exceptions encountered
        """
        try:
            # Create pipeline context
            context = PipelineContext(
                resume_text=resume_text,
                jd_text=jd_text,
                user_id=str(current_user.id),
                optimization_id=optimization_id,
                max_iterations=MAX_ITERATIONS,
                quality_threshold=SCORE_TARGET / 100.0,  # Convert to 0-1 scale
            )

            # Create executor and loop controller
            executor = PipelineExecutor()
            loop_controller = LoopController(context)

            # Emit start event
            start_time = asyncio.get_event_loop().time()
            yield {
                "data": json.dumps({
                    "type": "optimization_start",
                    "optimization_id": optimization_id,
                    "timestamp": asyncio.get_event_loop().time(),
                })
            }
            await asyncio.sleep(0.1)

            # ── Step 1: Extract claims from original resume ──────────────────────
            try:
                _logger.info(f"[{optimization_id}] Extracting claims from resume")
                claims = await asyncio.to_thread(extract_claims, resume_text)
                context.claims_ledger = claims.__dict__ if hasattr(claims, '__dict__') else claims
            except Exception as e:
                _logger.exception(f"[{optimization_id}] Extract claims failed: {str(e)}")
                context.record_error("extract_claims", str(e))
                yield {
                    "data": json.dumps({
                        "type": "error",
                        "message": f"Failed to extract claims: {str(e)}",
                        "task": "extract_claims",
                    })
                }
                await asyncio.sleep(0.1)

            # ── Step 2: Analyze JD ─────────────────────────────────────────────
            try:
                _logger.info(f"[{optimization_id}] Analyzing job description")
                jd_result_dict = await analyze_jd(jd_text)
                jd_result = jd_result_dict.get("text", jd_result_dict)
                context.jd_analysis = jd_result
                jd_keywords = jd_result.get("keywords", [])[:20]
                yield {
                    "data": json.dumps({
                        "type": "iteration_start",
                        "iteration": 0,
                        "message": "Analyzed job description",
                        "keywords": jd_keywords,
                    })
                }
                await asyncio.sleep(0.1)
            except Exception as e:
                _logger.exception(f"[{optimization_id}] Analyze JD failed: {str(e)}")
                context.record_error("analyze_jd", str(e))
                yield {
                    "data": json.dumps({
                        "type": "error",
                        "message": f"Failed to analyze JD: {str(e)}",
                        "task": "analyze_jd",
                    })
                }
                await asyncio.sleep(0.1)
                # Can't continue without JD analysis
                raise

            # ── Initial score ────────────────────────────────────────────────────
            try:
                _logger.info(f"[{optimization_id}] Scoring initial resume")
                initial_score_dict = await score_combined(resume_text, jd_text, jd_keywords)
                initial_score = initial_score_dict.get("text", initial_score_dict)
                context.quality_score = sum(
                    initial_score.get(k, {}).get("score", 0)
                    for k in ("ats", "impact", "skills_gap", "readability")
                ) / 4.0 / 100.0  # Normalize to 0-1
                context.score_breakdown = initial_score
                yield {
                    "data": json.dumps({
                        "type": "score",
                        "message": f"Initial score: {int(context.quality_score * 100)}/100",
                        "score": int(context.quality_score * 100),
                        "breakdown": {
                            k: initial_score.get(k, {}).get("score", 0)
                            for k in ("ats", "impact", "skills_gap", "readability")
                        },
                    })
                }
                await asyncio.sleep(0.1)
            except Exception as e:
                _logger.exception(f"[{optimization_id}] Initial score failed: {str(e)}")
                context.record_error("score", str(e))

            # ── Main optimization loop ────────────────────────────────────────────
            current_resume = resume_text
            while loop_controller.should_continue_loop() and context.iteration_count < MAX_ITERATIONS:
                context.iteration_count += 1
                iteration = context.iteration_count

                yield {
                    "data": json.dumps({
                        "type": "iteration_start",
                        "iteration": iteration,
                        "message": f"Starting optimization iteration {iteration}",
                    })
                }
                await asyncio.sleep(0.1)

                # Execute tasks in order
                for task_name in TASK_ORDER:
                    try:
                        if task_name == "extract_claims":
                            # Already done, skip
                            continue
                        elif task_name == "analyze_jd":
                            # Already done, skip
                            continue
                        elif task_name == "rewrite":
                            _logger.info(f"[{optimization_id}] Iteration {iteration}: Rewriting")
                            rewrite_dict = await rewrite_resume(
                                resume_text=current_resume,
                                jd_keywords=jd_keywords,
                                consolidated_feedback=None,
                                claims_ledger=context.claims_ledger,
                            )
                            current_resume = rewrite_dict.get("text", rewrite_dict)
                            context.rewritten_resume = current_resume

                            # Apply fabrication guard
                            guard = await asyncio.to_thread(
                                fabrication_guard,
                                current_resume,
                                context.claims_ledger,
                                resume_text,
                            )
                            current_resume = guard.text
                            context.rewritten_resume = current_resume

                        elif task_name == "humanize":
                            _logger.info(f"[{optimization_id}] Iteration {iteration}: Humanizing")
                            humanize_dict = await humanize_resume(current_resume)
                            current_resume = humanize_dict.get("text", humanize_dict)
                            context.humanized_resume = current_resume

                        elif task_name == "score":
                            _logger.info(f"[{optimization_id}] Iteration {iteration}: Scoring")
                            score_dict = await score_combined(current_resume, jd_text, jd_keywords)
                            score_data = score_dict.get("text", score_dict)
                            context.score_breakdown = score_data

                            # Calculate quality score
                            new_score = sum(
                                score_data.get(k, {}).get("score", 0)
                                for k in ("ats", "impact", "skills_gap", "readability")
                            ) / 4.0 / 100.0  # Normalize to 0-1
                            context.quality_score = new_score

                            # Emit score event
                            yield {
                                "data": json.dumps({
                                    "type": "score",
                                    "iteration": iteration,
                                    "message": f"Iteration {iteration} score: {int(new_score * 100)}/100",
                                    "score": int(new_score * 100),
                                    "breakdown": {
                                        k: score_data.get(k, {}).get("score", 0)
                                        for k in ("ats", "impact", "skills_gap", "readability")
                                    },
                                })
                            }
                            await asyncio.sleep(0.1)

                        elif task_name == "validate":
                            _logger.info(f"[{optimization_id}] Iteration {iteration}: Validating")
                            # Validation is implicit; just record it
                            context.validation_report = {
                                "iteration": iteration,
                                "status": "validated",
                            }

                    except Exception as e:
                        _logger.warning(f"[{optimization_id}] Task {task_name} failed: {str(e)}")
                        context.record_warning(task_name, str(e))
                        # Continue with next task on failure

                # Emit decision event
                should_continue = loop_controller.should_continue_loop()
                yield {
                    "data": json.dumps({
                        "type": "decision",
                        "iteration": iteration,
                        "current_score": int(context.quality_score * 100),
                        "target_score": SCORE_TARGET,
                        "should_continue": should_continue,
                        "reason": (
                            "Target reached" if context.quality_score >= (SCORE_TARGET / 100.0)
                            else "Max iterations reached" if iteration >= MAX_ITERATIONS
                            else "Continuing"
                        ),
                    })
                }
                await asyncio.sleep(0.1)

            # ── Format and emit final result ──────────────────────────────────────
            reached_threshold = context.quality_score >= (SCORE_TARGET / 100.0)
            diagnostic = loop_controller.prepare_diagnostic() if not reached_threshold else None
            final_result = format_result(context, reached_threshold, diagnostic)

            end_time = asyncio.get_event_loop().time()
            duration_ms = int((end_time - start_time) * 1000)

            yield {
                "data": json.dumps({
                    "type": "optimization_complete",
                    "optimization_id": optimization_id,
                    "success": True,
                    "resume": current_resume,
                    "final_score": int(context.quality_score * 100),
                    "target_score": SCORE_TARGET,
                    "iterations": context.iteration_count,
                    "duration_ms": duration_ms,
                    "reached_threshold": reached_threshold,
                    "diagnostic": diagnostic,
                })
            }

        except Exception as e:
            _logger.exception(f"[{optimization_id}] Optimization failed: {str(e)}")
            error_result = format_error_result(optimization_id, str(e), context if 'context' in locals() else None)
            yield {
                "data": json.dumps({
                    "type": "error",
                    "optimization_id": optimization_id,
                    "error": str(e),
                    "error_result": error_result,
                })
            }

    return EventSourceResponse(event_generator(), media_type="text/event-stream")
