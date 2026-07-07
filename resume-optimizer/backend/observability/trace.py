"""Async-safe trace context propagated via contextvars — zero call-site plumbing."""

import contextvars
import uuid

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_call_kind: contextvars.ContextVar[str] = contextvars.ContextVar("call_kind", default="")


def new_trace(trace_id: str | None = None) -> str:
    tid = trace_id or uuid.uuid4().hex
    _trace_id.set(tid)
    return tid


def current_trace() -> str:
    return _trace_id.get()


def set_call_kind(kind: str) -> None:
    _call_kind.set(kind)


def current_call_kind() -> str:
    return _call_kind.get()


_job_id: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="")
_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="")


def set_job_context(job_id: str | None, user_id: str | None) -> None:
    """Bind the pipeline job/user to this async context so every LlmCallLog
    row written during the run carries them (llm._record_call resolves these).
    """
    _job_id.set(job_id or "")
    _user_id.set(user_id or "")


def current_job_id() -> str:
    return _job_id.get()


def current_user_id() -> str:
    return _user_id.get()
