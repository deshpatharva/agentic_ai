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

    async def fake_complete_with_tools(messages, model, tools, **kwargs):
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


# ── Group 4: apply_edit handler ──────────────────────────────────────────────

import uuid
import pytest_asyncio
from datetime import datetime, timezone


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_user_and_session(context: dict):
    """Insert a User + ChatSession with the given context; return (user, session)."""
    from db.models import User, ChatSession, PlanType
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"edit-{uuid.uuid4().hex[:8]}@test.com",
            password_hash="x",
            plan=PlanType.free,
        )
        db.add(user)
        sess = ChatSession(
            id=uuid.uuid4(),
            user_id=user.id,
            title="t",
            context=context,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(sess)
        await db.commit()
        await db.refresh(user)
        await db.refresh(sess)
        return user, sess


def _fake_scores(values: dict):
    """values: {dim: int} -> full score_combined-style dict."""
    out = {d: {"score": values.get(d, 80)} for d in
           ("ats", "impact", "skills_gap", "readability", "jd_tailoring")}
    out["overall"] = round(sum(values.values()) / len(values)) if values else 80
    return {"text": out, "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}


@pytest.mark.asyncio
async def test_apply_edit_last_result_source_writes_back(db_tables):
    from chat import handoff
    from db.models import ChatSession
    from db.session import AsyncSessionLocal

    ctx = {
        "jd_text": "Python data engineer with Spark.",
        "_optimizer_launched": True,
        "last_result": {
            "sections": {"summary": "Old summary"},
            "optimized_text": "SUMMARY\nOld summary.\n\nEXPERIENCE\n- Built Kafka pipelines.",
            "scores": {"ats": 70, "impact": 65, "skills_gap": 72, "readability": 80},
            "report": {"scores": {"ats": 70, "impact": 65, "skills_gap": 72, "readability": 80}},
        },
    }
    user, sess = await _make_user_and_session(ctx)

    agent_ret = {"text": "SUMMARY\nNew summary.\n\nEXPERIENCE\n- Built Spark pipelines.",
                 "input_tokens": 5, "output_tokens": 5, "cost_usd": 0.0,
                 "iterations": 1, "flagged": []}

    with patch.object(handoff, "run_agent", AsyncMock(return_value=agent_ret)), \
         patch.object(handoff, "score_combined", AsyncMock(return_value=_fake_scores(
             {"ats": 82, "impact": 75, "skills_gap": 80, "readability": 88, "jd_tailoring": 71}))), \
         patch.object(handoff, "analyze_jd", AsyncMock(return_value={"text": {"keywords": ["spark"],
             "seniority_level": "mid", "required_hard_skills": []}, "tokens": {}, "cost_usd": 0.0})), \
         patch.object(handoff, "extract_claims", return_value=None), \
         patch.object(handoff, "_parse_sections", AsyncMock(return_value={"summary": "New summary."})):
        result = await handoff.apply_edit(user, sess, {"instruction": "Replace Kafka with Spark."})

    # returned event payload
    assert result["scores"]["ats"] == 82
    assert result["scores_before"]["ats"] == 70
    assert result["verifier_flagged"] == []
    assert isinstance(result["sections_changed"], list)

    # written back to session context
    async with AsyncSessionLocal() as db:
        row = await db.get(ChatSession, sess.id)
        lr = row.context["last_result"]
        assert lr["optimized_text"] == agent_ret["text"]
        assert lr["sections"] == {"summary": "New summary."}
        assert lr["scores"]["jd_tailoring"] == 71
        assert lr["verifier_flagged"] == []


# ── Group 5: apply_edit — profile source + error paths ───────────────────────

@pytest.mark.asyncio
async def test_apply_edit_profile_source(db_tables):
    """No last_result → edit the saved profile named by profile_id."""
    from chat import handoff
    from db.models import Profile
    from db.session import AsyncSessionLocal

    user, sess = await _make_user_and_session({})  # no jd, no last_result
    async with AsyncSessionLocal() as db:
        prof = Profile(
            id=uuid.uuid4(), user_id=user.id, label="Data Engineer",
            raw_text="SUMMARY\nGeneric summary.\n\nSKILLS\nPython, SQL.",
            sections={"summary": "Generic summary."},
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        db.add(prof)
        await db.commit()
        pid = str(prof.id)

    agent_ret = {"text": "SUMMARY\nTighter summary.\n\nSKILLS\nPython, SQL.",
                 "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0,
                 "iterations": 1, "flagged": []}

    with patch.object(handoff, "run_agent", AsyncMock(return_value=agent_ret)), \
         patch.object(handoff, "score_combined", AsyncMock(return_value=_fake_scores(
             {"ats": 80, "impact": 80, "skills_gap": 80, "readability": 90, "jd_tailoring": 60}))), \
         patch.object(handoff, "extract_claims", return_value=None), \
         patch.object(handoff, "_parse_sections", AsyncMock(return_value={"summary": "Tighter summary."})):
        result = await handoff.apply_edit(user, sess, {"instruction": "Shorten the summary.", "profile_id": pid})

    assert result["scores"]["readability"] == 90
    from db.models import ChatSession
    async with AsyncSessionLocal() as db:
        row = await db.get(ChatSession, sess.id)
        assert row.context["last_result"]["optimized_text"] == agent_ret["text"]


@pytest.mark.asyncio
async def test_apply_edit_no_source_returns_400(db_tables):
    from chat import handoff
    from fastapi import HTTPException
    user, sess = await _make_user_and_session({})
    with pytest.raises(HTTPException) as exc:
        await handoff.apply_edit(user, sess, {"instruction": "Fix it."})
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_apply_edit_blocked_during_active_optimization(db_tables):
    from chat import handoff
    from fastapi import HTTPException
    user, sess = await _make_user_and_session({"_optimizer_launched": True})  # no last_result
    with pytest.raises(HTTPException) as exc:
        await handoff.apply_edit(user, sess, {"instruction": "Fix it."})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_edit_empty_output_returns_422(db_tables):
    from chat import handoff
    from fastapi import HTTPException
    ctx = {"last_result": {"optimized_text": "SUMMARY\nSame text.", "sections": {}, "scores": {}}}
    user, sess = await _make_user_and_session(ctx)
    agent_ret = {"text": "SUMMARY\nSame text.", "flagged": [], "iterations": 1,
                 "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    with patch.object(handoff, "run_agent", AsyncMock(return_value=agent_ret)), \
         patch.object(handoff, "score_combined", AsyncMock(return_value=_fake_scores({"ats": 80}))), \
         patch.object(handoff, "extract_claims", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await handoff.apply_edit(user, sess, {"instruction": "no-op"})
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_apply_edit_fabrication_flagged_still_writes_back(db_tables):
    from chat import handoff
    from db.models import ChatSession
    from db.session import AsyncSessionLocal
    ctx = {"last_result": {"optimized_text": "SUMMARY\nReal text.", "sections": {}, "scores": {"ats": 70}}}
    user, sess = await _make_user_and_session(ctx)
    agent_ret = {"text": "SUMMARY\nEdited text.", "flagged": ["Managed a team of 20"],
                 "iterations": 1, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}
    with patch.object(handoff, "run_agent", AsyncMock(return_value=agent_ret)), \
         patch.object(handoff, "score_combined", AsyncMock(return_value=_fake_scores({"ats": 75}))), \
         patch.object(handoff, "extract_claims", return_value=None), \
         patch.object(handoff, "_parse_sections", AsyncMock(return_value={"summary": "Edited text."})):
        result = await handoff.apply_edit(user, sess, {"instruction": "Add team leadership."})
    assert result["verifier_flagged"] == ["Managed a team of 20"]
    async with AsyncSessionLocal() as db:
        row = await db.get(ChatSession, sess.id)
        assert row.context["last_result"]["verifier_flagged"] == ["Managed a team of 20"]


# ── Group 7: router quota helpers ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_edit_quota_blocks_when_over(db_tables):
    from chat import router
    from db.models import User, PlanType, PlanLimit, DailyUsageCounter
    from db.session import AsyncSessionLocal
    from fastapi import HTTPException
    from datetime import date

    async with AsyncSessionLocal() as db:
        db.add(PlanLimit(plan="free", daily_uploads=2, daily_edits=3,
                         max_stored_resumes=1, job_scraping_enabled=False, price_cents=0))
        user = User(id=uuid.uuid4(), email=f"q-{uuid.uuid4().hex[:8]}@t.com",
                    password_hash="x", plan=PlanType.free)
        db.add(user)
        db.add(DailyUsageCounter(user_id=user.id, date=date.today().isoformat(), runs=0, edits=3))
        await db.commit()
        await db.refresh(user)

    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await router._check_edit_quota(user, db)
        assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_increment_edit_counter(db_tables):
    from chat import router
    from db.models import User, PlanType, DailyUsageCounter
    from db.session import AsyncSessionLocal
    from sqlalchemy import select
    from datetime import date

    async with AsyncSessionLocal() as db:
        user = User(id=uuid.uuid4(), email=f"i-{uuid.uuid4().hex[:8]}@t.com",
                    password_hash="x", plan=PlanType.free)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    async with AsyncSessionLocal() as db:
        await router._increment_edit_counter(str(user.id), db)
        await router._increment_edit_counter(str(user.id), db)

    async with AsyncSessionLocal() as db:
        n = await db.scalar(select(DailyUsageCounter.edits).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == date.today().isoformat()))
        assert n == 2


def test_router_imports_edit_tool_and_apply_edit():
    import inspect
    from chat import router
    src = inspect.getsource(router)
    assert "EDIT_TOOL" in src
    assert "apply_edit" in src
    assert "resume_edited" in src
