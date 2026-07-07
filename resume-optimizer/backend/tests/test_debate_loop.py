"""Tests for the two-agent debate loop driver (T4.2)."""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DELTA_STORAGE_PATH", "./test_delta_store")

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SCORES_BELOW_TARGET = {
    "ats":         {"score": 60, "missing_keywords": ["docker", "kubernetes"], "matched_keywords": []},
    "impact":      {"score": 90, "weak_bullets": [],     "strong_bullets": []},
    "skills_gap":  {"score": 90, "missing_skills": [],   "matched_skills": []},
    "readability": {"score": 90, "issues": [],           "worst_section": "experience"},
    "overall": 80,
}


def _make_state(sections=None):
    from agents.tools import ResumeState
    return ResumeState(sections=sections or {"experience": "Did work.", "skills": "Python"})


def _make_ledger():
    from agents.fact_extractor import ClaimsLedger
    return ClaimsLedger(companies=frozenset(), metrics=frozenset(), raw_bullets=tuple())


def _done_msg(content="Done optimizing."):
    """Return a fake assistant message with no tool_calls."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    return msg


def _tool_call_msg(tool_name="keyword_inject",
                   args='{"missing_keywords_csv": "docker"}'):
    """Return a fake assistant message with one tool_call."""
    tc = MagicMock()
    tc.function.name = tool_name
    tc.function.arguments = args
    tc.id = "tc_1"
    msg = MagicMock()
    msg.content = ""
    msg.tool_calls = [tc]
    return msg


def _fake_complete_with_tools_result(msg=None, in_tok=100, out_tok=50, cost=0.01):
    if msg is None:
        msg = _done_msg()
    return {"message": msg, "input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": cost}


_NOOP_TOOL_MAP = {
    name: AsyncMock(return_value="OK")
    for name in [
        "keyword_inject", "bullet_strengthen", "skills_rewrite",
        "bullets_reorder",
    ]
}


def _clean_guard(generated_text, ledger, source_text):
    """Fabrication guard stub that always returns clean (no gaps)."""
    from agents.fabrication_guard import GuardResult
    return GuardResult(text=generated_text, stripped=[], gaps=[])


async def _fake_score_combined(*args, **kwargs):
    """Between-round re-score stub — avoids a real LLM call in unit tests."""
    return {"text": SCORES_BELOW_TARGET, "tokens": {"input_tokens": 20, "output_tokens": 10}, "cost_usd": 0.001}


# ---------------------------------------------------------------------------
# Test 1: debate loop is bounded by rounds
# ---------------------------------------------------------------------------


async def test_debate_loop_bounded_rounds():
    """Reviewer objects in round 1; round 2 is the final round (DEBATE_MAX_ROUNDS=2),
    so the optimizer addresses the objection but the reviewer is not called again --
    a discarded final-round objection is never worth the extra call (spec 5b).
    Result must have 'text', 'input_tokens', 'output_tokens', 'cost_usd', 'iterations'."""
    from orchestration import debate_loop

    state = _make_state()
    ledger = _make_ledger()

    # Optimizer: tool call on first call per round, done on second
    cwt_idx = [0]

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        cwt_idx[0] += 1
        if cwt_idx[0] % 2 == 1:
            return _fake_complete_with_tools_result(_tool_call_msg())
        return _fake_complete_with_tools_result(_done_msg())

    # complete (reviewer): objects when called -- only fires once since round 2
    # is the final round and skips the reviewer entirely.
    reviewer_call_count = [0]

    async def fake_complete(prompt, model, **kwargs):
        reviewer_call_count[0] += 1
        if reviewer_call_count[0] == 1:
            return {"text": "OBJECTION: bullets are weak", "input_tokens": 30, "output_tokens": 10, "cost_usd": 0.001}
        return {"text": "No objections.", "input_tokens": 30, "output_tokens": 5, "cost_usd": 0.0005}

    with patch.object(debate_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(debate_loop, "TOOL_MAP", _NOOP_TOOL_MAP), \
         patch.object(debate_loop, "score_combined", side_effect=_fake_score_combined), \
         patch.object(debate_loop, "complete", side_effect=fake_complete), \
         patch.object(debate_loop, "fabrication_guard", side_effect=_clean_guard):
        result = await debate_loop.run_debate(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=["docker"],
            ledger=ledger,
            original_resume="Did work.",
        )

    assert "text" in result
    assert "input_tokens" in result
    assert "output_tokens" in result
    assert "cost_usd" in result
    assert "iterations" in result
    assert result["text"]
    assert reviewer_call_count[0] == 1  # round 2 is the final round; reviewer skipped


# ---------------------------------------------------------------------------
# Test 2: reviewer objection triggers optimizer revision
# ---------------------------------------------------------------------------


async def test_reviewer_objection_triggers_revision():
    """When reviewer objects in round 1, optimizer's inner loop runs again in round 2."""
    from orchestration import debate_loop

    state = _make_state()
    ledger = _make_ledger()

    optimizer_call_count = [0]

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        optimizer_call_count[0] += 1
        if optimizer_call_count[0] % 2 == 1:
            return _fake_complete_with_tools_result(_tool_call_msg())
        return _fake_complete_with_tools_result(_done_msg())

    reviewer_call_count = [0]

    async def fake_complete(prompt, model, **kwargs):
        reviewer_call_count[0] += 1
        if reviewer_call_count[0] == 1:
            return {"text": "OBJECTION: ATS score too low", "input_tokens": 30, "output_tokens": 10, "cost_usd": 0.001}
        return {"text": "No objections.", "input_tokens": 30, "output_tokens": 5, "cost_usd": 0.0005}

    with patch.object(debate_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(debate_loop, "TOOL_MAP", _NOOP_TOOL_MAP), \
         patch.object(debate_loop, "score_combined", side_effect=_fake_score_combined), \
         patch.object(debate_loop, "complete", side_effect=fake_complete), \
         patch.object(debate_loop, "fabrication_guard", side_effect=_clean_guard):
        await debate_loop.run_debate(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=["docker"],
            ledger=ledger,
            original_resume="Did work.",
        )

    # Optimizer ran in both rounds (2 tool-call + 2 done = 4 calls)
    assert optimizer_call_count[0] >= 2, (
        f"Expected optimizer inner loop to run in multiple rounds, got {optimizer_call_count[0]}"
    )


# ---------------------------------------------------------------------------
# Test 3: no objection on round 1 terminates early
# ---------------------------------------------------------------------------


async def test_debate_loop_no_objection_terminates_early():
    """When reviewer says 'No objections.' immediately, loop exits after 1 round."""
    from orchestration import debate_loop

    state = _make_state()
    ledger = _make_ledger()

    cwt_idx = [0]

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        cwt_idx[0] += 1
        if cwt_idx[0] % 2 == 1:
            return _fake_complete_with_tools_result(_tool_call_msg())
        return _fake_complete_with_tools_result(_done_msg())

    reviewer_call_count = [0]

    async def fake_complete(prompt, model, **kwargs):
        reviewer_call_count[0] += 1
        return {"text": "No objections.", "input_tokens": 30, "output_tokens": 5, "cost_usd": 0.0005}

    with patch.object(debate_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(debate_loop, "TOOL_MAP", _NOOP_TOOL_MAP), \
         patch.object(debate_loop, "score_combined", side_effect=_fake_score_combined), \
         patch.object(debate_loop, "complete", side_effect=fake_complete), \
         patch.object(debate_loop, "fabrication_guard", side_effect=_clean_guard):
        result = await debate_loop.run_debate(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=[],
            ledger=ledger,
            original_resume="Did work.",
        )

    assert reviewer_call_count[0] == 1, (
        f"Expected exactly 1 reviewer call (early exit), got {reviewer_call_count[0]}"
    )
    assert result["text"]


# ---------------------------------------------------------------------------
# Test 4: call_kind is set to "pro_debate"
# ---------------------------------------------------------------------------


async def test_debate_loop_sets_pro_debate_call_kind():
    """run_debate must call set_call_kind('pro_debate') at start."""
    from orchestration import debate_loop

    state = _make_state()
    ledger = _make_ledger()

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        return _fake_complete_with_tools_result(_done_msg())

    async def fake_complete(prompt, model, **kwargs):
        return {"text": "No objections.", "input_tokens": 30, "output_tokens": 5, "cost_usd": 0.0005}

    with patch.object(debate_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(debate_loop, "score_combined", side_effect=_fake_score_combined), \
         patch.object(debate_loop, "complete", side_effect=fake_complete), \
         patch.object(debate_loop, "fabrication_guard", side_effect=_clean_guard), \
         patch.object(debate_loop, "set_call_kind") as mock_set_kind:
        await debate_loop.run_debate(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=[],
            ledger=ledger,
            original_resume="Did work.",
        )

    mock_set_kind.assert_called_with("pro_debate")


# ---------------------------------------------------------------------------
# Test 5: fabrication_guard runs exactly once on final draft
# ---------------------------------------------------------------------------


async def test_debate_loop_guard_runs_on_final_draft():
    """fabrication_guard must be called exactly once (on the final draft) when loop exits."""
    from orchestration import debate_loop

    state = _make_state()
    ledger = _make_ledger()

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        return _fake_complete_with_tools_result(_done_msg())

    async def fake_complete(prompt, model, **kwargs):
        return {"text": "No objections.", "input_tokens": 30, "output_tokens": 5, "cost_usd": 0.0005}

    guard_call_count = [0]

    def counting_guard(generated_text, ledger_, source_text):
        guard_call_count[0] += 1
        return _clean_guard(generated_text, ledger_, source_text)

    with patch.object(debate_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(debate_loop, "score_combined", side_effect=_fake_score_combined), \
         patch.object(debate_loop, "complete", side_effect=fake_complete), \
         patch.object(debate_loop, "fabrication_guard", side_effect=counting_guard):
        await debate_loop.run_debate(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=[],
            ledger=ledger,
            original_resume="Did work.",
        )

    assert guard_call_count[0] == 1, (
        f"Expected fabrication_guard to be called exactly once, got {guard_call_count[0]}"
    )


# ---------------------------------------------------------------------------
# Test 6: final round skips both re-score and reviewer (spec 5b)
# ---------------------------------------------------------------------------


async def test_final_round_skips_rescore_and_reviewer(monkeypatch):
    """Round DEBATE_MAX_ROUNDS-1: objection would be discarded, so neither the
    re-score nor the reviewer call may fire (spec 5b)."""
    from agents.fact_extractor import ClaimsLedger
    from agents.tools import ResumeState
    from orchestration import debate_loop

    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    state = ResumeState(sections={"experience": "python work"},
                        capabilities=ledger.capabilities)
    counts = {"reviewer": 0, "score": 0, "opt": 0}

    class _ToolCall:
        id = "t1"
        class function:  # noqa: N801 - mimic litellm shape
            name = "bullet_strengthen"
            arguments = '{"weak_bullets_csv": "python work"}'

    class _MsgTools:
        content = ""
        tool_calls = [_ToolCall()]

    class _MsgDone:
        content = "done"
        tool_calls = None

    msgs = [_MsgTools(), _MsgDone(), _MsgTools(), _MsgDone()]

    async def fake_cwt(messages, model, tools, **kw):
        counts["opt"] += 1
        return {"message": msgs.pop(0), "input_tokens": 5, "output_tokens": 5,
                "cost_usd": 0.0, "cached_input_tokens": 0}

    async def fake_reviewer(prompt, model, **kw):
        counts["reviewer"] += 1
        return {"text": "OBJECTION: reorder the experience bullets",
                "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    async def fake_score(*a, **kw):
        counts["score"] += 1
        return {"text": {"overall": 70}, "tokens": {"input_tokens": 0, "output_tokens": 0},
                "cost_usd": 0.0}

    async def fake_tool(state_, **kw):
        state_.update_section("experience", "stronger python work " * counts["opt"])
        return "ok"

    def fake_guard(text, ledger_, original):
        return type("_G", (), {"gaps": [], "text": text})()

    monkeypatch.setattr(debate_loop, "complete_with_tools", fake_cwt)
    monkeypatch.setattr(debate_loop, "complete", fake_reviewer)
    monkeypatch.setattr(debate_loop, "score_combined", fake_score)
    monkeypatch.setattr(debate_loop, "fabrication_guard", fake_guard)
    monkeypatch.setattr(debate_loop, "TOOL_MAP", {"bullet_strengthen": fake_tool})

    result = await debate_loop.run_debate(
        state=state, scores={"overall": 60}, jd_text="jd", jd_keywords=[],
        ledger=ledger, original_resume="python work",
    )
    assert counts["reviewer"] == 1          # round 1 only; final round skipped
    assert counts["score"] == 1             # ditto
    assert "honest_gaps" in result


async def test_reviewer_prompt_is_presentation_only(monkeypatch):
    from agents.fact_extractor import ClaimsLedger
    from agents.tools import ResumeState
    from orchestration import debate_loop

    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    state = ResumeState(sections={"experience": "python work"},
                        capabilities=ledger.capabilities)
    state.add_gaps(["Kubernetes"])
    captured = {}

    class _ToolCall:
        id = "t1"
        class function:  # noqa: N801
            name = "bullet_strengthen"
            arguments = '{"weak_bullets_csv": "python work"}'

    class _MsgTools:
        content = ""
        tool_calls = [_ToolCall()]

    class _MsgDone:
        content = "done"
        tool_calls = None

    msgs = [_MsgTools(), _MsgDone()]

    async def fake_cwt(messages, model, tools, **kw):
        return {"message": msgs.pop(0), "input_tokens": 5, "output_tokens": 5,
                "cost_usd": 0.0, "cached_input_tokens": 0}

    async def fake_reviewer(prompt, model, **kw):
        captured["prompt"] = prompt
        return {"text": "No objections.", "input_tokens": 1, "output_tokens": 1,
                "cost_usd": 0.0}

    async def fake_score(*a, **kw):
        return {"text": {"overall": 70, "ats": {"score": 70}},
                "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

    async def fake_tool(state_, **kw):
        state_.update_section("experience", "stronger python work")
        return "ok"

    def fake_guard(text, ledger_, original):
        return type("_G", (), {"gaps": [], "text": text})()

    monkeypatch.setattr(debate_loop, "complete_with_tools", fake_cwt)
    monkeypatch.setattr(debate_loop, "complete", fake_reviewer)
    monkeypatch.setattr(debate_loop, "score_combined", fake_score)
    monkeypatch.setattr(debate_loop, "fabrication_guard", fake_guard)
    monkeypatch.setattr(debate_loop, "TOOL_MAP", {"bullet_strengthen": fake_tool})

    await debate_loop.run_debate(
        state=state, scores={"overall": 60}, jd_text="jd", jd_keywords=[],
        ledger=ledger, original_resume="python work",
    )
    p = captured["prompt"]
    assert "PRESENTATION" in p
    assert "HONEST GAPS" in p and "Kubernetes" in p
    assert "CURRENT SCORES" in p or "UPDATED SCORES" in p
    assert "Do NOT raise objections about: missing skills" in p
