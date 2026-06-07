"""Tests for rewriter prompt improvements."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


def test_rewriter_has_three_priorities_not_eight():
    """Rewriter prompt must use 3 priorities, not 8 objectives."""
    import inspect
    from agents import rewriter as rw_module
    source = inspect.getsource(rw_module)
    assert "8." not in source, \
        "Rewriter still has 8 objectives in its prompt — collapse to 3 priorities"


def test_rewriter_no_hardcoded_600_word_limit():
    """Rewriter must not have a hardcoded '600 words' absolute cap."""
    import inspect
    from agents import rewriter as rw_module
    source = inspect.getsource(rw_module)
    assert "600 words" not in source and "600-word" not in source, \
        "Rewriter has hardcoded 600-word cap — make length dynamic based on input"


def test_rewriter_has_self_check_instruction():
    """Rewriter prompt must include a self-check instruction before returning."""
    import inspect
    from agents import rewriter as rw_module
    source = inspect.getsource(rw_module)
    assert "SELF-CHECK" in source or "self-check" in source.lower(), \
        "Rewriter must include a SELF-CHECK instruction before returning output"
