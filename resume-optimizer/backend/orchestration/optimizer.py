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
from agents.tools import ResumeState, split_evidenced
from agents.rewriter import rewrite_resume
import config
from orchestration.agent_loop import run_agent
from orchestration.debate_loop import run_debate
from utils.section_parser import detect_sections

_logger = logging.getLogger(__name__)


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
        {"text", "input_tokens", "output_tokens", "cost_usd", "iterations", "fallback", "honest_gaps"}
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
        return pipeline_result

    available_metrics = ", ".join(sorted(claims_ledger.metrics)[:15]) if claims_ledger.metrics else ""
    state = ResumeState(sections=sections, available_metrics=available_metrics, capabilities=claims_ledger.capabilities)

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

    if on_event:
        if use_debate:
            on_event({
                "type":    "stage",
                "message": f"Pro debate mode active — running {driver.__name__} (plan={plan}, PRO_DEBATE_ENABLED={config.PRO_DEBATE_ENABLED})",
                "stage":   "agent",
            })
        else:
            on_event({
                "type":    "stage",
                "message": f"Standard mode — running {driver.__name__} (plan={plan}, PRO_DEBATE_ENABLED={config.PRO_DEBATE_ENABLED})",
                "stage":   "agent",
            })

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
        return pipeline_result

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
        return pipeline_result

    pipeline_result = {
        "text":          optimized,
        "input_tokens":  input_tok,
        "output_tokens": output_tok,
        "cost_usd":      cost_usd,
        "iterations":    iterations,
        "fallback":      False,
        "honest_gaps":   result.get("honest_gaps", []),
    }
    return pipeline_result


def _format_scores_feedback(scores: dict, capabilities: frozenset = frozenset()) -> tuple:
    """Turn the raw scores dict into a human-readable feedback block for the rewriter.

    Without this, ``f"{scores}"`` dumps the Python repr (``{'ats': {...}}``) into the
    prompt — far less useful than a list of concrete weaknesses.

    Filters keyword/skill asks through the capabilities evidence allowlist so this
    second feedback channel doesn't undo the keyword filtering in rewrite_resume's
    own jd_keywords path. Returns (feedback_text, gaps).
    """
    if not isinstance(scores, dict):
        return str(scores), []

    lines: list[str] = []
    gaps: list[str] = []
    ats = scores.get("ats", {}) or {}
    if ats.get("missing_keywords"):
        evidenced, kw_gaps = split_evidenced(ats["missing_keywords"][:10], capabilities)
        gaps.extend(kw_gaps)
        if evidenced:
            lines.append(f"- Add missing ATS keywords: {', '.join(evidenced)}")
    impact = scores.get("impact", {}) or {}
    if impact.get("weak_bullets"):
        lines.append("- Strengthen weak bullets: " + "; ".join(impact["weak_bullets"][:5]))
    skills = scores.get("skills_gap", {}) or {}
    crit = skills.get("critical_missing") or skills.get("missing_skills") or []
    if crit:
        evidenced, sk_gaps = split_evidenced(crit[:10], capabilities)
        gaps.extend(sk_gaps)
        if evidenced:
            lines.append(f"- Add missing required skills: {', '.join(evidenced)}")
    tailor = scores.get("jd_tailoring", {}) or {}
    if tailor.get("issues"):
        lines.append("- Fix tailoring issues: " + "; ".join(tailor["issues"][:3]))

    return ("\n".join(lines) if lines else ""), gaps


async def _deterministic_fallback(
    resume_text: str,
    jd_keywords: list,
    claims_ledger: ClaimsLedger,
    scores: dict,
) -> dict:
    """Single full rewrite used when the agent cannot run or produces no change."""
    feedback_text, feedback_gaps = _format_scores_feedback(scores, claims_ledger.capabilities)
    result = await rewrite_resume(
        resume_text=resume_text,
        jd_keywords=jd_keywords,
        consolidated_feedback=feedback_text,
        claims_ledger=claims_ledger,
    )
    return {
        "text":          result.get("text", resume_text),
        "input_tokens":  result.get("tokens", {}).get("input_tokens",  0),
        "output_tokens": result.get("tokens", {}).get("output_tokens", 0),
        "cost_usd":      result.get("cost_usd", 0.0),
        "iterations":    1,
        "fallback":      True,
        "honest_gaps":   sorted(set(result.get("gaps", [])) | set(feedback_gaps)),
    }
