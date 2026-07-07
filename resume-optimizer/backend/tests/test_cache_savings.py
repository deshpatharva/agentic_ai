"""Cache savings must be priced per model from LiteLLM's pricing map — the same
source resolve_cost() trusts — with DEFAULT_PROVIDER_RATES as fallback only
(deep-review finding 10; hardcoded $0.30/1M x 75% was up to 10x off)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")


def test_cache_rates_prefers_litellm(monkeypatch):
    import utils.cost as cost
    monkeypatch.setattr(
        cost.litellm, "get_model_info",
        lambda m: {"input_cost_per_token": 3e-06, "cache_read_input_token_cost": 3e-07},
    )
    inp, cached = cost.cache_rates("anthropic/some-model")
    assert inp == 3e-06
    assert cached == 3e-07


def test_cache_rates_defaults_cached_fraction_when_unpublished(monkeypatch):
    import utils.cost as cost
    monkeypatch.setattr(
        cost.litellm, "get_model_info",
        lambda m: {"input_cost_per_token": 4e-06},  # no cache_read rate published
    )
    inp, cached = cost.cache_rates("groq/some-model")
    assert inp == 4e-06
    assert cached == 4e-06 * 0.25


def test_cache_rates_falls_back_to_provider_table(monkeypatch):
    import utils.cost as cost

    def _unmapped(m):
        raise ValueError("model isn't mapped")

    monkeypatch.setattr(cost.litellm, "get_model_info", _unmapped)
    inp, cached = cost.cache_rates("deepseek/unmapped-model")
    expected_inp = cost.DEFAULT_PROVIDER_RATES["deepseek"][0] / 1_000_000
    assert inp == expected_inp
    assert cached == expected_inp * 0.25


def test_estimate_cache_savings_sums_per_model(monkeypatch):
    import utils.cost as cost
    rates = {"m1": (2e-06, 5e-07), "m2": (1e-06, 2.5e-07)}
    monkeypatch.setattr(cost, "cache_rates", lambda m: rates[m])
    got = cost.estimate_cache_savings([("m1", 1_000_000), ("m2", 2_000_000), ("m3", 0)])
    # m1: 1M * 1.5e-06 = 1.5 ; m2: 2M * 0.75e-06 = 1.5 ; m3 skipped (0 tokens)
    assert abs(got - 3.0) < 1e-9
