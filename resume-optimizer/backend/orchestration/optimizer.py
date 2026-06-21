"""
Phase 2 — agentic optimizer entry point.

run_optimization_async() is the single function called from main.py.

Key design decisions:
  - on_event passed through to run_agent so step events fire in real time
  - No event_list buffer — events go directly to SSE callback
  - Token tracking lives in ResumeState, not step_callback
  - Insufficient sections detected before session registration (fail fast)
  - Fallback triggered by exception OR by all tools returning without any section update
"""

import logging
from typing import Callable, Optional

from agents.fact_extractor import ClaimsLedger
from agents.tools import ResumeState
from agents.rewriter import rewrite_resume
from agents.verifier import verify_final_draft
import config
from config import SCORE_TARGET
from orchestration.agent_loop import run_agent
from orchestration.debate_loop import run_debate
from utils.section_parser import detect_sections

_logger = logging.getLogger(__name__)

# Retained for the score-threshold contract checked by tests; the A+C agent loop
# itself now targets SCORE_TARGET directly via agent_loop._SCORE_TARGET.
_WORK_THRESHOLD = max(75, SCORE_TARGET - 10)


async def run_optimization_async(
    job_id: str,
    resume_text: str,
    jd_text: str,
    jd_keywords: list,
    claims_ledger: ClaimsLedger,
    scores: dict,
    seniority_level: str = "mid",
    required_hard_skills: Optional[list] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    plan: str = "standard",
) -> dict:
    """
    Phase 2 async entry point. Called from _run_pipeline_task in main.py.

    Args:
        job_id:        PipelineJob UUID string — used for logging/trace correlation.
        resume_text:   Current resume entering Phase 2 (trimmed to MAX_RESUME_CHARS).
        jd_text:       Full JD text — used by the reflection loop scorer.
        jd_keywords:   From Phase 1 analyze_jd().
        claims_ledger: From Phase 1 extract_claims().
        scores:        Baseline score dict from Phase 1 score_combined().
        on_event:      SSE event callback.
        plan:          User's subscription plan — "standard" (default) or "pro".
                       "pro" activates the debate loop when PRO_DEBATE_ENABLED=True.

    Returns:
        {"text", "input_tokens", "output_tokens", "cost_usd", "iterations", "fallback"}
    """
    if on_event:
        on_event({"type": "stage", "message": "Parsing resume sections...", "stage": "agent"})

    # ── Detect sections ───────────────────────────────────────────────────────
    sections = detect_sections(resume_text)
    meaningful = {k: v for k, v in sections.items() if k != "header" and v.strip()}

    if not meaningful:
        _logger.warning(
            "job=%s: no named sections detected (%s). Using deterministic fallback.",
            job_id, list(sections.keys()),
        )
        if on_event:
            on_event({
                "type":    "stage",
                "message": "Resume has no detectable named sections — using full rewrite.",
                "stage":   "agent",
            })
        pipeline_result = await _deterministic_fallback(resume_text, jd_keywords, claims_ledger, scores)
        return await _with_verifier(pipeline_result, claims_ledger)

    available_metrics = ", ".join(sorted(claims_ledger.metrics)[:15]) if claims_ledger.metrics else ""
    state = ResumeState(sections=sections, available_metrics=available_metrics)

    if on_event:
        on_event({
            "type":    "agent_step",
            "message": f"Resume split into {len(sections)} section(s): {', '.join(sections.keys())}.",
            "stage":   "agent",
        })

    # ── Select driver based on plan and feature flag ──────────────────────────
    use_debate = plan in ("pro", "enterprise") and config.PRO_DEBATE_ENABLED
    driver = run_debate if use_debate else run_agent

    _logger.info(
        "job=%s: plan=%r PRO_DEBATE_ENABLED=%r → driver=%s",
        job_id, plan, config.PRO_DEBATE_ENABLED, driver.__name__,
    )

    # ── Run selected driver ───────────────────────────────────────────────────
    try:
        result = await driver(
            state=state,
            scores=scores,
            jd_text=jd_text,
            jd_keywords=jd_keywords,
            ledger=claims_ledger,
            original_resume=resume_text,
            seniority_level=seniority_level,
            required_hard_skills=required_hard_skills,
            on_event=on_event,
        )
    except Exception as exc:
        _logger.warning("job=%s: agent failed (%s). Using deterministic fallback.", job_id, exc)
        if on_event:
            on_event({"type": "stage", "message": "Agent error — using deterministic rewrite.", "stage": "agent"})
        pipeline_result = await _deterministic_fallback(resume_text, jd_keywords, claims_ledger, scores)
        return await _with_verifier(pipeline_result, claims_ledger)

    # ── Extract result ────────────────────────────────────────────────────────
    optimized  = result.get("text", resume_text)
    input_tok  = result.get("input_tokens", 0)
    output_tok = result.get("output_tokens", 0)
    cost_usd   = result.get("cost_usd", 0.0)
    iterations = result.get("iterations", 1)

    # Guard: if nothing changed, all tools silently failed — fall back
    if optimized.strip() == resume_text.strip():
        _logger.warning(
            "job=%s: agent completed but resume is unchanged. Using deterministic fallback.",
            job_id,
        )
        if on_event:
            on_event({"type": "stage", "message": "No changes from agent — using deterministic rewrite.", "stage": "agent"})
        pipeline_result = await _deterministic_fallback(resume_text, jd_keywords, claims_ledger, scores)
        return await _with_verifier(pipeline_result, claims_ledger)

    pipeline_result = {
        "text":          optimized,
        "input_tokens":  input_tok,
        "output_tokens": output_tok,
        "cost_usd":      cost_usd,
        "iterations":    iterations,
        "fallback":      False,
    }
    return await _with_verifier(pipeline_result, claims_ledger)


async def _with_verifier(pipeline_result: dict, ledger: ClaimsLedger) -> dict:
    """Run the LLM verifier on the final draft and attach verifier_flagged to the result dict."""
    draft = pipeline_result.get("text", "")
    vr = await verify_final_draft(draft, ledger)
    return {
        **pipeline_result,
        "input_tokens":  pipeline_result.get("input_tokens",  0) + vr.input_tokens,
        "output_tokens": pipeline_result.get("output_tokens", 0) + vr.output_tokens,
        "cost_usd":      pipeline_result.get("cost_usd",     0.0) + vr.cost_usd,
        "verifier_flagged": vr.flagged,
    }


async def _deterministic_fallback(
    resume_text: str,
    jd_keywords: list,
    claims_ledger: ClaimsLedger,
    scores: dict,
) -> dict:
    """Single full rewrite used when the agent cannot run or produces no change."""
    result = await rewrite_resume(
        resume_text=resume_text,
        jd_keywords=jd_keywords,
        consolidated_feedback=scores,
        claims_ledger=claims_ledger,
    )
    return {
        "text":          result.get("text", resume_text),
        "input_tokens":  result.get("tokens", {}).get("input_tokens",  0),
        "output_tokens": result.get("tokens", {}).get("output_tokens", 0),
        "cost_usd":      result.get("cost_usd", 0.0),
        "iterations":    1,
        "fallback":      True,
    }
