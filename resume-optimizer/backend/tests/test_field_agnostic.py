"""Keyword injection prompt is field-agnostic — not limited to tech roles."""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("BOOTSTRAP_SECRET", "x" * 32)


def test_keyword_prompt_is_field_agnostic():
    """optimizer_agent keyword-inject prompt must not contain tech-specific vocabulary."""
    import agents.optimizer_agent as oa, inspect
    src = inspect.getsource(oa)
    assert "tools, languages, frameworks, platforms" not in src, \
        "Remove tech-specific 'tools, languages, frameworks, platforms' from keyword-inject prompt"
    assert "recruiting, talent acquisition" not in src, \
        "Remove tech-specific HR/finance rejection examples from keyword-inject prompt"


def test_rewriter_keyword_rule_is_field_agnostic():
    """rewriter PRIORITY 1 must not contain tech-specific vocabulary."""
    import agents.rewriter as rw, inspect
    src = inspect.getsource(rw)
    assert "tools, languages, frameworks, platforms" not in src, \
        "Remove tech-specific vocabulary from rewriter keyword rule"
    assert "recruiting, talent acquisition" not in src, \
        "Remove tech-specific HR/finance rejection from rewriter keyword rule"
