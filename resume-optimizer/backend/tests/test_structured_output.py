"""response_format is forwarded/coerced/dropped per provider."""
import sys, os
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("BOOTSTRAP_SECRET", "x" * 32)
import llm

def _fake_response():
    class M: ...
    r = M(); r.choices = [M()]; r.choices[0].message = M()
    r.choices[0].message.content = '{"ok": true}'
    r.usage = M(); r.usage.prompt_tokens = 10; r.usage.completion_tokens = 5
    return r

@pytest.mark.asyncio
async def test_gemini_gets_json_schema():
    schema = {"type": "json_schema", "json_schema": {"name": "s", "schema": {"type": "object"}}}
    with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_response())) as m:
        await llm.complete("p", "gemini/gemini-2.5-flash-lite", response_format=schema)
    assert m.call_args.kwargs["response_format"] == schema

@pytest.mark.asyncio
async def test_groq_schema_coerced_to_json_object():
    schema = {"type": "json_schema", "json_schema": {"name": "s", "schema": {"type": "object"}}}
    with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_response())) as m:
        await llm.complete("p", "groq/llama-3.1-8b-instant", response_format=schema)
    assert m.call_args.kwargs["response_format"] == {"type": "json_object"}

@pytest.mark.asyncio
async def test_other_provider_no_response_format():
    schema = {"type": "json_schema", "json_schema": {"name": "s", "schema": {"type": "object"}}}
    with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_response())) as m:
        await llm.complete("p", "anthropic/claude-sonnet-4-6", response_format=schema)
    assert "response_format" not in m.call_args.kwargs

@pytest.mark.asyncio
async def test_no_response_format_no_kwarg():
    with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_response())) as m:
        await llm.complete("p", "gemini/gemini-2.5-flash-lite")
    assert "response_format" not in m.call_args.kwargs
