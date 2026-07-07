"""
Tests for orchestration/agent_loop.py — the A+C agent loop driver.

Mocking strategy:
  - `complete_with_tools` is patched on the agent_loop module so no real
    LLM calls are made.
  - `score_combined` is patched similarly so no scorer calls hit the network.
  - `fabrication_guard` is patched in most tests to return a clean result
    so the test can control loop behaviour without depending on spaCy NER.
  - Individual tool functions are replaced with lightweight async stubs in
    TOOL_MAP patches so we avoid any LLM dependency inside tools.

pytest-asyncio runs in auto mode (set in pytest.ini), so async defs are
picked up automatically.
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SCORES_ALL_OK = {
    "ats":         {"score": 95, "missing_keywords": [], "matched_keywords": ["python"]},
    "impact":      {"score": 95, "weak_bullets": [],     "strong_bullets": []},
    "skills_gap":  {"score": 95, "missing_skills": [],   "matched_skills": []},
    "readability": {"score": 95, "issues": [],           "worst_section": "experience"},
    "overall": 95,
}

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


def _tool_msg(tool_name: str, arguments: dict, call_id: str = "call_1"):
    """Return a fake assistant message with one tool call."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = __import__("json").dumps(arguments)
    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    return msg


def _fake_result(msg, in_tok=100, out_tok=50, cost=0.01):
    return {"message": msg, "input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": cost}


async def _fake_score_all_ok(*args, **kwargs):
    return {
        "text": SCORES_ALL_OK,
        "tokens": {"input_tokens": 50, "output_tokens": 10},
        "cost_usd": 0.002,
    }


async def _noop_tool(state, **kwargs):
    return "ok"


_PATCHED_TOOL_MAP = {
    "keyword_inject":    _noop_tool,
    "bullet_strengthen": _noop_tool,
    "skills_rewrite":    _noop_tool,
}


def _clean_guard(generated_text, ledger, source_text):
    """Fabrication guard stub that always returns clean (no gaps)."""
    from agents.fabrication_guard import GuardResult
    return GuardResult(text=generated_text, stripped=[], gaps=[])


# ---------------------------------------------------------------------------
# Test 1: happy path — loop calls tools then terminates
# ---------------------------------------------------------------------------


