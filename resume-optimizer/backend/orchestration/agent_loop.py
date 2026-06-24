"""
A+C (Act + Critique) agent loop driver for Phase 2 resume optimization.

Architecture:
  Phase 1 → scores, jd_keywords, claims_ledger
      │
  ┌─ REFLECTION LOOP (max AGENT_MAX_REFLECTIONS) ◄──────────────────────┐
  │   ┌─ TOOL-CALLING LOOP (max AGENT_MAX_ITER, budget-gated) ────────┐  │
  │   │  complete_with_tools(msgs, MODEL_OPTIMIZER, TOOL_DEFS)         │  │
  │   │  → model returns tool_calls (structured, validated args)        │  │
  │   │  no tool_calls? → break (model said it's done)                  │  │
  │   │  else: dispatch tools → mutate ResumeState → append obs         │  │
  │   └────────────────────────────────────────────────────────────────┘  │
  │   REFLECTION: re-score + fabrication_guard on reassembled draft        │
  │   target met AND no guard flags? → DONE                                │
  │   else: feed deltas + flagged claims back as message ──────────────────┘
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from agents.fabrication_guard import fabrication_guard
from agents.fact_extractor import ClaimsLedger
from agents.scorer import score_combined
from agents.tools import (
    ResumeState,
    bullet_strengthen,
    bullets_reorder,
    critique_resume,
    keyword_inject,
    skills_rewrite,
)
from config import AGENT_MAX_ITER, AGENT_TOKEN_BUDGET, MODEL_OPTIMIZER, SCORE_DIMENSIONS, SCORE_TARGET
from llm import complete_with_tools
from observability.trace import set_call_kind

_logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

AGENT_MAX_REFLECTIONS = 3  # max reflection iterations (outer loop)
_SCORE_TARGET = SCORE_TARGET  # from config

# ── Tool definitions (JSON schema for LiteLLM tool-calling) ──────────────────

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "keyword_inject",
            "description": "Inject missing ATS keywords into resume sections. Call when ATS score is below target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "missing_keywords_csv": {
                        "type": "string",
                        "description": "Comma-separated keywords to inject",
                    },
                    "target_sections_csv": {
                        "type": "string",
                        "description": "Sections to inject into. Default: experience,summary",
                    },
                },
                "required": ["missing_keywords_csv"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bullet_strengthen",
            "description": "Strengthen weak impact bullets in the experience section. Call when Impact score is below target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weak_bullets_csv": {
                        "type": "string",
                        "description": "Comma-separated weak bullet texts verbatim from the Impact score",
                    },
                },
                "required": ["weak_bullets_csv"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skills_rewrite",
            "description": "Rewrite the skills section to include missing required skills. Call when Skills Gap score is below target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "missing_skills_csv": {
                        "type": "string",
                        "description": "Comma-separated skills from Skills Gap score's missing_skills",
                    },
                },
                "required": ["missing_skills_csv"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bullets_reorder",
            "description": "Reorder bullets in an experience section so the most JD-relevant bullets appear first. Call when JD Tailoring score is below target due to bullet ordering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_name": {
                        "type": "string",
                        "description": "Section to reorder: experience, summary, or skills",
                    },
                    "jd_focus_csv": {
                        "type": "string",
                        "description": "Comma-separated JD keywords to prioritize when reordering",
                    },
                },
                "required": ["section_name", "jd_focus_csv"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "critique_resume",
            "description": "Run a critic over the full resume draft to get qualitative feedback on what still reads weak, robotic, or generic. Returns structured issues (robotic phrases, weak bullets, keyword stuffing, tone issues, structural issues). Call this to understand what needs fixing before deciding which tools to use.",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus_areas_csv": {
                        "type": "string",
                        "description": "Optional comma-separated areas to focus on (e.g. 'robotic language,weak bullets'). Leave empty for full critique.",
                    },
                },
                "required": [],
            },
        },
    },
]

# ── Tool dispatch table ───────────────────────────────────────────────────────

TOOL_MAP: dict[str, Callable] = {
    "keyword_inject":    keyword_inject,
    "bullet_strengthen": bullet_strengthen,
    "skills_rewrite":    skills_rewrite,
    "bullets_reorder":   bullets_reorder,
    "critique_resume":   critique_resume,
}


# ── System prompt builder ─────────────────────────────────────────────────────


def _build_system_stable(jd_keywords: list, available_sections: list,
                         user_instruction: Optional[str] = None) -> str:
    """Stable system prompt — stays identical across reflections/rounds so the
    provider's context cache can hit on it."""
    instruction_block = ""
    if user_instruction:
        instruction_block = (
            "PRIORITY USER FEEDBACK: The user reviewed their resume and is not happy. "
            f"They asked you to fix the following: {user_instruction}\n"
            "Address ONLY what was flagged using the available tools. Do not re-run a full "
            "optimization or change sections the user did not mention.\n\n"
        )

    return f"""{instruction_block}You are a Resume Optimization Strategist. Your job is to raise all resume scores above {_SCORE_TARGET} using the available tools.

AVAILABLE RESUME SECTIONS: {', '.join(available_sections)}
JD KEYWORDS (context only): {', '.join(jd_keywords[:20])}

Call tools only for dimensions marked NEEDS WORK. When all needed tools have been called, output a brief summary and stop calling tools."""


