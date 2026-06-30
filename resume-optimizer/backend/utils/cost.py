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

    Prefers LiteLLM's call-time cost from response._hidden_params (works for
    providers like groq/gpt-oss where the after-the-fact completion_cost() can't
    re-map the prefix-stripped model name); then completion_cost(); then the
    ProviderCost table; tags 'zero' when none work so the audit column surfaces gaps.
    """
    # LiteLLM computes cost during the call with the full provider-prefixed model
    # name and stashes it here. This populates even when completion_cost() below
    # raises "model isn't mapped" (e.g. groq/openai/gpt-oss-120b).
    hidden = getattr(response, "_hidden_params", None) or {}
    rc = hidden.get("response_cost")
    if rc and rc > 0:
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
