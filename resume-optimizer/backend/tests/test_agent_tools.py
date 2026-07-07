"""
Tests for agents/tools.py — async tool functions and ResumeState.

Uses pytest-asyncio (asyncio_mode = auto from pytest.ini) so all async
test functions run automatically without explicit @pytest.mark.asyncio.

Mocking strategy: patch `agents.tools.complete` (the name as resolved in
that module) so we never hit a real LLM.
"""

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_RESULT = {
    "text": "Improved text here.",
    "input_tokens": 20,
    "output_tokens": 10,
    "cost_usd": 0.001,
}


async def _fake_complete(prompt, model, **kw):
    return FAKE_RESULT


async def _empty_complete(prompt, model, **kw):
    """Simulates an LLM returning an empty string."""
    return {"text": "", "input_tokens": 5, "output_tokens": 0, "cost_usd": 0.0}


# ---------------------------------------------------------------------------
# ResumeState unit tests
# ---------------------------------------------------------------------------


def test_resume_state_basic():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "Hello world.", "experience": "Did stuff."})
    assert st.get_section("summary") == "Hello world."
    assert st.get_section("nonexistent") == ""
    assert set(st.available_sections()) == {"summary", "experience"}


def test_resume_state_update_section():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "Old text."})
    st.update_section("summary", "New text.")
    assert st.get_section("summary") == "New text."


def test_resume_state_token_accounting():
    from agents import tools

    st = tools.ResumeState(sections={})
    st.add_tokens(100, 50, 0.01)
    assert st.total_tokens() == 150
    assert st.input_tokens == 100
    assert st.output_tokens == 50
    assert abs(st.cost_usd - 0.01) < 1e-9


def test_resume_state_token_accumulation():
    from agents import tools

    st = tools.ResumeState(sections={})
    st.add_tokens(10, 5, 0.001)
    st.add_tokens(20, 8, 0.002)
    assert st.total_tokens() == 43
    assert abs(st.cost_usd - 0.003) < 1e-9


def test_resume_state_available_sections_excludes_empty():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "text", "experience": "", "skills": "  "})
    assert st.available_sections() == ["summary"]


def test_resume_state_reassemble_canonical_order():
    from agents import tools

    # experience and summary are both in SECTION_ORDER; summary comes before experience
    st = tools.ResumeState(sections={"experience": "EXP", "summary": "SUM"})
    result = st.reassemble()
    assert result.index("SUM") < result.index("EXP")


# ---------------------------------------------------------------------------
# keyword_inject tests
# ---------------------------------------------------------------------------


async def test_keyword_inject_updates_section_and_cost():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "Built things.", "experience": "Did work."})

    async def fake(prompt, model, **kw):
        return {"text": "Built scalable things.", "input_tokens": 20, "output_tokens": 10, "cost_usd": 0.001}

    with patch.object(tools, "complete", new=fake):
        msg = await tools.keyword_inject(st, missing_keywords_csv="scalable", target_sections_csv="summary")

    assert "scalable" in st.get_section("summary")
    assert st.cost_usd > 0
    assert st.total_tokens() > 0
    assert "summary" in msg


async def test_keyword_inject_multiple_sections():
    from agents import tools

    st = tools.ResumeState(sections={
        "summary": "Professional summary.",
        "experience": "Work experience."
    })
    call_count = 0

    async def fake(prompt, model, **kw):
        nonlocal call_count
        call_count += 1
        return {"text": f"Improved text {call_count}.", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0005}

    with patch.object(tools, "complete", new=fake):
        msg = await tools.keyword_inject(
            st,
            missing_keywords_csv="python,agile",
            target_sections_csv="summary,experience",
        )

    assert call_count == 2
    assert st.total_tokens() == 30  # 2 calls × (10+5)


async def test_keyword_inject_budget_guard():
    from agents import tools
    from config import AGENT_TOKEN_BUDGET

    st = tools.ResumeState(sections={"summary": "Some text."})
    # Exhaust the budget
    st.add_tokens(AGENT_TOKEN_BUDGET, 0, 0.0)

    call_count = 0

    async def fake(prompt, model, **kw):
        nonlocal call_count
        call_count += 1
        return FAKE_RESULT

    with patch.object(tools, "complete", new=fake):
        msg = await tools.keyword_inject(st, missing_keywords_csv="python", target_sections_csv="summary")

    assert call_count == 0, "complete() must NOT be called when budget is exhausted"
    assert "budget" in msg.lower() or "token" in msg.lower()


async def test_keyword_inject_section_not_found():
    from agents import tools

    st = tools.ResumeState(sections={"experience": "Some work."})

    with patch.object(tools, "complete", new=_fake_complete):
        msg = await tools.keyword_inject(st, missing_keywords_csv="python", target_sections_csv="summary")

    # summary section is missing — should return informative string
    assert "available" in msg.lower() or "not found" in msg.lower() or "no target" in msg.lower()


