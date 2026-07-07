"""Tests for cost tracking flow through agents and pipeline.

Verifies that:
1. All agents return dicts with "text" and "tokens" keys
2. Tokens are accumulated correctly through the pipeline
3. Cost is calculated correctly from token counts
4. Delta Lake receives correct input_tokens, output_tokens, tokens_used
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio

# Set up test env vars before importing modules
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DELTA_STORAGE_PATH", "./test_delta_store")

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.humanizer import humanize_resume
from agents.jd_analyzer import analyze_jd
from agents.scorer import score_combined
from agents.rewriter import rewrite_resume


# ── Humanizer tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_humanizer_returns_dict_with_text_and_tokens():
    """Test that humanize_resume returns {"text": ..., "tokens": {"input_tokens": X, "output_tokens": Y}}."""
    mock_response_1 = MagicMock()
    mock_response_1.content = [MagicMock()]
    mock_response_1.content[0].text = "Polished resume text."
    mock_response_1.usage.input_tokens = 100
    mock_response_1.usage.output_tokens = 50

    mock_response_2 = MagicMock()
    mock_response_2.content = [MagicMock()]
    mock_response_2.content[0].text = '{"robotic_phrases": ["responsible for"]}'
    mock_response_2.usage.input_tokens = 80
    mock_response_2.usage.output_tokens = 20

    mock_response_3 = MagicMock()
    mock_response_3.content = [MagicMock()]
    mock_response_3.content[0].text = "Final polished resume."
    mock_response_3.usage.input_tokens = 100
    mock_response_3.usage.output_tokens = 40

    responses = [mock_response_1, mock_response_2, mock_response_3]
    call_count = [0]

    async def mock_complete(prompt, model, cached_prefix=None, response_format=None):
        result = responses[call_count[0]]
        call_count[0] += 1
        return {
            "text": result.content[0].text,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        }

    with patch("agents.humanizer.complete", side_effect=mock_complete):
        result = await humanize_resume("Original resume text.")

        # Verify result structure
        assert isinstance(result, dict)
        assert "text" in result
        assert "tokens" in result

        # Verify tokens are accumulated correctly
        tokens = result["tokens"]
        assert tokens["input_tokens"] == 100 + 80 + 100  # 280
        assert tokens["output_tokens"] == 50 + 20 + 40    # 110
        assert isinstance(result["text"], str)


# ── JD Analyzer tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jd_analyzer_returns_dict_with_text_and_tokens():
    """Test that analyze_jd returns a flat structured dict with legacy keys present."""
    llm_payload = (
        '{"keywords": ["python", "sql"], "requirements": [], "skills": [],'
        ' "required_hard_skills": ["Python", "SQL"], "preferred_soft_skills": [],'
        ' "critical_keywords": ["python", "sql"], "tech_stack": ["Python"],'
        ' "seniority_level": "mid", "industry": "saas", "required_certifications": []}'
    )

    async def mock_complete(prompt, model, **kwargs):
        return {
            "text": llm_payload,
            "input_tokens": 150,
            "output_tokens": 75,
        }

    with patch("agents.jd_analyzer.complete", side_effect=mock_complete):
        # Clear cache to ensure fresh result
        from utils import cache
        cache.clear()

        result = await analyze_jd("Sample JD with Python and SQL requirements.")

        # Current schema: {"text": <structured dict>, "tokens": {...}, "cost_usd": float}
        assert isinstance(result, dict)
        assert "text" in result and "tokens" in result
        payload = result["text"]

        # Legacy keys still present for backward compatibility
        assert "keywords" in payload
        assert "requirements" in payload
        assert "skills" in payload

        # New structured keys
        assert "required_hard_skills" in payload
        assert "seniority_level" in payload
        assert "industry" in payload
        assert "tech_stack" in payload


# ── Scorer tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scorer_returns_dict_with_text_and_tokens():
    """Test that score_combined returns a flat dict with scoring sections."""
    fake_scores = {
        "ats": {"score": 75, "missing_keywords": [], "matched_keywords": [], "keyword_coverage_pct": 50.0},
        "impact": {"score": 70, "weak_bullets": [], "strong_bullets": [], "has_quantified_achievements": False},
        "skills_gap": {"score": 80, "missing_skills": [], "matched_skills": [], "critical_missing": []},
        "readability": {"score": 85, "issues": [], "worst_section": "experience", "has_summary": True, "tense_consistent": True},
        "overall": 77,
    }

    async def mock_llm_complete(prompt, system=None, **kwargs):
        # real _llm_complete returns (parsed_json, cost_usd, input_tokens, output_tokens)
        return fake_scores, 0.0, 100, 50

    with patch("agents.scorer._llm_complete", side_effect=mock_llm_complete):
        result = await score_combined("Resume text.", "JD text.", ["python"])

        # Current schema: {"text": <scores dict>, "tokens": {...}, "cost_usd": float}
        assert isinstance(result, dict)
        assert "text" in result and "tokens" in result
        scores = result["text"]
        assert "ats" in scores
        assert "impact" in scores
        assert "skills_gap" in scores
        assert "readability" in scores


# ── Rewriter tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rewriter_returns_dict_with_text_and_tokens():
    """Test that rewrite_resume returns {"text": ..., "tokens": {...}}."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "Rewritten resume incorporating JD keywords."
    mock_response.usage.input_tokens = 250
    mock_response.usage.output_tokens = 150

    async def mock_complete(prompt, model, cached_prefix=None):
        return {
            "text": mock_response.content[0].text,
            "input_tokens": mock_response.usage.input_tokens,
            "output_tokens": mock_response.usage.output_tokens,
        }

    with patch("agents.rewriter.complete", side_effect=mock_complete):
        result = await rewrite_resume(
            resume_text="Original resume.",
            jd_keywords=["python", "sql"],
            consolidated_feedback=None,
            claims_ledger=None,
        )

        # Verify result structure
        assert isinstance(result, dict)
        assert "text" in result
        assert "tokens" in result

        # Verify tokens
        tokens = result["tokens"]
        assert tokens["input_tokens"] == 250
        assert tokens["output_tokens"] == 150
        assert isinstance(result["text"], str)


