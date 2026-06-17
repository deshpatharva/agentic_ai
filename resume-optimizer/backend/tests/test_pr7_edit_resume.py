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