async def test_keyword_inject_empty_section_skipped():
    """An empty target section should be skipped (not passed to LLM)."""
    from agents import tools

    st = tools.ResumeState(sections={"summary": "", "experience": "Real work."})
    call_count = 0

    async def fake(prompt, model, **kw):
        nonlocal call_count
        call_count += 1
        return FAKE_RESULT

    with patch.object(tools, "complete", new=fake):
        await tools.keyword_inject(st, missing_keywords_csv="python", target_sections_csv="summary,experience")

    # summary is empty, only experience gets a call
    assert call_count == 1


# ---------------------------------------------------------------------------
# bullet_strengthen tests
# ---------------------------------------------------------------------------


async def test_bullet_strengthen_updates_section_and_cost():
    from agents import tools

    st = tools.ResumeState(sections={"experience": "- Helped with deployments.\n- Worked on APIs."})

    with patch.object(tools, "complete", new=_fake_complete):
        msg = await tools.bullet_strengthen(st, weak_bullets_csv="Helped with deployments.")

    assert st.get_section("experience") == FAKE_RESULT["text"]
    assert st.cost_usd > 0
    assert st.total_tokens() > 0


async def test_bullet_strengthen_budget_guard():
    from agents import tools
    from config import AGENT_TOKEN_BUDGET

    st = tools.ResumeState(sections={"experience": "- Did stuff."})
    st.add_tokens(AGENT_TOKEN_BUDGET, 0, 0.0)

    call_count = 0

    async def fake(prompt, model, **kw):
        nonlocal call_count
        call_count += 1
        return FAKE_RESULT

    with patch.object(tools, "complete", new=fake):
        msg = await tools.bullet_strengthen(st, weak_bullets_csv="Did stuff.")

    assert call_count == 0
    assert "budget" in msg.lower() or "token" in msg.lower()


async def test_bullet_strengthen_no_experience_section():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "I am great."})

    with patch.object(tools, "complete", new=_fake_complete):
        msg = await tools.bullet_strengthen(st, weak_bullets_csv="Did stuff.")

    # Should return informative fallback, not crash
    assert "experience" in msg.lower() or "available" in msg.lower()
    # Section should NOT be created
    assert not st.get_section("experience")


async def test_bullet_strengthen_empty_output_unchanged():
    """When LLM returns empty text, section should remain unchanged."""
    from agents import tools

    original = "- Did stuff.\n- Made things."
    st = tools.ResumeState(sections={"experience": original})

    with patch.object(tools, "complete", new=_empty_complete):
        msg = await tools.bullet_strengthen(st, weak_bullets_csv="Did stuff.")

    assert st.get_section("experience") == original
    assert "empty" in msg.lower() or "unchanged" in msg.lower()


# ---------------------------------------------------------------------------
# skills_rewrite tests
# ---------------------------------------------------------------------------


async def test_skills_rewrite_updates_section_and_cost():
    from agents import tools

    st = tools.ResumeState(sections={"skills": "Python, SQL, Git"})

    with patch.object(tools, "complete", new=_fake_complete):
        msg = await tools.skills_rewrite(st, missing_skills_csv="Docker, Kubernetes")

    assert st.get_section("skills") == FAKE_RESULT["text"]
    assert st.cost_usd > 0
    assert st.total_tokens() > 0


async def test_skills_rewrite_budget_guard():
    from agents import tools
    from config import AGENT_TOKEN_BUDGET

    st = tools.ResumeState(sections={"skills": "Python"})
    st.add_tokens(AGENT_TOKEN_BUDGET, 0, 0.0)

    call_count = 0

    async def fake(prompt, model, **kw):
        nonlocal call_count
        call_count += 1
        return FAKE_RESULT

    with patch.object(tools, "complete", new=fake):
        msg = await tools.skills_rewrite(st, missing_skills_csv="Docker")

    assert call_count == 0
    assert "budget" in msg.lower() or "token" in msg.lower()


async def test_skills_rewrite_no_skills_section():
    from agents import tools

    st = tools.ResumeState(sections={"experience": "Did work."})

    with patch.object(tools, "complete", new=_fake_complete):
        msg = await tools.skills_rewrite(st, missing_skills_csv="Docker")

    assert "skill" in msg.lower() or "keyword_inject" in msg.lower()
    assert not st.get_section("skills")


async def test_skills_rewrite_empty_output_unchanged():
    from agents import tools

    original = "Python, SQL"
    st = tools.ResumeState(sections={"skills": original})

    with patch.object(tools, "complete", new=_empty_complete):
        msg = await tools.skills_rewrite(st, missing_skills_csv="Docker")

    assert st.get_section("skills") == original
    assert "empty" in msg.lower() or "unchanged" in msg.lower()