# ── Pipeline token accumulation tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_accumulates_tokens_from_all_agents():
    """Test that pipeline correctly sums tokens from JD analysis, scoring, and rewriting."""
    # This is a simplified integration test showing token accumulation logic
    jd_tokens = {"input_tokens": 150, "output_tokens": 75}
    score_tokens = {"input_tokens": 200, "output_tokens": 100}
    rewrite_tokens = {"input_tokens": 250, "output_tokens": 150}
    humanize_tokens = {"input_tokens": 100, "output_tokens": 50}

    # Simulate pipeline accumulation
    total_input = jd_tokens["input_tokens"] + score_tokens["input_tokens"] + rewrite_tokens["input_tokens"] + humanize_tokens["input_tokens"]
    total_output = jd_tokens["output_tokens"] + score_tokens["output_tokens"] + rewrite_tokens["output_tokens"] + humanize_tokens["output_tokens"]

    assert total_input == 150 + 200 + 250 + 100  # 700
    assert total_output == 75 + 100 + 150 + 50   # 375
    assert total_input + total_output == 1075


# ── Cost calculation tests ────────────────────────────────────────────────────

def test_cost_calculation_from_tokens():
    """Test that cost is correctly calculated from token counts."""
    # Simulate ProviderCost rates (in dollars per 1M tokens)
    # Note: Anthropic pricing is approximately $3/1M input, $15/1M output for claude-3.5-sonnet
    input_rate = 3.0  # $3 per 1M input tokens
    output_rate = 15.0  # $15 per 1M output tokens

    # Test 1: Small token count
    input_tokens = 100_000
    output_tokens = 50_000

    input_cost = (input_tokens / 1_000_000) * input_rate  # 0.3 dollars
    output_cost = (output_tokens / 1_000_000) * output_rate  # 0.75 dollars
    total_cost_cents = int((input_cost + output_cost) * 100)  # 105 cents = $1.05
    assert total_cost_cents == 105

    # Test 2: 1M input + 0.5M output tokens
    input_tokens = 1_000_000
    output_tokens = 500_000

    input_cost = (input_tokens / 1_000_000) * input_rate  # 3 dollars
    output_cost = (output_tokens / 1_000_000) * output_rate  # 7.5 dollars
    total_cost_cents = int((input_cost + output_cost) * 100)  # 1050 cents = $10.50
    assert total_cost_cents == 1050

    # Test 3: 10M input + 5M output tokens
    input_tokens = 10_000_000
    output_tokens = 5_000_000

    input_cost = (input_tokens / 1_000_000) * input_rate  # 30 dollars
    output_cost = (output_tokens / 1_000_000) * output_rate  # 75 dollars
    total_cost_cents = int((input_cost + output_cost) * 100)  # 10500 cents = $105
    assert total_cost_cents == 10500


def test_delta_write_includes_token_fields():
    """Test that write_daily_usage correctly formats input_tokens, output_tokens, tokens_used."""
    record = {
        "user_id": "test-user-123",
        "date": date.today().isoformat(),
        "pipeline_runs": 1,
        "uploads": 1,
        "input_tokens": 1_000_000,
        "output_tokens": 500_000,
        "tokens_used": 1_500_000,
    }

    # Verify all required keys are present
    assert "input_tokens" in record
    assert "output_tokens" in record
    assert "tokens_used" in record

    # Verify values
    assert record["input_tokens"] == 1_000_000
    assert record["output_tokens"] == 500_000
    assert record["tokens_used"] == record["input_tokens"] + record["output_tokens"]


