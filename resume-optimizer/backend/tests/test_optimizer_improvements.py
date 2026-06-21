"""Tests for optimizer threshold, list caps, and agent definition fixes."""
import os, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

_BACKEND = Path(__file__).parent.parent


def test_optimizer_list_caps_increased():
    """missing_keywords, weak_bullets, missing_skills caps must be 15/8/15."""
    source = (_BACKEND / "orchestration" / "optimizer.py").read_text(encoding="utf-8")
    assert "missing_keywords[:8]" not in source, \
        "missing_keywords still capped at 8 — increase to 15"
    assert "weak_bullets[:4]" not in source, \
        "weak_bullets still capped at 4 — increase to 8"
    assert "missing_skills[:8]" not in source, \
        "missing_skills still capped at 8 — increase to 15"


def test_section_name_uses_worst_section():
    """section_name must come from readability.worst_section, not be hardcoded 'summary'.
    With T2.3, the prompt-building logic moved to orchestration/agent_loop.py, so we
    check the combined source of optimizer.py + agent_loop.py.
    """
    optimizer_src = (_BACKEND / "orchestration" / "optimizer.py").read_text(encoding="utf-8")
    agent_loop_src = (_BACKEND / "orchestration" / "agent_loop.py").read_text(encoding="utf-8")
    combined = optimizer_src + agent_loop_src
    assert 'section_name = "summary"' not in combined, \
        "section_name is hardcoded to 'summary' — use worst_section from scorer"
    assert "worst_section" in combined, \
        "worst_section not referenced in optimizer.py or agent_loop.py"


def test_agent_max_iter_comes_from_config():
    """AGENT_MAX_ITER must be defined in config.py (the single source of truth)."""
    import config
    assert hasattr(config, "AGENT_MAX_ITER"), "AGENT_MAX_ITER must be in config.py"
    assert isinstance(config.AGENT_MAX_ITER, int) and config.AGENT_MAX_ITER > 0