def _build_scores_context(scores: dict) -> str:
    """Volatile scores block — injected as a user message so the system prompt
    stays cacheable across reflections.

    Readability is intentionally omitted — a dedicated humanize stage runs
    after the agent loop and handles language polish, so the optimizer should
    not waste tool calls trying to fix readability.
    """
    ats    = scores.get("ats", {})
    impact = scores.get("impact", {})
    skills = scores.get("skills_gap", {})
    tailor = scores.get("jd_tailoring", {})

    def _s(d: dict) -> int:
        return d.get("score", 0)

    def _flag(d: dict) -> str:
        return "NEEDS WORK" if _s(d) < _SCORE_TARGET else "ok"

    return f"""CURRENT SCORES:
  ATS Match:    {_s(ats):>3}  [{_flag(ats)}]
    missing_keywords: {', '.join(ats.get('missing_keywords', [])[:15])}
  Impact:       {_s(impact):>3}  [{_flag(impact)}]
    weak_bullets: {', '.join(impact.get('weak_bullets', [])[:8])}
  Skills Gap:   {_s(skills):>3}  [{_flag(skills)}]
    missing_skills: {', '.join(skills.get('missing_skills', [])[:15])}
  JD Tailoring: {_s(tailor):>3}  [{_flag(tailor)}]
    issues: {', '.join(tailor.get('issues', [])[:3])}

Analyze the scores above. Call tools for dimensions marked NEEDS WORK."""


def _build_system(scores: dict, jd_keywords: list, available_sections: list,
                  user_instruction: Optional[str] = None) -> str:
    """Full system prompt (backward-compat wrapper)."""
    return (_build_system_stable(jd_keywords, available_sections, user_instruction)
            + "\n\n" + _build_scores_context(scores))


# ── Main entry point ──────────────────────────────────────────────────────────