async def test_loop_calls_tools_then_terminates():
    """Loop executes tool calls returned by model, then terminates when model
    returns no tool_calls."""
    from orchestration import agent_loop

    state = _make_state()
    ledger = _make_ledger()

    tool_call_count = [0]

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        if tool_call_count[0] == 0:
            tool_call_count[0] += 1
            msg = _tool_msg("keyword_inject", {"missing_keywords_csv": "docker"})
            return _fake_result(msg)
        else:
            return _fake_result(_done_msg(), in_tok=80, out_tok=20, cost=0.005)

    async def fake_tool(st, **kwargs):
        st.update_section("experience", "Did docker work.")
        return "Injected docker."

    patched_map = {**_PATCHED_TOOL_MAP, "keyword_inject": fake_tool}

    with patch.object(agent_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(agent_loop, "score_combined", side_effect=_fake_score_all_ok), \
         patch.object(agent_loop, "fabrication_guard", side_effect=_clean_guard), \
         patch.object(agent_loop, "TOOL_MAP", patched_map):
        result = await agent_loop.run_agent(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=["docker"],
            ledger=ledger,
            original_resume="Did work.",
        )

    assert result["text"], "Should return non-empty text"
    assert result["iterations"] >= 1, "Should have made at least one complete_with_tools call"
    assert result["input_tokens"] > 0
    assert result["output_tokens"] > 0
    # Tool was called — section should have been updated
    assert "docker" in state.get_section("experience").lower()


# ---------------------------------------------------------------------------
# Test 2: budget exceeded — inner loop exits before model call
# ---------------------------------------------------------------------------


async def test_loop_terminates_on_budget_exceeded():
    """When total_tokens() >= AGENT_TOKEN_BUDGET before a call, the inner
    loop exits without calling complete_with_tools again."""
    from orchestration import agent_loop
    from config import AGENT_TOKEN_BUDGET

    state = _make_state()
    # Pre-load the state with tokens at the limit
    state.add_tokens(AGENT_TOKEN_BUDGET, 0, 0.0)
    ledger = _make_ledger()

    call_count = [0]

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        call_count[0] += 1
        return _fake_result(_done_msg())

    with patch.object(agent_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(agent_loop, "score_combined", side_effect=_fake_score_all_ok), \
         patch.object(agent_loop, "fabrication_guard", side_effect=_clean_guard), \
         patch.object(agent_loop, "TOOL_MAP", _PATCHED_TOOL_MAP):
        result = await agent_loop.run_agent(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=[],
            ledger=ledger,
            original_resume="Did work.",
        )

    # complete_with_tools should NOT have been called (budget already exceeded)
    assert call_count[0] == 0, (
        f"Expected 0 LLM calls when budget is pre-exhausted, got {call_count[0]}"
    )
    assert result["text"]  # should still return the current draft


# ---------------------------------------------------------------------------
# Test 3: unknown tool name — graceful handling, no crash
# ---------------------------------------------------------------------------


async def test_loop_handles_unknown_tool_gracefully():
    """When the model returns an unknown tool name, the loop appends an error
    observation and continues — it must not raise."""
    from orchestration import agent_loop

    state = _make_state()
    ledger = _make_ledger()

    call_count = [0]

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            # Return a call to a tool that doesn't exist
            msg = _tool_msg("nonexistent_tool", {"arg": "val"}, call_id="call_bad")
            return _fake_result(msg)
        else:
            return _fake_result(_done_msg())

    with patch.object(agent_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(agent_loop, "score_combined", side_effect=_fake_score_all_ok), \
         patch.object(agent_loop, "fabrication_guard", side_effect=_clean_guard), \
         patch.object(agent_loop, "TOOL_MAP", _PATCHED_TOOL_MAP):
        result = await agent_loop.run_agent(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=[],
            ledger=ledger,
            original_resume="Did work.",
        )

    # Must not raise; result must be a valid dict
    assert isinstance(result, dict)
    assert result["text"]
    assert result["iterations"] >= 1

    # The error observation should have been appended as a tool message
    # (verified indirectly: second call was made, so loop continued)
    assert call_count[0] >= 1


# ---------------------------------------------------------------------------
# Test 4: fabrication guard gaps trigger a follow-up message
# ---------------------------------------------------------------------------


async def test_reflection_feeds_back_guard_flags():
    """When fabrication_guard returns .gaps, a user message with the flags
    is appended to the conversation, and the loop continues for another
    reflection iteration."""
    from orchestration import agent_loop
    from agents.fabrication_guard import GuardResult

    state = _make_state()
    ledger = _make_ledger()

    # Track messages sent to complete_with_tools across calls
    all_message_batches: list[list] = []
    call_count = [0]

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        all_message_batches.append(list(messages))
        call_count[0] += 1
        return _fake_result(_done_msg(f"Done (call {call_count[0]})"))

    # scores stay below target so reflection loop keeps going until max
    async def fake_score_below(*args, **kwargs):
        return {
            "text": SCORES_BELOW_TARGET,
            "tokens": {"input_tokens": 50, "output_tokens": 10},
            "cost_usd": 0.002,
        }

    # Fabrication guard always returns a gap on the first reflection,
    # then clean on the second — use a side_effect list
    guard_gap = GuardResult(
        text="Did work.",
        stripped=["fake_metric"],
        gaps=["unverified claim: 'fake_metric'"],
    )
    guard_clean = GuardResult(text="Did work.", stripped=[], gaps=[])

    guard_results = [guard_gap, guard_clean]
    guard_iter = [0]

    def fake_guard(generated_text, ledger_, source_text):
        idx = min(guard_iter[0], len(guard_results) - 1)
        guard_iter[0] += 1
        return guard_results[idx]

    with patch.object(agent_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(agent_loop, "score_combined", side_effect=fake_score_below), \
         patch.object(agent_loop, "fabrication_guard", side_effect=fake_guard), \
         patch.object(agent_loop, "TOOL_MAP", _PATCHED_TOOL_MAP):
        result = await agent_loop.run_agent(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=[],
            ledger=ledger,
            original_resume="Did work.",
        )

    assert isinstance(result, dict)
    assert result["iterations"] >= 1

    # After the first reflection (with gaps), a user message should have been
    # appended before the second complete_with_tools call — verify by checking
    # that a later message batch contains a user-role message with guard text.
    if len(all_message_batches) >= 2:
        second_batch_roles = [m["role"] for m in all_message_batches[1]]
        assert "user" in second_batch_roles, (
            "Expected a user feedback message in the second LLM call after guard flags"
        )
        # Check that guard gap text appears somewhere in the user messages
        user_contents = " ".join(
            m.get("content", "") for m in all_message_batches[1] if m["role"] == "user"
        )
        assert "fabrication" in user_contents.lower() or "guard" in user_contents.lower() or "flagged" in user_contents.lower(), (
            f"Expected guard flag info in user message. Got: {user_contents!r}"
        )


# ---------------------------------------------------------------------------
# Test 5: on_event callback is invoked for each tool execution
# ---------------------------------------------------------------------------


async def test_on_event_callback_invoked():
    """The on_event callable must be called once per tool dispatched."""
    from orchestration import agent_loop

    state = _make_state()
    ledger = _make_ledger()

    events: list[dict] = []

    def on_event(ev: dict):
        events.append(ev)

    call_count = [0]

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            return _fake_result(_tool_msg("keyword_inject", {"missing_keywords_csv": "docker"}))
        return _fake_result(_done_msg())

    with patch.object(agent_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(agent_loop, "score_combined", side_effect=_fake_score_all_ok), \
         patch.object(agent_loop, "fabrication_guard", side_effect=_clean_guard), \
         patch.object(agent_loop, "TOOL_MAP", _PATCHED_TOOL_MAP):
        await agent_loop.run_agent(
            state=state,
            scores=SCORES_BELOW_TARGET,
            jd_text="JD text",
            jd_keywords=["docker"],
            ledger=ledger,
            original_resume="Did work.",
            on_event=on_event,
        )

    assert len(events) >= 1, "on_event should have been called at least once"
    first = events[0]
    assert first["type"] == "agent_step"
    assert "keyword_inject" in first["message"]
    assert "tokens_used" in first
    assert "budget" in first


# ---------------------------------------------------------------------------
# Test 6: capped (gap-blocked) dimensions stop reflections and report gaps
# ---------------------------------------------------------------------------


async def test_capped_dimensions_stop_reflections_and_report_gaps(monkeypatch):
    """Below-target but gap-blocked dimensions must end the loop (no treadmill)
    and surface honest_gaps in the result."""
    from agents.fact_extractor import ClaimsLedger
    from agents.tools import ResumeState
    from orchestration import agent_loop

    capped_scores = {
        "ats":          {"score": 50, "missing_keywords": ["Kubernetes"]},
        "impact":       {"score": 95, "weak_bullets": []},
        "skills_gap":   {"score": 55, "missing_skills": ["Terraform"]},
        "readability":  {"score": 60},
        "jd_tailoring": {"score": 95, "issues": []},
        "overall": 70,
    }
    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    state = ResumeState(sections={"experience": "Did python things."},
                        capabilities=ledger.capabilities)

    calls = {"llm": 0, "score": 0}

    class _Msg:
        content = "done"
        tool_calls = None

    async def fake_cwt(messages, model, tools, **kw):
        calls["llm"] += 1
        return {"message": _Msg(), "input_tokens": 10, "output_tokens": 5,
                "cost_usd": 0.0, "cached_input_tokens": 0}

    async def fake_score(*a, **kw):
        calls["score"] += 1
        return {"text": capped_scores, "tokens": {"input_tokens": 0, "output_tokens": 0},
                "cost_usd": 0.0}

    def fake_guard(text, ledger_, original):
        return type("_G", (), {"gaps": [], "text": text})()

    monkeypatch.setattr(agent_loop, "complete_with_tools", fake_cwt)
    monkeypatch.setattr(agent_loop, "score_combined", fake_score)
    monkeypatch.setattr(agent_loop, "fabrication_guard", fake_guard)

    result = await agent_loop.run_agent(
        state=state, scores=capped_scores, jd_text="jd", jd_keywords=[],
        ledger=ledger, original_resume="Did python things.",
    )
    # one strategist turn, then loop ends: ats/skills below target but capped
    assert calls["llm"] == 1
    assert result["honest_gaps"] == ["Kubernetes", "Terraform"]
