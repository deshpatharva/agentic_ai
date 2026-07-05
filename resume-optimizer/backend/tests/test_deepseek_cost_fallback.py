"""
DeepSeek cost-fallback coverage.

resolve_cost() prefers LiteLLM's native per-call cost and only reads the
ProviderCost table when LiteLLM can't price a call. deepseek/deepseek-v4-pro (the
optimizer's strategist, and the priciest model) has a custom name LiteLLM may not
map, so it must have a configurable fallback — otherwise those calls record $0.
"""

import inspect
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")


class _NoNativeCost:
    """Response whose LiteLLM native cost is unavailable, forcing the table fallback."""
    _hidden_params: dict = {}


def test_deepseek_uses_provider_table_when_litellm_cannot_price():
    from utils.cost import resolve_cost
    rates = {"deepseek": (0.28, 1.10)}
    cost, source = resolve_cost(_NoNativeCost(), "deepseek/deepseek-v4-pro", 1_000_000, 1_000_000, rates)
    assert source == "provider_table"
    assert abs(cost - (0.28 + 1.10)) < 1e-9, cost


def test_deepseek_without_rate_records_zero_source():
    """Documents the pre-fix behaviour: no deepseek rate → cost_source 'zero'."""
    from utils.cost import resolve_cost
    cost, source = resolve_cost(_NoNativeCost(), "deepseek/deepseek-v4-pro", 1000, 1000, {})
    assert source == "zero"
    assert cost == 0.0


def test_init_db_seeds_deepseek_fallback():
    from db import session as db_session
    src = inspect.getsource(db_session.init_db)
    assert '"deepseek"' in src or "'deepseek'" in src, "init_db must seed a deepseek provider_costs row"


def test_admin_allows_deepseek_provider():
    from admin import router as admin_router
    src = inspect.getsource(admin_router.create_provider_cost)
    assert "deepseek" in src, "create_provider_cost must accept the deepseek provider"
