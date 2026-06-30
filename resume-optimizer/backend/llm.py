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
import os
import time
from datetime import datetime, timezone
from typing import AsyncIterator

import litellm

litellm.drop_params = True  # silently ignore unsupported provider params

_logger = logging.getLogger(__name__)

# DeepSeek V4 thinking effort. LiteLLM's DeepSeek config discards reasoning_effort
# and always sends thinking:{"type":"enabled"} (litellm #27439), so we pass the
# value raw via extra_body, which LiteLLM forwards untouched. Remove the extra_body
# hack once PR #28702 lands and pass reasoning_effort natively.
_DEEPSEEK_REASONING_EFFORT = os.environ.get("DEEPSEEK_REASONING_EFFORT", "max")


def _deepseek_extra_body(model: str) -> dict | None:
    if _provider(model) != "deepseek":
        return None
    return {"reasoning_effort": _DEEPSEEK_REASONING_EFFORT, "thinking": {"type": "enabled"}}

# A hung provider call would otherwise stall a pipeline run until the
# 15-minute stuck-job reaper kills it.
_CALL_TIMEOUT_S = 120
_TRANSIENT = (litellm.exceptions.Timeout, litellm.exceptions.APIConnectionError,
              litellm.exceptions.InternalServerError, asyncio.TimeoutError)


def _provider(model: str) -> str:
    return model.split("/", 1)[0]


async def _record_call(row_kwargs: dict) -> None:
    """Fire-and-forget: write one LlmCallLog row in a fresh session."""
    try:
        from db.models import LlmCallLog
        from db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            db.add(LlmCallLog(**row_kwargs))
            await db.commit()
    except Exception:
        _logger.exception("Failed to write LlmCallLog row")


async def _provider_rates() -> dict[str, tuple[float, float]]:
    """Return {provider: (in_rate, out_rate)} from the ProviderCost table (cached 5 min)."""
    now = time.monotonic()
    if now - _rates_cache["ts"] < 300 and _rates_cache["data"]:
        return _rates_cache["data"]
    try:
        from db.models import ProviderCost
        from db.session import AsyncSessionLocal
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(ProviderCost).where(ProviderCost.active.is_(True))
            )).scalars().all()
        data = {r.provider: (r.input_cost_per_1m_tokens, r.output_cost_per_1m_tokens)
                for r in rows}
        _rates_cache["data"] = data
        _rates_cache["ts"] = now
        return data
    except Exception:
        return _rates_cache.get("data") or {}


_rates_cache: dict = {"ts": 0.0, "data": {}}


