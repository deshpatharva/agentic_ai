"""Tests for optimizer threshold, list caps, and agent definition fixes."""
import os, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest
import inspect


def test_optimizer_threshold_constant_defined():
    """_WORK_THRESHOLD must be defined as max(75, SCORE_TARGET - 10)."""
    from orchestration import optimizer as opt_module
    from config import SCORE_TARGET
    source = inspect.getsource(opt_module)
    assert "_WORK_THRESHOLD" in source, "_WORK_THRESHOLD constant not defined in optimizer.py"
    expected = max(75, SCORE_TARGET - 10)
    assert str(expected) in source or "SCORE_TARGET - 10" in source, \
        f"_WORK_THRESHOLD must equal max(75, SCORE_TARGET-10) = {expected}"


def test_optimizer_list_caps_increased():
    """missing_keywords, weak_bullets, missing_skills caps must be 15/8/15."""
    from orchestration import optimizer as opt_module
    source = inspect.getsource(opt_module)
    assert "missing_keywords[:8]" not in source, \
        "missing_keywords still capped at 8 — increase to 15"
    assert "weak_bullets[:4]" not in source, \
        "weak_bullets still capped at 4 — increase to 8"
    assert "missing_skills[:8]" not in source, \
        "missing_skills still capped at 8 — increase to 15"


def test_section_name_uses_worst_section():
    """section_name must come from readability.worst_section, not be hardcoded 'summary'."""
    from orchestration import optimizer as opt_module
    source = inspect.getsource(opt_module)
    assert 'section_name = "summary"' not in source, \
        "section_name is hardcoded to 'summary' — use worst_section from scorer"
    assert "worst_section" in source, \
        "worst_section not referenced in optimizer.py"


def test_optimizer_agent_max_iter_is_six():
    """AGENT_MAX_ITER must be 6."""
    from agents import optimizer_agent
    source = inspect.getsource(optimizer_agent)
    match = re.search(r"AGENT_MAX_ITER\s*=\s*(\d+)", source)
    assert match, "AGENT_MAX_ITER not found in optimizer_agent.py"
    assert int(match.group(1)) == 6, f"AGENT_MAX_ITER should be 6, got {match.group(1)}"
