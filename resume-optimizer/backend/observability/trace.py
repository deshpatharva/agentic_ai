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