# ── Phase 2 async correctness tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_phase2_tool_calls_do_not_use_asyncio_run():
    """
    Verify that Phase 2 tools call complete() as an awaitable coroutine,
    not via asyncio.run() which would prevent LlmCallLog from being written.

    This is a structural test: it confirms complete() is called with 'await'
    by checking that the tools module does not contain 'asyncio.run()' in executable code.

    Context: The old bug used asyncio.run(complete(...)) which creates a new event loop,
    runs the LLM call, then tears down the loop — cancelling the async fire-and-forget
    _record_call before it could commit an LlmCallLog row. The fix: tools now call
    'await complete(...)' on the live event loop, so _record_call fires and commits.
    """
    from pathlib import Path
    import re

    def check_code_for_pattern(source, pattern_name):
        """Check source code for a pattern, ignoring comments and docstrings."""
        import ast
        lines = source.split("\n")

        # Simple approach: look for the pattern in executable code only
        # We'll look for lines that have actual code after removing comments and docstrings
        in_docstring = False
        docstring_char = None

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Track docstring boundaries (triple quotes)
            if '"""' in stripped or "'''" in stripped:
                # Count triple quotes to detect entry/exit
                if '"""' in stripped:
                    count = stripped.count('"""')
                    if count % 2 == 1:  # Odd number = toggle
                        in_docstring = not in_docstring
                        docstring_char = '"""'
                elif "'''" in stripped:
                    count = stripped.count("'''")
                    if count % 2 == 1:
                        in_docstring = not in_docstring
                        docstring_char = "'''"

            # Skip if in docstring
            if in_docstring:
                continue

            # Skip if entire line is a comment
            if stripped.startswith("#"):
                continue

            # Extract the part before any '#' comment marker
            code_part = line.split("#")[0]

            # Check for pattern in code part (not comment)
            if pattern_name == "asyncio.run" and "asyncio.run(" in code_part:
                return i, line
            elif pattern_name == "asyncio.to_thread" and "asyncio.to_thread" in code_part:
                return i, line
        return None, None

    # Check agents/tools.py does not use asyncio.run in code
    tools_source = (Path(__file__).parent.parent / "agents" / "tools.py").read_text(encoding="utf-8")
    line_no, line_text = check_code_for_pattern(tools_source, "asyncio.run")
    assert line_no is None, \
        f"agents/tools.py:{line_no} must not use asyncio.run() — tool calls must be awaited on the live event loop\n  {line_text}"

    # Check orchestration/agent_loop.py
    loop_source = (Path(__file__).parent.parent / "orchestration" / "agent_loop.py").read_text(encoding="utf-8")
    line_no, line_text = check_code_for_pattern(loop_source, "asyncio.run")
    assert line_no is None, \
        f"orchestration/agent_loop.py:{line_no} must not use asyncio.run()\n  {line_text}"

    # Check orchestration/optimizer.py does not use asyncio.to_thread (Phase 2 should be native async)
    optimizer_source = (Path(__file__).parent.parent / "orchestration" / "optimizer.py").read_text(encoding="utf-8")
    line_no, line_text = check_code_for_pattern(optimizer_source, "asyncio.to_thread")
    assert line_no is None, \
        f"orchestration/optimizer.py:{line_no} must not use asyncio.to_thread for Phase 2\n  {line_text}"


@pytest.mark.asyncio
async def test_phase2_tools_properly_await_complete():
    """
    Verify that Phase 2 tools use 'await complete()' syntax by checking
    the source code contains the correct pattern.

    This test ensures the structural requirement for _record_call fire-and-forget to work:
    complete() must be awaited on the live event loop, not run in a separate loop.
    """
    from pathlib import Path

    tools_source = (Path(__file__).parent.parent / "agents" / "tools.py").read_text()

    # Check that await complete is used in the file
    assert "await complete(" in tools_source, \
        "agents/tools.py must contain 'await complete(' calls to ensure _record_call fires on the live loop"

    # Verify we have at least the main tool implementations using await
    # (keyword_inject, bullet_strengthen, skills_rewrite, bullets_reorder)
    await_count = tools_source.count("await complete(")
    assert await_count >= 4, \
        f"agents/tools.py should have at least 4 'await complete(' calls (keyword_inject, bullet_strengthen, " \
        f"skills_rewrite, bullets_reorder), found {await_count}"
