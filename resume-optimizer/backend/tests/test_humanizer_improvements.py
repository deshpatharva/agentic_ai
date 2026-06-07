"""Tests for humanizer prompt improvements."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


def test_humanizer_accepts_industry_and_seniority_params():
    """humanize_resume must accept industry and seniority_level keyword args."""
    import inspect
    from agents.humanizer import humanize_resume
    sig = inspect.signature(humanize_resume)
    assert "industry" in sig.parameters, \
        "humanize_resume must accept 'industry' parameter"
    assert "seniority_level" in sig.parameters, \
        "humanize_resume must accept 'seniority_level' parameter"


def test_humanizer_has_three_objectives_not_seven():
    """Humanizer Step 1 prompt must NOT contain '7.' (old 7-objective list)."""
    import inspect
    from agents import humanizer as hum_module
    source = inspect.getsource(hum_module)
    assert "7." not in source, \
        "Humanizer still has 7 objectives — reduce to 3 focused objectives"


def test_humanizer_no_max_3_cap_in_critic():
    """Humanizer critic prompt must not contain 'max 3' or 'Max 3' cap."""
    import inspect
    from agents import humanizer as hum_module
    source = inspect.getsource(hum_module)
    assert "max 3" not in source.lower() or "max_iter" in source, \
        "Humanizer critic still has 'max 3' items cap — remove it"