async def complete(
    prompt: str,
    model: str,
    cached_prefix: str = None,
    response_format: dict | None = None,
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
            - cost_usd (float): Resolved cost
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

    t0 = time.perf_counter()

    call_kwargs: dict = {"model": model, "messages": messages, "timeout": _CALL_TIMEOUT_S}
    if response_format is not None:
        provider = _provider(model)
        if provider in ("gemini", "vertex_ai"):
            call_kwargs["response_format"] = response_format
        elif provider in ("groq", "deepseek"):
            # Both support json_object but not json_schema.
            if response_format.get("type") == "json_schema":
                call_kwargs["response_format"] = {"type": "json_object"}
            else:
                call_kwargs["response_format"] = response_format
        # else: omit entirely — response_format unsupported by this provider

    extra_body = _deepseek_extra_body(model)
    if extra_body:
        call_kwargs["extra_body"] = extra_body

    # One bounded retry on transient failures (timeout / connection / 5xx).
    try:
        response = await litellm.acompletion(**call_kwargs)
    except _TRANSIENT as exc:
        _logger.warning("LLM call to %s failed transiently (%s) — retrying once", model, type(exc).__name__)
        response = await litellm.acompletion(**call_kwargs)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    in_tok  = response.usage.prompt_tokens
    out_tok = response.usage.completion_tokens

    from utils.cost import resolve_cost
    rates = await _provider_rates()
    cost_usd, cost_source = resolve_cost(response, model, in_tok, out_tok, rates)

    from observability.trace import current_trace, current_call_kind
    asyncio.create_task(_record_call({
        "trace_id":      current_trace() or None,
        "model":         model,
        "provider":      _provider(model),
        "call_kind":     current_call_kind() or None,
        "input_tokens":  in_tok,
        "output_tokens": out_tok,
        "cost_usd":      cost_usd,
        "cost_source":   cost_source,
        "latency_ms":    latency_ms,
        "created_at":    datetime.now(timezone.utc),
    }))

    return {
        "text":          response.choices[0].message.content.strip(),
        "input_tokens":  in_tok,
        "output_tokens": out_tok,
        "cost_usd":      cost_usd,
    }


async def complete_with_tools(
    messages: list[dict],
    model: str,
    tools: list[dict],
) -> dict:
    """Multi-turn completion with native tool-calling (non-streaming).

    Returns:
        dict with:
          - message:       the raw assistant message (has .content and .tool_calls)
          - input_tokens / output_tokens / cost_usd

    Tool calls come back as structured, validated arguments — never parsed from
    free text — eliminating control-token leakage. Records an LlmCallLog row via
    the same fire-and-forget path as complete()/stream_chat().
    """
    tool_kwargs: dict = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "timeout": _CALL_TIMEOUT_S,
    }
    extra_body = _deepseek_extra_body(model)
    if extra_body:
        tool_kwargs["extra_body"] = extra_body

    t0 = time.perf_counter()
    try:
        response = await litellm.acompletion(**tool_kwargs)
    except _TRANSIENT as exc:
        _logger.warning("tool-calling chat to %s failed transiently (%s) — retrying once",
                        model, type(exc).__name__)
        response = await litellm.acompletion(**tool_kwargs)
    except Exception as exc:
        # Some providers/models reject or mishandle the tools/tool_choice params.
        # Degrade gracefully to a plain completion so the user still gets a reply
        # (the action just won't fire on this turn).
        _logger.warning("tool-calling chat to %s failed (%s) — retrying WITHOUT tools",
                        model, type(exc).__name__)
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            timeout=_CALL_TIMEOUT_S,
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", 0) or 0
    out_tok = getattr(usage, "completion_tokens", 0) or 0

    from utils.cost import resolve_cost
    rates = await _provider_rates()
    cost_usd, cost_source = resolve_cost(response, model, in_tok, out_tok, rates)

    from observability.trace import current_trace, current_call_kind
    asyncio.create_task(_record_call({
        "trace_id":      current_trace() or None,
        "model":         model,
        "provider":      _provider(model),
        "call_kind":     current_call_kind() or None,
        "input_tokens":  in_tok,
        "output_tokens": out_tok,
        "cost_usd":      cost_usd,
        "cost_source":   cost_source,
        "latency_ms":    latency_ms,
        "created_at":    datetime.now(timezone.utc),
    }))

    return {
        "message":       response.choices[0].message,
        "input_tokens":  in_tok,
        "output_tokens": out_tok,
        "cost_usd":      float(cost_usd),
    }


async def stream_chat(messages: list[dict], model: str) -> AsyncIterator[dict]:
    """Stream a multi-turn chat completion token-by-token via LiteLLM.

    Yields dicts:
      {"type": "token", "text": "<delta>"}            # 0..N times
      {"type": "usage", "input_tokens": int,          # exactly once, last
                        "output_tokens": int, "cost_usd": float}

    `messages` is [{role, content}, ...] — system + sliding window.
    """
    t0 = time.perf_counter()
    ttft_ms: int | None = None

    response = await litellm.acompletion(
        model=model,
        messages=messages,
        timeout=_CALL_TIMEOUT_S,
        stream=True,
        stream_options={"include_usage": True},
    )

    in_tok = out_tok = 0
    last_response = None
    async for chunk in response:
        last_response = chunk
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            if ttft_ms is None:
                ttft_ms = int((time.perf_counter() - t0) * 1000)
            yield {"type": "token", "text": delta}
        usage = getattr(chunk, "usage", None)
        if usage:
            in_tok  = getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "completion_tokens", 0) or 0

    latency_ms = int((time.perf_counter() - t0) * 1000)

    from utils.cost import resolve_cost
    rates = await _provider_rates()
    cost_usd, cost_source = resolve_cost(last_response, model, in_tok, out_tok, rates)

    from observability.trace import current_trace, current_call_kind
    asyncio.create_task(_record_call({
        "trace_id":      current_trace() or None,
        "model":         model,
        "provider":      _provider(model),
        "call_kind":     current_call_kind() or None,
        "input_tokens":  in_tok,
        "output_tokens": out_tok,
        "cost_usd":      cost_usd,
        "cost_source":   cost_source,
        "latency_ms":    latency_ms,
        "ttft_ms":       ttft_ms,
        "created_at":    datetime.now(timezone.utc),
    }))

    yield {"type": "usage", "input_tokens": in_tok, "output_tokens": out_tok,
           "cost_usd": float(cost_usd)}
