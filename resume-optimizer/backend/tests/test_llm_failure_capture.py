"""Failed LLM calls must reach the ledger (status='error' + metadata) and
still raise; successes must record finish_reason. Spec decision: metadata
only — these tests also pin that no prompt text lands in the row."""

import asyncio
import os
import sys
import types
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_llm_capture.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


class _FakeProviderError(Exception):
    def __init__(self):
        super().__init__("boom")
        self.status_code = 429


def _fake_response(text="hello", finish="stop"):
    usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None)
    msg = types.SimpleNamespace(content=text, tool_calls=None)
    choice = types.SimpleNamespace(message=msg, finish_reason=finish)
    return types.SimpleNamespace(usage=usage, choices=[choice], _hidden_params={})


@pytest.fixture
def captured(monkeypatch):
    import llm
    rows = []

    async def _capture(row_kwargs):
        rows.append(row_kwargs)

    monkeypatch.setattr(llm, "_record_call", _capture)
    return rows


async def _drain():
    for _ in range(5):
        await asyncio.sleep(0.01)


async def test_complete_records_error_row_and_raises(captured, monkeypatch):
    import llm

    async def _boom(**kwargs):
        raise _FakeProviderError()

    monkeypatch.setattr(llm.litellm, "acompletion", _boom)
    with pytest.raises(_FakeProviderError):
        await llm.complete("prompt text", "groq/some-model")
    await _drain()
    assert len(captured) == 1
    row = captured[0]
    assert row["status"] == "error"
    assert row["error_type"] == "_FakeProviderError"
    assert row["error_code"] == "429"
    assert row["attempt"] == 1
    assert row["cost_usd"] == 0.0
    assert row["cost_source"] == "error"
    assert "prompt" not in str(row.values())  # no payload capture, ever


async def test_transient_retry_then_failure_records_attempt_2(captured, monkeypatch):
    import llm

    async def _timeout(**kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(llm.litellm, "acompletion", _timeout)
    with pytest.raises(asyncio.TimeoutError):
        await llm.complete("prompt", "groq/some-model")
    await _drain()
    assert captured[-1]["status"] == "error"
    assert captured[-1]["attempt"] == 2


async def test_complete_success_records_finish_reason(captured, monkeypatch):
    import llm

    async def _ok(**kwargs):
        return _fake_response(finish="length")

    monkeypatch.setattr(llm.litellm, "acompletion", _ok)
    out = await llm.complete("prompt", "groq/some-model")
    assert out["text"] == "hello"
    await _drain()
    assert captured[-1]["status"] == "ok"
    assert captured[-1]["finish_reason"] == "length"
    assert captured[-1]["attempt"] == 1


async def test_complete_with_tools_error_row(captured, monkeypatch):
    import llm

    async def _boom(**kwargs):
        raise _FakeProviderError()

    monkeypatch.setattr(llm.litellm, "acompletion", _boom)
    with pytest.raises(_FakeProviderError):
        await llm.complete_with_tools([{"role": "user", "content": "x"}], "groq/m", tools=[])
    await _drain()
    row = captured[-1]
    assert row["status"] == "error"
    # generic exception path retried without tools -> two invocations
    assert row["attempt"] == 2


async def test_stream_chat_error_mid_call(captured, monkeypatch):
    import llm

    async def _boom(**kwargs):
        raise _FakeProviderError()

    monkeypatch.setattr(llm.litellm, "acompletion", _boom)
    with pytest.raises(_FakeProviderError):
        async for _ in llm.stream_chat([{"role": "user", "content": "x"}], "groq/m"):
            pass
    await _drain()
    assert captured[-1]["status"] == "error"
    assert captured[-1]["error_type"] == "_FakeProviderError"


async def test_job_context_resolved_in_record_call(monkeypatch):
    """_record_call itself resolves job/user context into the row."""
    import llm
    from observability.trace import set_job_context

    added = []

    class _FakeSession:
        def add(self, row):
            added.append(row)
        async def commit(self):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    import db.session as dbs
    monkeypatch.setattr(dbs, "AsyncSessionLocal", lambda: _FakeSession())

    jid, uid = uuid.uuid4(), uuid.uuid4()
    set_job_context(str(jid), str(uid))
    try:
        await llm._record_call({
            "model": "groq/m", "provider": "groq", "input_tokens": 1,
            "output_tokens": 1, "cost_usd": 0.0, "cost_source": "zero",
        })
    finally:
        set_job_context(None, None)
    assert len(added) == 1
    assert added[0].job_id == jid
    assert added[0].user_id == uid
