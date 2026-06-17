"""
Tests for PR-7 edit_resume tool.

Mocking strategy:
  - Source-inspection tests check module text (schema/prompt presence).
  - apply_edit tests patch chat.handoff.run_agent, .score_combined, .analyze_jd,
    .extract_claims, ._parse_sections so no real LLM/API is hit.
  - Quota tests use SQLite via db.session.engine.

pytest-asyncio runs in auto mode (pytest.ini).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_pr7.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


# ── Group 1: edit-quota DB columns ───────────────────────────────────────────

def test_plan_limit_has_daily_edits_column():
    from db.models import PlanLimit
    assert hasattr(PlanLimit, "daily_edits")


def test_daily_usage_counter_has_edits_column():
    from db.models import DailyUsageCounter
    assert hasattr(DailyUsageCounter, "edits")


def test_seed_includes_daily_edits():
    """init_db seeding must set daily_edits on every seeded plan."""
    import inspect
    from db import session as db_session
    src = inspect.getsource(db_session.init_db)
    assert "daily_edits" in src


# ── Group 2: run_agent instruction injection ─────────────────────────────────

from unittest.mock import AsyncMock, patch
from types import SimpleNamespace


def _fake_msg(content="done", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


@pytest.mark.asyncio
async def test_run_agent_injects_user_instruction_and_returns_flagged():
    from orchestration import agent_loop
    from agents.tools import ResumeState
    from agents.fact_extractor import ClaimsLedger

    state = ResumeState(sections={"summary": "Engineer.", "experience": "- Did things."})
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(), raw_bullets=tuple(),
        job_titles=frozenset(), degrees=frozenset(), date_ranges=frozenset(),
    )
    scores = {d: {"score": 95} for d in ("ats", "impact", "skills_gap", "readability", "jd_tailoring")}
    scores["overall"] = 95

    captured = {}

    async def fake_complete_with_tools(messages, model, tools):
        captured["system"] = messages[0]["content"]
        return {"message": _fake_msg(content="done", tool_calls=None),
                "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    fake_guard = SimpleNamespace(gaps=["Managed team of 20 (unsupported)"], text="cleaned text")
    fake_score = {"text": scores, "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

    with patch.object(agent_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(agent_loop, "fabrication_guard", return_value=fake_guard), \
         patch.object(agent_loop, "score_combined", AsyncMock(return_value=fake_score)):
        result = await agent_loop.run_agent(
            state=state, scores=scores, jd_text="", jd_keywords=[], ledger=ledger,
            original_resume="Engineer.\n- Did things.",
            user_instruction="Remove the Kafka bullet and shorten the summary.",
            max_reflections=2,
        )

    assert "Remove the Kafka bullet" in captured["system"]
    assert result["flagged"] == ["Managed team of 20 (unsupported)"]
    assert result["text"] == "cleaned text"


# ── Group 3: edit_resume tool schema ─────────────────────────────────────────

def test_edit_tool_in_tools_list():
    from chat.tools import TOOLS, EDIT_TOOL
    names = [t["function"]["name"] for t in TOOLS]
    assert EDIT_TOOL == "edit_resume"
    assert "edit_resume" in names


def test_edit_tool_schema():
    from chat.tools import TOOLS
    fn = next(t["function"] for t in TOOLS if t["function"]["name"] == "edit_resume")
    props = fn["parameters"]["properties"]
    assert "instruction" in props
    assert "profile_id" in props
    assert fn["parameters"]["required"] == ["instruction"]


# ── Group 6: co-pilot prompt guidance ────────────────────────────────────────

def test_system_prompt_has_edit_guidance():
    import inspect
    from chat import agent
    src = inspect.getsource(agent)
    assert "edit_resume" in src
    assert "RESUME EDITS" in src
