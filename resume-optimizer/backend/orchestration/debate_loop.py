"""
Two-agent debate driver for the Pro tier.

Architecture:
  DEBATE LOOP (max DEBATE_MAX_ROUNDS):
    OPTIMIZER: inner tool-calling loop (same TOOL_DEFS/TOOL_MAP as agent_loop)
    REVIEWER:  single complete() call — returns "No objections." or "OBJECTION: <issue>"
    exit when no objections OR rounds exhausted OR budget hit
  GUARD: fabrication_guard on final draft
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional

from agents.fabrication_guard import fabrication_guard
from agents.fact_extractor import ClaimsLedger
from agents.scorer import score_combined
from agents.tools import ResumeState
from config import AGENT_MAX_ITER, DEBATE_TOKEN_BUDGET, MODEL_OPTIMIZER, MODEL_REVIEWER
from llm import complete, complete_with_tools
from observability.trace import set_call_kind
from orchestration.agent_loop import TOOL_DEFS, TOOL_MAP, _build_system_stable, _build_scores_context

_logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEBATE_MAX_ROUNDS = 2  # max debate rounds — always bounded


# ── Main entry point ──────────────────────────────────────────────────────────


async def run_debate(
    state: ResumeState,
    scores: dict,
    jd_text: str,
    jd_keywords: list,
    ledger: ClaimsLedger,
    original_resume: str,
    on_event: Optional[Callable[[dict], None]] = None,
    **kwargs,
) -> dict:
    """
    Run the two-agent debate loop (Pro tier).

    The Optimizer agent revises the resume using tool calls; the Reviewer
    agent critiques it in a single pass. Rounds continue until the Reviewer
    raises no new objections or DEBATE_MAX_ROUNDS is exhausted.

    `**kwargs` accepts seniority_level and required_hard_skills, used by the
    between-round re-score so the optimizer sees fresh scores each round.

    Returns:
        dict with keys:
          - text (str): final optimized resume text
          - input_tokens (int): cumulative input tokens across all calls
          - output_tokens (int): cumulative output tokens across all calls
          - cost_usd (float): cumulative cost
          - iterations (int): number of complete_with_tools calls made
    """
    # Tag all LlmCallLog rows from this driver as "pro_debate"
    set_call_kind("pro_debate")

    # Stable system prompt — shared across rounds so the provider cache hits.
    stable_system = _build_system_stable(jd_keywords, state.available_sections())

    current_scores = scores
    iterations = 0
    last_objection: str | None = None
    # Guard result initialised so we always have something to reference
    # even if the loop exits early (e.g. budget exceeded before first round).
    guard = type("_Guard", (), {"gaps": [], "text": state.reassemble()})()

    for round_idx in range(DEBATE_MAX_ROUNDS):
        _logger.info("debate_loop: starting round %d/%d", round_idx + 1, DEBATE_MAX_ROUNDS)

        # Budget gate — skip round entirely if already exhausted
        if state.total_tokens() >= DEBATE_TOKEN_BUDGET:
            _logger.info(
                "debate_loop: budget exhausted (%d/%d) before round %d — stopping",
                state.total_tokens(), DEBATE_TOKEN_BUDGET, round_idx + 1,
            )
            break

        # ── Optimizer inner tool-calling loop ──────────────────────────────
        messages: list[dict] = [
            {"role": "system", "content": stable_system},
            {"role": "user", "content": _build_scores_context(current_scores)},
        ]

        # Feed reviewer objection from previous round as user context (round > 0)
        if round_idx > 0 and last_objection:
            messages.append({
                "role": "user",
                "content": (
                    f"The reviewer raised this objection: {last_objection}\n\n"
                    "Address ONLY this objection. Call at most 1-2 tools that directly "
                    "target the issue raised. Do NOT re-run a full optimization. Pick the "
                    "tool that matches the objection (keyword_inject for missing keywords, "
                    "bullet_strengthen for weak bullets, skills_rewrite for missing skills, "
                    "bullets_reorder for ordering). When the targeted fix is applied, stop."
                ),
            })

        round_tool_calls = 0
        for _ in range(AGENT_MAX_ITER):
            if state.total_tokens() >= DEBATE_TOKEN_BUDGET:
                _logger.info(
                    "debate_loop: token budget reached (%d/%d), stopping optimizer",
                    state.total_tokens(), DEBATE_TOKEN_BUDGET,
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

            # Preserve reasoning_content when present — DeepSeek V4 thinking models
            # require the prior turn's reasoning echoed back or the next turn errors
            # (litellm #26395). Harmless no-op for models that don't emit it.
            assistant_msg = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": msg.tool_calls or None,
            }
            _rc = getattr(msg, "reasoning_content", None)
            if _rc:
                assistant_msg["reasoning_content"] = _rc
            messages.append(assistant_msg)

            if not msg.tool_calls:
                _logger.debug("debate_loop: optimizer returned no tool_calls — inner loop done")
                break

            round_tool_calls += len(msg.tool_calls)

            # Dispatch each tool call and collect observations
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                if tool_name not in TOOL_MAP:
                    obs = f"Unknown tool: {tool_name}"
                    _logger.warning("debate_loop: model called unknown tool %r", tool_name)
                else:
                    try:
                        tool_args = json.loads(tc.function.arguments)
                        obs = await TOOL_MAP[tool_name](state, **tool_args)
                    except Exception as exc:
                        obs = f"Tool error: {exc}"
                        _logger.warning("debate_loop: tool %r raised %s", tool_name, exc)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": obs,
                })

                if on_event:
                    on_event({
                        "type": "agent_step",
                        "message": f"[Debate round {round_idx + 1}] Tool {tool_name}: {obs[:100]}",
                        "stage": "debate",
                        "tokens_used": state.total_tokens(),
                        "budget": DEBATE_TOKEN_BUDGET,
                        "round": round_idx + 1,
                    })

        # If the optimizer couldn't make any tool calls this round (budget hit
        # or model chose not to), skip the reviewer — no point critiquing a
        # draft that wasn't changed.
        if round_tool_calls == 0:
            _logger.info("debate_loop: optimizer made 0 tool calls in round %d — skipping reviewer", round_idx + 1)
            break

        # ── Re-score the draft so round N+1 (and the reviewer) see fresh scores ──
        draft = state.reassemble()
        try:
            _rescore = await score_combined(
                draft, jd_text, jd_keywords,
                seniority_level=kwargs.get("seniority_level", "mid"),
                required_hard_skills=kwargs.get("required_hard_skills"),
            )
            if _rescore.get("text"):
                current_scores = _rescore["text"]
            _st = _rescore.get("tokens", {})
            state.add_tokens(_st.get("input_tokens", 0), _st.get("output_tokens", 0), _rescore.get("cost_usd", 0.0))
        except Exception as exc:
            _logger.warning("debate_loop: re-score failed (%s) — keeping prior scores", exc)

        # ── Reviewer single-pass critique ──────────────────────────────────
        overall = current_scores.get("overall", 0)

        reviewer_prompt = (
            "You are a skeptical resume reviewer. The optimizer just revised this resume "
            "and can run more tools to address objections.\n\n"
            f"CURRENT RESUME DRAFT:\n{draft}\n\n"
            f"SCORES: overall={overall}\n\n"
            "The optimizer can only fix issues with these tools:\n"
            "  - keyword_inject: add missing ATS keywords\n"
            "  - bullet_strengthen: rewrite weak bullets with stronger verbs/metrics\n"
            "  - skills_rewrite: add missing skills to the skills section\n"
            "  - bullets_reorder: reorder bullets by JD relevance\n\n"
            "Raise ONE objection that is fixable by these tools. Do NOT raise objections about:\n"
            "  - tone, density, robotic language, metric inflation, wording — a dedicated humanize "
            "stage runs after the debate completes and handles all language polish\n"
            "  - employment gaps, timeline, dates, missing certifications, lack of specific projects, "
            "or anything requiring new factual information — the optimizer cannot fabricate facts\n\n"
            "If you have no more fixable objections, respond EXACTLY: No objections.\n"
            "Otherwise respond EXACTLY: OBJECTION: <one fixable issue, 20 words or less>"
        )

        try:
            reviewer_result = await complete(reviewer_prompt, MODEL_REVIEWER)
        except Exception as exc:
            _logger.warning("debate_loop: reviewer LLM call failed (%s) — treating as no objection", exc)
            break

        state.add_tokens(
            reviewer_result.get("input_tokens", 0),
            reviewer_result.get("output_tokens", 0),
            reviewer_result.get("cost_usd", 0.0),
        )

        reviewer_text = reviewer_result.get("text", "").strip()
        _logger.info(
            "debate_loop round %d/%d reviewer said: %r",
            round_idx + 1, DEBATE_MAX_ROUNDS, reviewer_text[:80],
        )

        if on_event:
            on_event({
                "type": "debate_review",
                "message": f"[Reviewer round {round_idx + 1}]: {reviewer_text[:120]}",
                "stage": "debate",
                "round": round_idx + 1,
            })

        # Termination check: reviewer satisfied?
        if reviewer_text.lower().startswith("no objections"):
            _logger.info("debate_loop: reviewer satisfied after round %d — exiting", round_idx + 1)
            break

        # Store objection to feed back next round
        last_objection = reviewer_text

        # If this is the last round, don't iterate further
        if round_idx >= DEBATE_MAX_ROUNDS - 1:
            _logger.info(
                "debate_loop: max rounds (%d) exhausted — exiting with last draft",
                DEBATE_MAX_ROUNDS,
            )

    # ── Fabrication guard on final draft ──────────────────────────────────────
    final_draft = state.reassemble()
    # CPU-bound (spaCy NER + difflib) — offload so concurrent requests aren't stalled.
    guard = await asyncio.to_thread(fabrication_guard, final_draft, ledger, original_resume)

    # Prefer guard's cleaned text when fabrications were detected
    final_text = guard.text if guard.gaps else final_draft

    return {
        "text":          final_text,
        "input_tokens":  state.input_tokens,
        "output_tokens": state.output_tokens,
        "cost_usd":      state.cost_usd,
        "iterations":    iterations,
    }
