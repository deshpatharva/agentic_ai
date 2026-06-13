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

import asyncio
import logging
from typing import AsyncIterator

import litellm

litellm.drop_params = True  # silently ignore unsupported provider params

_logger = logging.getLogger(__name__)

# A hung provider call would otherwise stall a pipeline run until the
# 15-minute stuck-job reaper kills it.
_CALL_TIMEOUT_S = 120
_TRANSIENT = (litellm.exceptions.Timeout, litellm.exceptions.APIConnectionError,
              litellm.exceptions.InternalServerError, asyncio.TimeoutError)


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
        cached_prefix: Large text block sent with cache_control=ephemeral before the main
                       prompt. Saves on input token cost on cache hits. Supported by
                       Anthropic and Gemini 2.5+; silently ignored by other providers
                       (drop_params=True).

    Returns:
        dict with keys:
            - text (str): Generated response text
            - input_tokens (int): Input token count
            - output_tokens (int): Output token count
    """
    if cached_prefix:
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": cached_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": prompt},
            ],
        }]
    else:
        messages = [{"role": "user", "content": prompt}]

    # One bounded retry on transient failures (timeout / connection / 5xx).
    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            timeout=_CALL_TIMEOUT_S,
        )
    except _TRANSIENT as exc:
        _logger.warning("LLM call to %s failed transiently (%s) — retrying once", model, type(exc).__name__)
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            timeout=_CALL_TIMEOUT_S,
        )

    cost_usd = getattr(response, "_hidden_params", {}).get("response_cost") or 0.0

    return {
        "text": response.choices[0].message.content.strip(),
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "cost_usd": float(cost_usd),
    }


async def stream_chat(messages: list[dict], model: str) -> AsyncIterator[dict]:
    """Stream a multi-turn chat completion token-by-token via LiteLLM.

    Yields dicts:
      {"type": "token", "text": "<delta>"}            # 0..N times
      {"type": "usage", "input_tokens": int,          # exactly once, last
                        "output_tokens": int, "cost_usd": float}

    `messages` is [{role, content}, ...] — system + sliding window.
    """
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        timeout=_CALL_TIMEOUT_S,
        stream=True,
        stream_options={"include_usage": True},
    )

    in_tok = out_tok = 0
    cost = 0.0
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield {"type": "token", "text": delta}
        usage = getattr(chunk, "usage", None)
        if usage:
            in_tok = getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "completion_tokens", 0) or 0
            cost = getattr(chunk, "_hidden_params", {}).get("response_cost") or 0.0

    yield {"type": "usage", "input_tokens": in_tok, "output_tokens": out_tok,
           "cost_usd": float(cost)}
