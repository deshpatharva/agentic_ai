"""Cost resolution: LiteLLM-native first, ProviderCost table fallback."""

import litellm


def resolve_cost(
    response,
    model: str,
    in_tok: int,
    out_tok: int,
    rates: dict[str, tuple[float, float]],
) -> tuple[float, str]:
    """Return (cost_usd, source).

    Tries litellm.completion_cost first; falls back to the ProviderCost table
    rates dict; tags 'zero' when neither works so the audit column surfaces gaps.
    """
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
