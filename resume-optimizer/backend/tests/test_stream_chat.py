"""Tests for llm.stream_chat — mocks litellm.acompletion, no real API calls."""

import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("GROQ_API_KEY", "test")


def _make_stream_chunk(text: str | None = None, usage=None):
    """Build a minimal chunk mock matching LiteLLM's streaming shape."""
    chunk = MagicMock()
    if text is not None:
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
    else:
        chunk.choices = []
    chunk.usage = usage
    chunk._hidden_params = {}
    return chunk


async def _stream(chunks):
    """Async generator that yields chunks — simulates LiteLLM acompletion(stream=True)."""
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_stream_chat_yields_tokens_then_usage():
    """stream_chat yields token events for each delta, then a single usage event."""
    from llm import stream_chat

    usage_obj = MagicMock()
    usage_obj.prompt_tokens = 20
    usage_obj.completion_tokens = 10

    chunks = [
        _make_stream_chunk("Hello"),
        _make_stream_chunk(" world"),
        _make_stream_chunk(usage=usage_obj),   # final usage chunk
    ]

    mock_response = _stream(chunks)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        events = []
        async for ev in stream_chat([{"role": "user", "content": "hi"}], "groq/llama-3.1-8b-instant"):
            events.append(ev)

    token_events = [e for e in events if e["type"] == "token"]
    usage_events = [e for e in events if e["type"] == "usage"]

    assert len(token_events) == 2
    assert token_events[0]["text"] == "Hello"
    assert token_events[1]["text"] == " world"
    assert len(usage_events) == 1
    assert usage_events[0]["input_tokens"] == 20
    assert usage_events[0]["output_tokens"] == 10


@pytest.mark.asyncio
async def test_stream_chat_usage_is_last():
    """The usage event must always be the final event yielded."""
    from llm import stream_chat

    usage_obj = MagicMock()
    usage_obj.prompt_tokens = 5
    usage_obj.completion_tokens = 3

    chunks = [_make_stream_chunk("hi"), _make_stream_chunk(usage=usage_obj)]
    mock_response = _stream(chunks)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        events = []
        async for ev in stream_chat([], "groq/llama-3.1-8b-instant"):
            events.append(ev)

    assert events[-1]["type"] == "usage"


@pytest.mark.asyncio
async def test_stream_chat_groq_prefix_routes_through():
    """groq/ prefix model name is passed unchanged to litellm.acompletion."""
    from llm import stream_chat

    chunks = [_make_stream_chunk(usage=MagicMock(prompt_tokens=0, completion_tokens=0))]
    mock_response = _stream(chunks)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)) as mock_call:
        async for _ in stream_chat([], "groq/llama-3.1-8b-instant"):
            pass

    call_kwargs = mock_call.call_args
    assert call_kwargs.kwargs["model"] == "groq/llama-3.1-8b-instant"
    assert call_kwargs.kwargs["stream"] is True


@pytest.mark.asyncio
async def test_stream_chat_empty_delta_not_yielded():
    """None or empty delta strings do not produce token events."""
    from llm import stream_chat

    chunks = [
        _make_stream_chunk(None),   # no choices
        _make_stream_chunk(""),     # empty string
        _make_stream_chunk(usage=MagicMock(prompt_tokens=0, completion_tokens=0)),
    ]
    mock_response = _stream(chunks)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        events = []
        async for ev in stream_chat([], "groq/llama-3.1-8b-instant"):
            events.append(ev)

    token_events = [e for e in events if e["type"] == "token"]
    assert len(token_events) == 0