async def run_agent(
    state: ResumeState,
    scores: dict,
    jd_text: str,
    jd_keywords: list,
    ledger: ClaimsLedger,
    original_resume: str,
    seniority_level: str = "mid",
    required_hard_skills: Optional[list] = None,
    user_instruction: Optional[str] = None,
    max_reflections: Optional[int] = None,
    on_event: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    Run the A+C agent loop.

    Returns:
        dict with keys:
          - text (str): final optimized resume text
          - input_tokens (int): cumulative input tokens across all calls
          - output_tokens (int): cumulative output tokens across all calls
          - cost_usd (float): cumulative cost
          - iterations (int): number of complete_with_tools calls made
    """
    # Tag all LlmCallLog rows from this driver as "phase2_optimizer"
    set_call_kind("phase2_optimizer")

    reflections_cap = max_reflections or AGENT_MAX_REFLECTIONS

    _SCORES_IDX = 1
    messages: list[dict] = [
        {"role": "system",
         "content": _build_system_stable(jd_keywords, state.available_sections(), user_instruction)},
        {"role": "user",
         "content": _build_scores_context(scores)},
    ]

    current_scores = scores
    last_scored_draft = original_resume  # baseline `scores` were computed on this text
    iterations = 0
    # Guard result is initialised so we always have something to reference
    # even if the loop exits early (e.g. budget exceeded before first reflection).
    guard = type("_Guard", (), {"gaps": [], "text": state.reassemble()})()

    for reflection_idx in range(reflections_cap):

        # ── Inner tool-calling loop ───────────────────────────────────────────
        for _ in range(AGENT_MAX_ITER):
            if state.total_tokens() >= AGENT_TOKEN_BUDGET:
                _logger.info(
                    "agent_loop: token budget reached (%d/%d), stopping inner loop",
                    state.total_tokens(), AGENT_TOKEN_BUDGET,
                )
                break

            result = await complete_with_tools(messages, MODEL_OPTIMIZER, TOOL_DEFS, cache_system=True)
            state.add_tokens(
                result["input_tokens"],
                result["output_tokens"],
                result.get("cost_usd", 0.0),
            )
            iterations += 1

            msg = result["message"]

            # Append the raw assistant message object; LiteLLM accepts it directly
            # so tool_call IDs stay consistent for the tool role messages below.
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": msg.tool_calls or None,
            })

            if not msg.tool_calls:
                _logger.debug("agent_loop: model returned no tool_calls — inner loop done")
                break

            # Dispatch each tool call and collect observations
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                if tool_name not in TOOL_MAP:
                    obs = f"Unknown tool: {tool_name}"
                    _logger.warning("agent_loop: model called unknown tool %r", tool_name)
                else:
                    try:
                        kwargs = json.loads(tc.function.arguments)
                        obs = await TOOL_MAP[tool_name](state, **kwargs)
                    except Exception as exc:
                        obs = f"Tool error: {exc}"
                        _logger.warning("agent_loop: tool %r raised %s", tool_name, exc)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": obs,
                })

                if on_event:
                    on_event({
                        "type": "agent_step",
                        "message": f"Tool {tool_name}: {obs[:100]}",
                        "stage": "agent",
                        "tokens_used": state.total_tokens(),
                        "budget": AGENT_TOKEN_BUDGET,
                    })

        # ── Reflection ────────────────────────────────────────────────────────
        draft = state.reassemble()
        guard = fabrication_guard(draft, ledger, original_resume)

        # Re-score the current draft — skip the LLM call when the inner loop changed
        # nothing (draft identical to what we last scored), reusing current_scores.
        if draft != last_scored_draft:
            try:
                score_result = await score_combined(
                    draft, jd_text, jd_keywords,
                    seniority_level=seniority_level,
                    required_hard_skills=required_hard_skills,
                )
                rescored = score_result.get("text", {})
                if rescored:
                    current_scores = rescored
                last_scored_draft = draft
                score_tokens = score_result.get("tokens", {})
                state.add_tokens(score_tokens.get("input_tokens", 0), score_tokens.get("output_tokens", 0), score_result.get("cost_usd", 0.0))
            except Exception as exc:
                _logger.warning("Re-score failed (%s) — using prior scores for reflection", exc)

        overall = current_scores.get("overall", 0)
        all_above = all(
            current_scores.get(d, {}).get("score", 0) >= _SCORE_TARGET
            for d in SCORE_DIMENSIONS
        )

        _logger.info(
            "agent_loop reflection %d/%d: overall=%s all_above=%s guard_gaps=%d",
            reflection_idx + 1, reflections_cap, overall, all_above, len(guard.gaps),
        )

        if all_above and not guard.gaps:
            break  # target met, no fabrication flags — done

        if reflection_idx < reflections_cap - 1:
            # Feed reflection back as a user message so the model can continue
            feedback_parts: list[str] = []
            if not all_above:
                feedback_parts.append(
                    f"Scores after your changes: overall={overall}. "
                    f"Still below target on some dimensions."
                )
            if guard.gaps:
                feedback_parts.append(
                    f"Fabrication guard flagged: {'; '.join(guard.gaps[:5])}"
                )

            messages.append({
                "role": "user",
                "content": "\n".join(feedback_parts) + "\nPlease continue optimizing.",
            })

            # Refresh scores context (system prompt stays stable → cache hits)
            messages[_SCORES_IDX] = {
                "role": "user",
                "content": _build_scores_context(current_scores),
            }

    # Prefer guard's cleaned text when fabrications were detected
    final_text = guard.text if guard.gaps else state.reassemble()

    return {
        "text":          final_text,
        "input_tokens":  state.input_tokens,
        "output_tokens": state.output_tokens,
        "cost_usd":      state.cost_usd,
        "iterations":    iterations,
        "flagged":       list(guard.gaps),
    }
