"""
Phase 2 — agentic optimizer entry point.

run_optimization_async() is the single function called from main.py.

Key design decisions:
  - on_event passed through to _run_crew_sync so step_callback fires in real time
  - No event_list buffer — events go directly to SSE via asyncio.run_coroutine_threadsafe
  - Token tracking lives in ResumeState, not step_callback
  - Insufficient sections detected before session registration (fail fast)
  - Fallback triggered by exception OR by all tools returning without any section update
"""

import asyncio
import logging
from typing import Callable, Optional

from crewai import Crew, Process, Task

from agents.fact_extractor import ClaimsLedger
from agents.optimizer_agent import (
    ResumeState,
    cleanup_session,
    create_optimizer_agent,
    register_session,
)
from agents.rewriter import rewrite_resume
from config import AGENT_TOKEN_BUDGET, SCORE_TARGET
from utils.section_parser import detect_sections

_logger = logging.getLogger(__name__)


def _build_task_description(
    session_key: str,
    jd_keywords: list,
    scores: dict,
    available_sections: list,
) -> str:
    """
    Structured task the agent reads to make tool decisions.
    session_key is embedded here — the agent copies it into every tool call.
    Resume text is NEVER included — it lives in shared state only.
    """
    ats    = scores.get("ats",         {})
    impact = scores.get("impact",      {})
    skills = scores.get("skills_gap",  {})
    read   = scores.get("readability", {})

    def _s(d):    return d.get("score", 0)
    def _flag(d): return "NEEDS WORK" if _s(d) < 75 else "ok — skip"

    return f"""Optimize the resume stored under session key: {session_key}

Pass this session_key exactly as written as the first argument to every tool call.
Do NOT pass any resume text to tools. They load from session state automatically.

SCORES (call tools only for dimensions marked NEEDS WORK):
  ATS Match:   {_s(ats):>3}  [{_flag(ats)}]
    missing_keywords_csv = "{', '.join(ats.get('missing_keywords', [])[:8])}"
    target_sections_csv  = "experience,summary"

  Impact:      {_s(impact):>3}  [{_flag(impact)}]
    weak_bullets_csv = "{', '.join(impact.get('weak_bullets', [])[:4])}"

  Skills Gap:  {_s(skills):>3}  [{_flag(skills)}]
    missing_skills_csv = "{', '.join(skills.get('missing_skills', [])[:8])}"

  Readability: {_s(read):>3}  [{_flag(read)}]
    section_name = "summary"
    issues_csv   = "{', '.join(read.get('issues', [])[:4])}"

AVAILABLE SECTIONS IN STATE: {', '.join(available_sections)}
JD KEYWORDS (context only, do not pass to tools): {', '.join(jd_keywords[:20])}

INSTRUCTIONS:
1. For each dimension marked NEEDS WORK, call the corresponding tool once
2. Copy the parameter values shown above exactly as written
3. After calling all needed tools, output only the session_key to signal completion"""


def _run_crew_sync(
    session_key: str,
    jd_keywords: list,
    scores: dict,
    state: ResumeState,
    on_event: Optional[Callable] = None,
) -> None:
    """
    Blocking crew execution — runs inside asyncio.to_thread().

    on_event is called directly from step_callback for real-time SSE.
    In main.py, on_event is defined as:
        lambda event: asyncio.run_coroutine_threadsafe(emit(event), loop)
    which is thread-safe and delivers events to SSE immediately.

    Token accounting is in ResumeState — read after kickoff() returns.
    """
    def _step_callback(step_output):
        total = state.total_tokens()
        event = {
            "type":        "agent_step",
            "message":     f"Agent step — {total:,} of {AGENT_TOKEN_BUDGET:,} tokens used.",
            "stage":       "agent",
            "tokens_used": total,
            "budget":      AGENT_TOKEN_BUDGET,
        }
        if on_event:
            on_event(event)

    agent = create_optimizer_agent()
    task  = Task(
        description=_build_task_description(
            session_key=session_key,
            jd_keywords=jd_keywords,
            scores=scores,
            available_sections=state.available_sections(),
        ),
        expected_output=(
            f"The session key '{session_key}' confirming all needed tools were called. "
            f"No resume text in the output."
        ),
        agent=agent,
    )
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
        memory=False,
        step_callback=_step_callback,
    )
    crew.kickoff()


async def run_optimization_async(
    job_id: str,
    resume_text: str,
    jd_keywords: list,
    claims_ledger: ClaimsLedger,
    scores: dict,
    on_event: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    Phase 2 async entry point. Called from _run_pipeline_task in main.py.

    Args:
        job_id:        PipelineJob UUID string — used as the session key.
        resume_text:   Current resume entering Phase 2 (trimmed to MAX_RESUME_CHARS).
        jd_keywords:   From Phase 1 analyze_jd().
        claims_ledger: From Phase 1 extract_claims().
        scores:        Baseline score dict from Phase 1 score_combined().
        on_event:      SSE event callback. In main.py this uses
                       asyncio.run_coroutine_threadsafe for thread safety.

    Returns:
        {"text", "input_tokens", "output_tokens", "iterations", "fallback"}
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
        return await _deterministic_fallback(resume_text, jd_keywords, claims_ledger, scores)

    available_metrics = ", ".join(sorted(claims_ledger.metrics)[:15]) if claims_ledger.metrics else ""
    state = ResumeState(sections=sections, available_metrics=available_metrics)
    register_session(job_id, state)

    if on_event:
        on_event({
            "type":    "agent_step",
            "message": f"Resume split into {len(sections)} section(s): {', '.join(sections.keys())}.",
            "stage":   "agent",
        })

    # ── Run crew in thread ────────────────────────────────────────────────────
    try:
        await asyncio.to_thread(
            _run_crew_sync,
            job_id,
            jd_keywords,
            scores,
            state,
            on_event,
        )
    except Exception as exc:
        _logger.warning("job=%s: agent failed (%s). Using deterministic fallback.", job_id, exc)
        cleanup_session(job_id)
        if on_event:
            on_event({"type": "stage", "message": "Agent error — using deterministic rewrite.", "stage": "agent"})
        return await _deterministic_fallback(resume_text, jd_keywords, claims_ledger, scores)

    # ── Extract result ────────────────────────────────────────────────────────
    optimized  = state.reassemble()
    input_tok  = state.input_tokens
    output_tok = state.output_tokens
    cleanup_session(job_id)

    # Guard: if nothing changed, all tools silently failed — fall back
    if optimized.strip() == resume_text.strip():
        _logger.warning(
            "job=%s: agent completed but resume is unchanged. Using deterministic fallback.",
            job_id,
        )
        if on_event:
            on_event({"type": "stage", "message": "No changes from agent — using deterministic rewrite.", "stage": "agent"})
        return await _deterministic_fallback(resume_text, jd_keywords, claims_ledger, scores)

    return {
        "text":          optimized,
        "input_tokens":  input_tok,
        "output_tokens": output_tok,
        "iterations":    1,
        "fallback":      False,
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
        "iterations":    1,
        "fallback":      True,
    }
