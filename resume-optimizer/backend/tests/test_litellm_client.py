"""Tests for LiteLLM client wrapper."""

import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from llm.litellm_client import LiteLLMClient
from llm.config import LLMConfig

pytestmark = pytest.mark.asyncio

@pytest.mark.asyncio
async def test_complete_with_anthropic():
    """LiteLLMClient.complete() calls Anthropic when primary provider is anthropic."""
    config = LLMConfig(primary_provider="anthropic", primary_model="claude-opus-4-8")
    client = LiteLLMClient(config)

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Test response"))],
            usage=MagicMock(prompt_tokens=100, completion_tokens=50),
        )

        result = await client.complete("Test prompt")

        assert result["text"] == "Test response"
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50

@pytest.mark.asyncio
async def test_complete_returns_dict_structure():
    """complete() returns dict with text, input_tokens, output_tokens."""
    config = LLMConfig()
    client = LiteLLMClient(config)

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Response"))],
            usage=MagicMock(prompt_tokens=50, completion_tokens=25),
        )

        result = await client.complete("Prompt")

        assert isinstance(result, dict)
        assert "text" in result
        assert "input_tokens" in result
        assert "output_tokens" in result

@pytest.mark.asyncio
async def test_complete_respects_max_output_tokens():
    """complete() passes max_tokens parameter to litellm."""
    config = LLMConfig()
    client = LiteLLMClient(config)

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Response"))],
            usage=MagicMock(prompt_tokens=50, completion_tokens=25),
        )

        await client.complete("Prompt", max_tokens=1000)

        # Verify completion was called with max_tokens
        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs.get("max_tokens") == 1000

@pytest.mark.asyncio
async def test_fallback_chain_tried_on_primary_failure():
    """LiteLLMClient tries fallback providers when primary fails."""
    config = LLMConfig()
    client = LiteLLMClient(config)

    call_count = 0
    def mock_completion_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # First call (primary) fails
            raise Exception("Primary provider down")
        # Second call (first fallback) succeeds
        return MagicMock(
            choices=[MagicMock(message=MagicMock(content="Fallback response"))],
            usage=MagicMock(prompt_tokens=30, completion_tokens=15),
        )

    with patch("litellm.completion", side_effect=mock_completion_side_effect):
        result = await client.complete("Prompt")
        assert result["text"] == "Fallback response"
        assert call_count == 2  # Tried primary then fallback
