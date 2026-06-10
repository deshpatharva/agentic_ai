"""
Unified LLM client — single entry point for all model calls via LiteLLM.

Agents call:
    from llm import complete
    result = await complete(prompt, MODEL_REWRITER)
    text = result["text"]
    input_tokens = result["input_tokens"]
    output_tokens = result["output_tokens"]

    # With Anthropic prompt caching on a large prefix block:
    result = await complete(prompt, MODEL_HUMANIZER, cached_prefix="<large text>")

Model names use LiteLLM provider prefixes (e.g. "gemini/...", "anthropic/...", "groq/...").
To switch a model, change config.py only. To add a provider, no code change needed.
"""

import litellm

litellm.drop_params = True  # silently ignore unsupported provider params


async def complete(
    prompt: str,
    model: str,
    cached_prefix: str = None,
) -> dict:
    """
    Send a prompt to the appropriate provider via LiteLLM.

    Args:
        prompt:        The main prompt / instruction text.
        model:         LiteLLM model name with provider prefix (e.g. "gemini/gemini-2.5-flash-lite").
        cached_prefix: (Anthropic only) Large text block sent with cache_control=ephemeral
                       before the main prompt. Saves ~90% of input token cost on cache hits.

    Returns:
        dict with keys:
            - text (str): Generated response text
            - input_tokens (int): Input token count
            - output_tokens (int): Output token count
    """
    if cached_prefix and model.startswith("anthropic/"):
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": cached_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": prompt},
            ],
        }]
    else:
        messages = [{"role": "user", "content": prompt}]

    response = await litellm.acompletion(
        model=model,
        messages=messages,
    )

    cost_usd = getattr(response, "_hidden_params", {}).get("response_cost") or 0.0

    return {
        "text": response.choices[0].message.content.strip(),
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "cost_usd": float(cost_usd),
    }
