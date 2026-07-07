"""Cost resolution: LiteLLM-native first, ProviderCost table fallback."""

import litellm

# Single source of truth for the providers we price and their fallback rates,
# in USD per 1,000,000 tokens as (input, output). resolve_cost() only reaches
# these when LiteLLM can't natively price a call. Admin validation (admin.router)
# and the init_db fallback seed both derive from this, so adding a provider is a
# one-line change here rather than four edits that can drift.
# Refreshed 2026-07-06 from litellm's pricing map — fallback only; resolve_cost()/cache_rates() prefer LiteLLM.
DEFAULT_PROVIDER_RATES: dict[str, tuple[float, float]] = {
    "anthropic": (3.0, 15.0),    # anthropic/claude-sonnet-4-6 (no config.py MODEL_* uses anthropic today)
    "google": (0.25, 1.5),       # gemini/gemini-3.1-flash-lite — predominant google model (10 of 11 MODEL_* consts)
    "groq": (0.05, 0.08),        # groq/llama-3.1-8b-instant — MODEL_CRITIC/MODEL_VERIFIER/MODEL_CRITIQUE
    "deepseek": (0.435, 0.87),   # deepseek/deepseek-v4-pro — MODEL_OPTIMIZER
}

ALLOWED_PROVIDERS: tuple[str, ...] = tuple(DEFAULT_PROVIDER_RATES)


def resolve_cost(
    response,
    model: str,
    in_tok: int,
    out_tok: int,
    rates: dict[str, tuple[float, float]],
) -> tuple[float, str]:
    """Return (cost_usd, source).

    Prefers LiteLLM's call-time cost from response._hidden_params (works for
    providers like groq/gpt-oss where the after-the-fact completion_cost() can't
    re-map the prefix-stripped model name); then completion_cost(); then the
    ProviderCost table; tags 'zero' when none work so the audit column surfaces gaps.
    """
    # LiteLLM computes cost during the call with the full provider-prefixed model
    # name and stashes it here. This populates even when completion_cost() below
    # raises "model isn't mapped" (e.g. groq/openai/gpt-oss-120b).
    hidden = getattr(response, "_hidden_params", None)
    rc = hidden.get("response_cost") if isinstance(hidden, dict) else None
    if isinstance(rc, (int, float)) and rc > 0:
        return float(rc), "litellm_hidden"

    try:
        c = litellm.completion_cost(completion_response=response)
        if c and c > 0:
            return float(c), "litellm"
    except Exception:
        pass

    provider = model.split("/", 1)[0]
    provider = {"gemini": "google"}.get(provider, provider)
    if provider in rates:
        in_rate, out_rate = rates[provider]
        cost = (in_tok / 1_000_000) * in_rate + (out_tok / 1_000_000) * out_rate
        return cost, "provider_table"

    return 0.0, "zero"


_FALLBACK_CACHED_FRACTION = 0.25


def cache_rates(model: str) -> tuple[float, float]:
    """(input_cost_per_token, cache_read_cost_per_token) for a model, in USD/token.

    LiteLLM's bundled pricing map is primary — the same source resolve_cost()
    trusts at call time, updated with the library instead of hand-maintained.
    Falls back to DEFAULT_PROVIDER_RATES when LiteLLM has no mapping, assuming
    cache reads at 25% of input when no rate is published.
    """
    try:
        info = litellm.get_model_info(model)
        inp = float(info.get("input_cost_per_token") or 0.0)
        if inp > 0:
            cached = float(info.get("cache_read_input_token_cost") or 0.0)
            return inp, cached if cached > 0 else inp * _FALLBACK_CACHED_FRACTION
    except Exception:
        pass
    provider = model.split("/", 1)[0]
    provider = {"gemini": "google"}.get(provider, provider)
    in_per_1m = DEFAULT_PROVIDER_RATES.get(provider, (0.0, 0.0))[0]
    inp = in_per_1m / 1_000_000
    return inp, inp * _FALLBACK_CACHED_FRACTION


def estimate_cache_savings(model_cached_tokens) -> float:
    """USD saved by cache reads: cached_tokens x (input_rate - cache_read_rate),
    summed per model. model_cached_tokens: iterable of (model, cached_token_count)."""
    total = 0.0
    for model, cached_tok in model_cached_tokens:
        if not cached_tok:
            continue
        inp, cached = cache_rates(model)
        total += cached_tok * (inp - cached)
    return total
