"""
Unified LLM client — single entry point for all model calls.

Agents call:
    from llm import complete
    text = await complete(prompt, MODEL_REWRITER)

To switch a model tomorrow, change config.py only.
To add a new provider (OpenAI, Mistral, etc.), add a branch here only.
"""

import asyncio
import anthropic
from google import genai as google_genai
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

async def complete(prompt: str, model: str, max_tokens: int = 8096) -> str:
    """
    Send a prompt to the appropriate provider based on model name prefix.
    Returns the response text as a plain string.

    Routing:
      claude-*                          → Anthropic
      gemini-*                          → Google (google-genai SDK)
      llama-* / mixtral-* / gemma-* /
      qwen-* / deepseek-*               → Groq
    """
    model_lower = model.lower()

    # ── Anthropic ────────────────────────────────────────────────────────────
    if model_lower.startswith("claude"):
        client = _get_anthropic()
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    # ── Google Gemini (new google-genai SDK) ──────────────────────────────────
    if model_lower.startswith("gemini"):
        client = _get_google()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=prompt,
        )
        return response.text.strip()

    # ── Groq ─────────────────────────────────────────────────────────────────
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
