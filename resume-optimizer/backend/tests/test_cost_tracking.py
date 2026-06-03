"""Token extraction tests for LLM cost tracking.

Tests that the complete() function returns {text, input_tokens, output_tokens}
instead of just text, enabling cost tracking across all providers.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Set up test env vars before importing llm module
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).parent.parent))

from llm import complete


@pytest.mark.asyncio
async def test_complete_returns_text_and_tokens():
    """Test that Anthropic responses return {text, input_tokens, output_tokens}."""
    # Mock Anthropic response with usage data
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "This is a test response."
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    with patch("llm._get_anthropic") as mock_get_anthropic:
        mock_client = AsyncMock()
        mock_get_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await complete(
            prompt="Test prompt",
            model="claude-3-5-sonnet-20241022"
        )

        # Verify result is a dict with expected keys
        assert isinstance(result, dict)
        assert "text" in result
        assert "input_tokens" in result
        assert "output_tokens" in result

        # Verify values
        assert result["text"] == "This is a test response."
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50


@pytest.mark.asyncio
async def test_complete_google_defaults_to_zero_tokens():
    """Test that Google Gemini responses default to zero tokens (not exposed by SDK)."""
    # Mock Google response (no usage data available in SDK)
    mock_response = MagicMock()
    mock_response.text = "Google response text."

    with patch("llm._get_google") as mock_get_google:
        mock_client = MagicMock()
        mock_get_google.return_value = mock_client
        # Set up the chain: client.models.generate_content(...) returns mock_response
        mock_client.models.generate_content.return_value = mock_response

        # Mock asyncio.to_thread to call the function directly
        async def mock_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await complete(
                prompt="Test prompt",
                model="gemini-1.5-pro"
            )

            # Verify result structure
            assert isinstance(result, dict)
            assert result["text"] == "Google response text."
            assert result["input_tokens"] == 0
            assert result["output_tokens"] == 0


@pytest.mark.asyncio
async def test_complete_groq_returns_prompt_completion_tokens():
    """Test that Groq responses map prompt_tokens → input_tokens and completion_tokens → output_tokens."""
    # Mock Groq response with usage data
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Groq response here."
    mock_response.usage.prompt_tokens = 75
    mock_response.usage.completion_tokens = 25

    with patch("llm._get_groq") as mock_get_groq:
        mock_client = AsyncMock()
        mock_get_groq.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await complete(
            prompt="Test prompt",
            model="llama-3-70b-versatile"
        )

        # Verify result structure and token mapping
        assert isinstance(result, dict)
        assert result["text"] == "Groq response here."
        assert result["input_tokens"] == 75  # mapped from prompt_tokens
        assert result["output_tokens"] == 25  # mapped from completion_tokens