# ---------------------------------------------------------------------------
# Prompt content sanity checks (no fabrication rules carried over)
# ---------------------------------------------------------------------------


async def test_keyword_inject_prompt_contains_no_placeholder_metrics_rule():
    """The prompt sent to the LLM must include the no-placeholder-metrics rule."""
    from agents import tools

    st = tools.ResumeState(sections={"summary": "Built software."})
    captured_prompts = []

    async def capturing_fake(prompt, model, **kw):
        captured_prompts.append(prompt)
        return FAKE_RESULT

    with patch.object(tools, "complete", new=capturing_fake):
        await tools.keyword_inject(st, missing_keywords_csv="scalable", target_sections_csv="summary")

    assert captured_prompts, "complete() was not called"
    prompt_text = captured_prompts[0]
    assert "XX%" in prompt_text or "placeholder" in prompt_text.lower()


async def test_bullet_strengthen_prompt_contains_no_placeholder_rule():
    from agents import tools

    st = tools.ResumeState(sections={"experience": "- Did stuff."})
    captured_prompts = []

    async def capturing_fake(prompt, model, **kw):
        captured_prompts.append(prompt)
        return FAKE_RESULT

    with patch.object(tools, "complete", new=capturing_fake):
        await tools.bullet_strengthen(st, weak_bullets_csv="Did stuff.")

    assert captured_prompts
    assert "XX%" in captured_prompts[0] or "placeholder" in captured_prompts[0].lower()


# ---------------------------------------------------------------------------
# Empty CSV early-return guard tests
# ---------------------------------------------------------------------------


async def test_keyword_inject_empty_csv_returns_early():
    """Empty missing_keywords_csv must return early without calling the LLM."""
    from agents import tools

    st = tools.ResumeState(sections={"summary": "Built software.", "experience": "Did work."})

    call_count = 0

    async def fake(prompt, model, **kw):
        nonlocal call_count
        call_count += 1
        return FAKE_RESULT

    with patch.object(tools, "complete", new=fake):
        msg = await tools.keyword_inject(st, missing_keywords_csv="", target_sections_csv="summary")

    assert call_count == 0, "complete() must NOT be called when keywords CSV is empty"
    assert "no keywords" in msg.lower()
    assert st.total_tokens() == 0


async def test_bullet_strengthen_empty_csv_returns_early():
    """Empty weak_bullets_csv must return early without calling the LLM."""
    from agents import tools

    st = tools.ResumeState(sections={"experience": "- Did stuff."})

    call_count = 0

    async def fake(prompt, model, **kw):
        nonlocal call_count
        call_count += 1
        return FAKE_RESULT

    with patch.object(tools, "complete", new=fake):
        msg = await tools.bullet_strengthen(st, weak_bullets_csv="")

    assert call_count == 0, "complete() must NOT be called when bullets CSV is empty"
    assert "no weak bullets" in msg.lower()
    assert st.total_tokens() == 0


async def test_skills_rewrite_empty_csv_returns_early():
    """Empty missing_skills_csv must return early without calling the LLM."""
    from agents import tools

    st = tools.ResumeState(sections={"skills": "Python, SQL"})

    call_count = 0

    async def fake(prompt, model, **kw):
        nonlocal call_count
        call_count += 1
        return FAKE_RESULT

    with patch.object(tools, "complete", new=fake):
        msg = await tools.skills_rewrite(st, missing_skills_csv="")

    assert call_count == 0, "complete() must NOT be called when skills CSV is empty"
    assert "no missing skills" in msg.lower()
    assert st.total_tokens() == 0


async def test_keyword_inject_complete_failure_returns_error_string():
    """When complete() raises, keyword_inject should return an error string, not propagate."""
    from agents import tools

    original_summary = "Built software."
    st = tools.ResumeState(sections={"summary": original_summary})

    async def failing_complete(prompt, model, **kw):
        raise Exception("timeout")

    with patch.object(tools, "complete", new=failing_complete):
        msg = await tools.keyword_inject(st, missing_keywords_csv="scalable", target_sections_csv="summary")

    assert "llm call failed" in msg.lower()
    assert "timeout" in msg.lower()
    # Section must be unchanged since the call failed
    assert st.get_section("summary") == original_summary
    assert st.total_tokens() == 0


# ---------------------------------------------------------------------------
# Capabilities + honest gaps (truthful optimizer)
# ---------------------------------------------------------------------------


def test_resume_state_capabilities_lowercased():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "x"}, capabilities=frozenset({"Python", "AWS"}))
    assert st.capabilities == frozenset({"python", "aws"})


def test_resume_state_gap_collector_dedups_and_sorts():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "x"})
    st.add_gaps(["Kubernetes", "terraform", "Kubernetes", "  "])
    st.add_gaps(("docker",))
    assert st.honest_gaps() == ["Kubernetes", "docker", "terraform"]
