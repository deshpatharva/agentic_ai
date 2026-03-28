"""
Unified LLM client — single entry point for all model calls.

Agents call:
    from llm import complete
    text = await complete(prompt, MODEL_REWRITER)

    # With Anthropic prompt caching on a large prefix block:
    text = await complete(prompt, MODEL_HUMANIZER, cached_prefix="<large text>")

    # With a pre-created Gemini context cache:
    text = await complete(prompt, MODEL_SCORER, gemini_cache_name="cachedContents/abc123")

To switch a model tomorrow, change config.py only.
To add a new provider, add a branch here only.
"""

import asyncio
import anthropic
from google import genai as google_genai
from google.genai import types as genai_types
from groq import AsyncGroq
from config import ANTHROPIC_API_KEY, GOOGLE_AI_STUDIO_API_KEY, GROQ_API_KEY

# ── Lazy singletons ──────────────────────────────────────────────────────────
_anthropic_client = None
_google_client = None
_groq_client = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def _get_google():
    global _google_client
    if _google_client is None:
        _google_client = google_genai.Client(api_key=GOOGLE_AI_STUDIO_API_KEY)
    return _google_client


def _get_groq():
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq_client


# ── Gemini context cache management ─────────────────────────────────────────

async def create_gemini_cache(content: str, model: str, ttl_seconds: int = 3600) -> str:
    """
    Create a Gemini server-side context cache for large repeated content (e.g. JD text).
    Returns the cache name to pass into complete() via gemini_cache_name.

    Note: Gemini requires >= 32,768 tokens to cache. For shorter content the call
    will succeed but caching may not activate — still safe to call.
    """
    client = _get_google()
    cache = await asyncio.to_thread(
        client.caches.create,
        model=model,
        contents=[genai_types.Content(role="user", parts=[genai_types.Part(text=content)])],
        ttl=f"{ttl_seconds}s",
    )
    return cache.name


async def delete_gemini_cache(cache_name: str) -> None:
    """Delete a Gemini context cache when the pipeline is done."""
    client = _get_google()
    try:
        await asyncio.to_thread(client.caches.delete, name=cache_name)
    except Exception:
        pass  # Best-effort cleanup


# ── Router ───────────────────────────────────────────────────────────────────

async def complete(
    prompt: str,
    model: str,
    max_tokens: int = 8096,
    cached_prefix: str = None,
    gemini_cache_name: str = None,
) -> str:
    """
    Send a prompt to the appropriate provider.

    Args:
        prompt:            The main prompt / instruction text.
        model:             Model name — routes to correct provider automatically.
        max_tokens:        Max output tokens.
        cached_prefix:     (Anthropic only) Large text block to send with
                           cache_control=ephemeral before the main prompt.
                           Saves ~90% of input token cost on cache hits.
        gemini_cache_name: (Gemini only) Cache name from create_gemini_cache().
                           Attaches server-side cached content to the request.
    """
    model_lower = model.lower()

    # ── Anthropic ─────────────────────────────────────────────────────────────
    if model_lower.startswith("claude"):
        client = _get_anthropic()

        if cached_prefix:
            # Split into cached block + instruction block — saves input tokens on repeated calls
            messages = [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": cached_prefix,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }]
        else:
            messages = [{"role": "user", "content": prompt}]

        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )
        return response.content[0].text.strip()

    # ── Google Gemini ─────────────────────────────────────────────────────────
    if model_lower.startswith("gemini"):
        client = _get_google()

        if gemini_cache_name:
            # Use server-side cached content — sends only the new prompt tokens
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    cached_content=gemini_cache_name,
                ),
            )
        else:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=prompt,
            )
        return response.text.strip()

    # ── Groq ──────────────────────────────────────────────────────────────────
    if any(model_lower.startswith(p) for p in ("llama", "mixtral", "gemma", "qwen", "deepseek")):
        client = _get_groq()
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()

    raise ValueError(
        f"Unknown model '{model}'. Add routing for this provider in llm.py."
    )
