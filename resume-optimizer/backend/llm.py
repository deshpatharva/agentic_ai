"""
Unified LLM client — single entry point for all model calls.

Agents call:
    from llm import complete
    result = await complete(prompt, MODEL_REWRITER)
    text = result["text"]
    input_tokens = result["input_tokens"]
    output_tokens = result["output_tokens"]

    # With Anthropic prompt caching on a large prefix block:
    result = await complete(prompt, MODEL_HUMANIZER, cached_prefix="<large text>")

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


# ── Router ───────────────────────────────────────────────────────────────────

async def complete(
    prompt: str,
    model: str,
    max_tokens: int = 8096,
    cached_prefix: str = None,
) -> dict:
    """
    Send a prompt to the appropriate provider.

    Args:
        prompt:        The main prompt / instruction text.
        model:         Model name — routes to correct provider automatically.
        max_tokens:    Max output tokens.
        cached_prefix: (Anthropic only) Large text block to send with
                       cache_control=ephemeral before the main prompt.
                       Saves ~90% of input token cost on cache hits.

    Returns:
        dict with keys:
            - text (str): Generated response text
            - input_tokens (int): Input token count
            - output_tokens (int): Output token count
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
        return {
            "text": response.content[0].text.strip(),
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

    # ── Google Gemini ─────────────────────────────────────────────────────────
    if model_lower.startswith("gemini"):
        client = _get_google()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=prompt,
        )
        return {
            "text": response.text.strip(),
            "input_tokens": 0,  # Google SDK doesn't expose token counts
            "output_tokens": 0,
        }

    # ── Groq ──────────────────────────────────────────────────────────────────
    if any(model_lower.startswith(p) for p in ("llama", "mixtral", "gemma", "qwen", "deepseek")):
        client = _get_groq()
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return {
            "text": response.choices[0].message.content.strip(),
            "input_tokens": response.usage.prompt_tokens,  # Groq uses prompt_tokens
            "output_tokens": response.usage.completion_tokens,  # Groq uses completion_tokens
        }

    raise ValueError(
        f"Unknown model '{model}'. Add routing for this provider in llm.py."
    )
