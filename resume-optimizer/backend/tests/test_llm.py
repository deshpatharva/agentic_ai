"""Tests for the LiteLLM-based unified LLM client.

All tests mock litellm.acompletion — no real API calls.
Failures before migration: model prefix routing, Gemini token counts.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_litellm_response(text: str, input_tokens: int, output_tokens: int):
    """Build a minimal mock that matches the LiteLLM response shape."""
    response = MagicMock()
    response.choices[0].message.content = text
    response.usage.prompt_tokens = input_tokens
    response.usage.completion_tokens = output_tokens
    return response


@pytest.mark.asyncio
async def test_complete_returns_required_keys():
    """complete() always returns text, input_tokens, and output_tokens."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    fake = _make_litellm_response("hello", 10, 5)
    with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
        from llm import complete
        result = await complete("say hello", "gemini/gemini-2.5-flash-lite")

    assert "text" in result
    assert "input_tokens" in result
    assert "output_tokens" in result


@pytest.mark.asyncio
async def test_gemini_returns_actual_token_counts():
    """Gemini calls return real token counts, not zero."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    fake = _make_litellm_response("scored resume", input_tokens=200, output_tokens=80)
    with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
        from llm import complete
        result = await complete("score this resume", "gemini/gemini-2.5-flash-lite")

    assert result["input_tokens"] == 200
    assert result["output_tokens"] == 80


@pytest.mark.asyncio
async def test_anthropic_model_routes_correctly():
    """claude/ prefixed model passes the model name through to litellm.acompletion."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    fake = _make_litellm_response("rewritten", 100, 50)
    mock_acompletion = AsyncMock(return_value=fake)
    with patch("litellm.acompletion", new=mock_acompletion):
        from llm import complete
        await complete("rewrite this", "anthropic/claude-sonnet-4-6")

    call_kwargs = mock_acompletion.call_args
    assert call_kwargs.kwargs["model"] == "anthropic/claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_groq_model_routes_correctly():
    """groq/ prefixed model passes the model name through to litellm.acompletion."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    fake = _make_litellm_response("feedback json", 50, 20)
    mock_acompletion = AsyncMock(return_value=fake)
    with patch("litellm.acompletion", new=mock_acompletion):
        from llm import complete
        await complete("review this", "groq/llama-3.1-8b-instant")

    call_kwargs = mock_acompletion.call_args
    assert call_kwargs.kwargs["model"] == "groq/llama-3.1-8b-instant"


@pytest.mark.asyncio
async def test_cached_prefix_sends_cache_control_for_anthropic():
    """cached_prefix injects cache_control:ephemeral on the first content block."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    fake = _make_litellm_response("humanized", 300, 120)
    mock_acompletion = AsyncMock(return_value=fake)
    with patch("litellm.acompletion", new=mock_acompletion):
        from llm import complete
        await complete(
            prompt="polish this resume",
            model="anthropic/claude-sonnet-4-6",
            cached_prefix="<large resume text>",
        )

    messages = mock_acompletion.call_args.kwargs["messages"]
    content = messages[0]["content"]
    assert isinstance(content, list), "cached_prefix must produce multi-block content"
    first_block = content[0]
    assert first_block.get("cache_control") == {"type": "ephemeral"}
    assert first_block["text"] == "<large resume text>"


@pytest.mark.asyncio
async def test_cached_prefix_ignored_for_non_anthropic():
    """cached_prefix is a no-op for non-Anthropic models — single string content."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    fake = _make_litellm_response("result", 50, 20)
    mock_acompletion = AsyncMock(return_value=fake)
    with patch("litellm.acompletion", new=mock_acompletion):
        from llm import complete
        await complete(
            prompt="rewrite",
            model="gemini/gemini-2.5-flash-lite",
            cached_prefix="some large text",
        )

    messages = mock_acompletion.call_args.kwargs["messages"]
    content = messages[0]["content"]
    assert isinstance(content, str), "Non-Anthropic models should use simple string content"


@pytest.mark.asyncio
async def test_response_text_is_stripped():
    """Whitespace is stripped from the model response text."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    fake = _make_litellm_response("  result with spaces  ", 10, 5)
    with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
        from llm import complete
        result = await complete("prompt", "gemini/gemini-2.5-flash-lite")

    assert result["text"] == "result with spaces"
