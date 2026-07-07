# AI Observability (Admin) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Industry-standard LLM observability in the admin dashboard: failure capture, latency percentiles, error analytics, health badges, and per-run trace waterfalls (spec: `resume-optimizer/docs/superpowers/specs/2026-07-06-ai-observability-design.md`).

**Architecture:** One migration extends the `llm_call_log` ledger with status/error columns; `llm.py`'s three entry points record failures through the existing `_record_call` chokepoint and re-raise; a new `admin/observability.py` router aggregates on read (Python-side bucketing/percentiles — dialect-portable); the admin UI adds only views that don't exist (health tiles on the dashboard, one new Observability page, a PipelineRuns link).

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic (backend), React + recharts + the existing `adminUi.jsx` primitives (frontend), pytest via the Windows venv.

## Global Constraints

- **Repo root:** `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai`, branch `claude/effort-estimation-m4a4ep`. Backend paths relative to `resume-optimizer/backend/`. Do not push until the final task.
- **Test runner (WSL → Windows venv), from `resume-optimizer/backend/`:**
  `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/<file> -q`
  Plain `python3`/`pytest` will NOT work. Env vars must be set INSIDE test files via `os.environ.setdefault` (bash prefixes don't cross the WSL→Windows boundary). Console is cp1252 — no non-ASCII in test assertion literals.
- **Frontend build check, from `resume-optimizer/frontend/`:** `npm run build` (vite). If `npm` is unavailable in WSL, use `cmd.exe /c "cd /d C:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\frontend && npm run build"`.
- **Privacy (spec decision 2):** never store prompt or completion text — error metadata only.
- **No duplication (spec decision 5):** `Analytics.jsx` and the existing `/admin/analytics/*` endpoints are untouched; `/series` must NOT return cost/token series.
- **Known-failure baseline:** ~428 passed / 18 failed (all pre-existing: test_auto_profile 7, test_chat_agent 8, test_pr7_edit_resume 1 mojibake, test_optimizer_improvements 1, test_pipeline_integration 1; test_chat_sessions 0-2 order-dependent). No task may introduce a NEW failure.
- Working-tree files with CRLF-only modifications (e.g. `chat/gaps.py`) are pre-existing noise — never stage them. `git add` exact paths only.

---

### Task 1: Migration 0027 + LlmCallLog model columns

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0027_add_llm_call_observability_columns.py`
- Modify: `resume-optimizer/backend/db/models.py` (LlmCallLog, after `cache_hit` ~line 278)

**Interfaces:**
- Consumes: revision `"0026"` as down_revision (verify: `grep '^revision' resume-optimizer/backend/alembic/versions/0026_*.py` prints `revision = "0026"`).
- Produces: `LlmCallLog.status` (String(16), default "ok"), `.error_type` (String(100), nullable), `.error_code` (String(40), nullable), `.attempt` (SmallInteger, default 1), `.finish_reason` (String(40), nullable) — Tasks 2–4 read/write these exact names.

- [ ] **Step 1: Write the migration**

Create `resume-optimizer/backend/alembic/versions/0027_add_llm_call_observability_columns.py`:

```python
"""add LLM call observability columns

Failure capture and finish-reason tracking for llm_call_log. Until now the
exception paths in llm.py never reached the ledger, so error rates were
unknowable in-product. Columns follow OTel GenAI naming where sensible
(error_type ~ error.type, finish_reason ~ gen_ai.response.finish_reasons).
Existing rows backfill to status='ok' via the server default — every
pre-0027 row was by definition a success.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_call_log", sa.Column("status", sa.String(16), nullable=False, server_default="ok"))
    op.add_column("llm_call_log", sa.Column("error_type", sa.String(100), nullable=True))
    op.add_column("llm_call_log", sa.Column("error_code", sa.String(40), nullable=True))
    op.add_column("llm_call_log", sa.Column("attempt", sa.SmallInteger(), nullable=False, server_default="1"))
    op.add_column("llm_call_log", sa.Column("finish_reason", sa.String(40), nullable=True))
    op.create_index("ix_llm_call_status_created", "llm_call_log", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_status_created", table_name="llm_call_log")
    for col in ("finish_reason", "attempt", "error_code", "error_type", "status"):
        op.drop_column("llm_call_log", col)
```

(Plain `add_column`s — no FK/ALTER-rename, so no batch mode needed on SQLite.)

- [ ] **Step 2: Add the model columns**

In `resume-optimizer/backend/db/models.py`: check the sqlalchemy import line (`grep -n "^from sqlalchemy import" resume-optimizer/backend/db/models.py`) and add `SmallInteger` if absent (`String` is already there). Then in `LlmCallLog`, directly below the `cache_hit` column, add:

```python
    # Observability (0027): failure capture + finish reason. Named to map onto
    # OTel GenAI semantic conventions for a possible future export.
    status        = Column(String(16),  nullable=False, default="ok")
    error_type    = Column(String(100), nullable=True)
    error_code    = Column(String(40),  nullable=True)
    attempt       = Column(SmallInteger, nullable=False, default=1)
    finish_reason = Column(String(40),  nullable=True)
```

- [ ] **Step 3: Verify migration + model**

```bash
rm -f ./test_migrate_local.db
/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -c "import os; os.environ['DATABASE_URL']='sqlite+aiosqlite:///./test_migrate_local.db'; from alembic.config import main; main(argv=['upgrade','head'])"
rm -f ./test_migrate_local.db
/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -c "import os; os.environ.setdefault('JWT_SECRET','x'*32); from db.models import LlmCallLog; print(all(hasattr(LlmCallLog, c) for c in ('status','error_type','error_code','attempt','finish_reason')))"
```
Expected: upgrade completes through 0027; second command prints `True`. Also run `tests/test_migrations.py` — must stay 3 passed.

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0027_add_llm_call_observability_columns.py resume-optimizer/backend/db/models.py
git commit -m "feat: add llm_call_log observability columns (status, error, attempt, finish_reason)"
```

---

### Task 2: Failure capture in llm.py + job/user trace context

**Files:**
- Modify: `resume-optimizer/backend/observability/trace.py`
- Modify: `resume-optimizer/backend/llm.py` (all three entry points + `_record_call`)
- Modify: `resume-optimizer/backend/main.py` (`_run_pipeline_task`, first lines of its body)
- Test: `resume-optimizer/backend/tests/test_llm_failure_capture.py` (new)

**Interfaces:**
- Consumes: Task 1's columns.
- Produces:
  - `observability.trace.set_job_context(job_id: str | None, user_id: str | None)`, `current_job_id() -> str`, `current_user_id() -> str`.
  - Ledger rows for FAILED calls: `status='error'`, `error_type`, `error_code`, `attempt`, `latency_ms`, `cost_usd=0.0`, `cost_source='error'`. Success rows gain `status='ok'`, `finish_reason`, `attempt`.
  - Pipeline-run rows now carry `job_id`/`user_id` (resolved inside `_record_call` from context) — Task 4's `/trace?job_id=` depends on this.
- **Spec addendum (documented deviation):** the spec's `/trace?job_id=` assumed `LlmCallLog.job_id` was populated; it never was (the columns exist but no writer sets them). This task adds job/user contextvars set by `_run_pipeline_task` and resolved in `_record_call` — the minimal enabler, same chokepoint philosophy.

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_llm_failure_capture.py`:

```python
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
```

- [ ] **Step 2: Run to verify failures**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_llm_failure_capture.py -q`
Expected: FAIL — error tests get the raised exception but `captured` stays empty (no error rows recorded today); `set_job_context` ImportError.

- [ ] **Step 3: Extend `observability/trace.py`**

Append:

```python
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
```

- [ ] **Step 4: Wire context into `_run_pipeline_task` and `_record_call`**

1. `resume-optimizer/backend/main.py` — find `async def _run_pipeline_task(` and add as its FIRST body lines (before any awaits):

```python
    # Bind trace + job context: every LLM call in this run logs with this
    # job's id, and the trace waterfall keys off it (spec 2026-07-06).
    from observability.trace import new_trace, set_job_context
    new_trace(job_id)
    set_job_context(job_id, user_id)
```

(`job_id`/`user_id` are the function's str parameters — verify with `grep -n "async def _run_pipeline_task" resume-optimizer/backend/main.py`.)

2. `resume-optimizer/backend/llm.py` — replace `_record_call` with:

```python
async def _record_call(row_kwargs: dict) -> None:
    """Fire-and-forget: write one LlmCallLog row in a fresh session.

    Resolves job/user context here (single chokepoint) so pipeline-run rows
    carry job_id/user_id without any call-site plumbing.
    """
    try:
        import uuid as _uuid
        from db.models import LlmCallLog
        from db.session import AsyncSessionLocal
        from observability.trace import current_job_id, current_user_id
        for key, val in (("job_id", current_job_id()), ("user_id", current_user_id())):
            if val and key not in row_kwargs:
                try:
                    row_kwargs[key] = _uuid.UUID(val)
                except ValueError:
                    pass
        async with AsyncSessionLocal() as db:
            db.add(LlmCallLog(**row_kwargs))
            await db.commit()
    except Exception:
        _logger.exception("Failed to write LlmCallLog row")
```

- [ ] **Step 5: Failure capture in the three entry points**

All in `resume-optimizer/backend/llm.py`.

1. Add a module-level helper below `_record_call`:

```python
def _error_row(model: str, exc: Exception, t0: float, attempt: int) -> dict:
    """Ledger row for a failed call — metadata only, never payload text."""
    from observability.trace import current_trace, current_call_kind
    code = getattr(exc, "status_code", None)
    return {
        "trace_id":      current_trace() or None,
        "model":         model,
        "provider":      _provider(model),
        "call_kind":     current_call_kind() or None,
        "status":        "error",
        "error_type":    type(exc).__name__[:100],
        "error_code":    (str(code)[:40] if code is not None else None),
        "attempt":       attempt,
        "input_tokens":  0,
        "output_tokens": 0,
        "cost_usd":      0.0,
        "cost_source":   "error",
        "latency_ms":    int((time.perf_counter() - t0) * 1000),
        "created_at":    datetime.now(timezone.utc),
    }
```

2. **`complete()`** — replace the retry block (lines ~146-151) with:

```python
    # One bounded retry on transient failures (timeout / connection / 5xx).
    attempt = 1
    finish_reason = None
    try:
        try:
            response = await litellm.acompletion(**call_kwargs)
        except _TRANSIENT as exc:
            _logger.warning("LLM call to %s failed transiently (%s) — retrying once", model, type(exc).__name__)
            attempt = 2
            response = await litellm.acompletion(**call_kwargs)
    except Exception as exc:
        asyncio.create_task(_record_call(_error_row(model, exc, t0, attempt)))
        raise
    finish_reason = getattr(response.choices[0], "finish_reason", None) if getattr(response, "choices", None) else None
```

and extend its success `_record_call` dict with:

```python
        "status":        "ok",
        "attempt":       attempt,
        "finish_reason": finish_reason,
```

3. **`complete_with_tools()`** — replace its try/except (lines ~237-247) with:

```python
    attempt = 1
    try:
        try:
            response = await litellm.acompletion(**tool_kwargs)
        except _TRANSIENT as exc:
            _logger.warning("tool-calling chat to %s failed transiently (%s) — retrying once",
                            model, type(exc).__name__)
            attempt = 2
            response = await litellm.acompletion(**tool_kwargs)
        except Exception as exc:
            _logger.warning("tool-calling chat to %s failed (%s) — retrying WITHOUT tools",
                            model, type(exc).__name__)
            attempt = 2
            no_tools = {k: v for k, v in tool_kwargs.items() if k not in ("tools", "tool_choice")}
            response = await litellm.acompletion(**no_tools)
    except Exception as exc:
        asyncio.create_task(_record_call(_error_row(model, exc, t0, attempt)))
        raise
    finish_reason = getattr(response.choices[0], "finish_reason", None) if getattr(response, "choices", None) else None
```

and extend its success `_record_call` dict with the same three keys (`"status": "ok"`, `"attempt": attempt`, `"finish_reason": finish_reason`).

4. **`stream_chat()`** — wrap the acompletion call AND the consume loop (mid-stream failures are the realistic outage mode). Replace from `response = await litellm.acompletion(` through the `async for` loop with:

```python
    in_tok = out_tok = 0
    last_response = None
    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            timeout=_CALL_TIMEOUT_S,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in response:
            last_response = chunk
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                if ttft_ms is None:
                    ttft_ms = int((time.perf_counter() - t0) * 1000)
                yield {"type": "token", "text": delta}
            usage = getattr(chunk, "usage", None)
            if usage:
                in_tok  = getattr(usage, "prompt_tokens", 0) or 0
                out_tok = getattr(usage, "completion_tokens", 0) or 0
    except Exception as exc:
        row = _error_row(model, exc, t0, attempt=1)
        row["ttft_ms"] = ttft_ms
        asyncio.create_task(_record_call(row))
        raise
```

and extend its success `_record_call` dict with `"status": "ok"`, `"attempt": 1`, plus the cached-token parity fields (spec A "parity fix in passing") computed before the dict, mirroring `complete()`:

```python
    usage_obj = getattr(last_response, "usage", None)
    cached_tok = getattr(usage_obj, "prompt_tokens_details", None)
    cached_tok = getattr(cached_tok, "cached_tokens", 0) or 0 if cached_tok else 0
    cached_tok = cached_tok if isinstance(cached_tok, int) else 0
```

with `"cached_input_tokens": cached_tok, "cache_hit": cached_tok > 0,` added to the dict. (`finish_reason` is not reliably present on stream chunks — leave it unset here.)

- [ ] **Step 6: Run the tests**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_llm_failure_capture.py tests/test_llm.py tests/test_context_caching.py -q`
Expected: new file 6 passed; the two existing llm suites stay green (they passed at baseline).

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/llm.py resume-optimizer/backend/observability/trace.py resume-optimizer/backend/main.py resume-optimizer/backend/tests/test_llm_failure_capture.py
git commit -m "feat: record failed LLM calls with error metadata; bind job context to pipeline runs"
```

---

### Task 3: Observability router — /health + /series

**Files:**
- Create: `resume-optimizer/backend/admin/observability.py`
- Modify: `resume-optimizer/backend/main.py` (router registration, next to `app.include_router(admin_router)` line ~291)
- Test: `resume-optimizer/backend/tests/test_observability_api.py` (new)

**Interfaces:**
- Consumes: Task 1 columns; `get_admin_user` (verify location: `grep -rn "def get_admin_user" resume-optimizer/backend/` — import from that module; the existing `admin/router.py` imports it the same way).
- Produces: `admin.observability.router` (APIRouter, prefix `/admin/observability`); `_percentiles(values, points=(50, 95, 99)) -> dict[int, float | None]` (nearest-rank; Task 4 reuses it); `GET /health` and `GET /series` response shapes below (Tasks 5–6 consume them).

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_observability_api.py`:

```python
"""Admin AI-observability endpoints: health grading, series bucketing."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-for-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_obs.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, LlmCallLog, User, PlanType
from db.session import get_db
from main import app

TEST_DB_URL = "sqlite+aiosqlite:///./test_obs.db"
_engine = create_async_engine(TEST_DB_URL, echo=False)
_TestSession = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    app.dependency_overrides[get_db] = _override_get_db
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    app.dependency_overrides.pop(get_db, None)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()
    try:
        os.remove("./test_obs.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def admin_client():
    from auth.dependencies import get_admin_user  # noqa: PLC0415 — same module the router depends on
    admin = User(id=uuid.uuid4(), email="obs-admin@test.com", password_hash="x",
                 plan=PlanType.free, is_admin=True)

    async def _admin():
        return admin

    app.dependency_overrides[get_admin_user] = _admin
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_admin_user, None)


def _row(status="ok", latency=100, cost=0.001, age_hours=1, model="groq/m", **kw):
    return LlmCallLog(
        model=model, provider=model.split("/")[0], status=status,
        error_type=("FakeError" if status == "error" else None),
        input_tokens=10, output_tokens=5, cost_usd=cost, cost_source="zero",
        latency_ms=latency,
        created_at=datetime.now(timezone.utc) - timedelta(hours=age_hours), **kw)


async def _seed(rows):
    async with _TestSession() as db:
        for r in rows:
            db.add(r)
        await db.commit()


async def test_health_empty_window_is_ok(admin_client):
    r = await admin_client.get("/admin/observability/health")
    assert r.status_code == 200
    body = r.json()
    assert body["signals"]["error_rate"]["status"] == "ok"
    assert body["counts"]["calls_24h"] == 0


async def test_health_grades_error_rate_crit(admin_client):
    await _seed([_row() for _ in range(45)] + [_row(status="error") for _ in range(5)])
    r = await admin_client.get("/admin/observability/health")
    body = r.json()
    assert body["counts"]["calls_24h"] == 50
    assert body["counts"]["errors_24h"] == 5
    assert body["signals"]["error_rate"]["status"] == "crit"  # 10% >= 5%


async def test_series_daily_buckets(admin_client):
    await _seed([_row(age_hours=30), _row(age_hours=30, status="error")])
    r = await admin_client.get("/admin/observability/series", params={"days": 7})
    body = r.json()
    assert body["bucket"] == "day"
    assert body["capped"] is False
    total_calls = sum(b["calls"] for b in body["series"])
    total_errors = sum(b["errors"] for b in body["series"])
    assert total_calls >= 2 and total_errors >= 1


async def test_series_hourly_when_short_window(admin_client):
    r = await admin_client.get("/admin/observability/series", params={"days": 1})
    assert r.json()["bucket"] == "hour"
```

Also add pure-unit tests for the helpers at the bottom of the same file:

```python
def test_percentiles_nearest_rank():
    from admin.observability import _percentiles
    assert _percentiles([])[95] is None
    assert _percentiles([100])[50] == 100.0
    p = _percentiles(list(range(1, 101)))
    assert p[50] == 50.0 and p[95] == 95.0 and p[99] == 99.0


def test_grade_boundaries():
    from admin.observability import _grade
    assert _grade(0.019, 0.02, 0.05) == "ok"
    assert _grade(0.02, 0.02, 0.05) == "warn"
    assert _grade(0.05, 0.02, 0.05) == "crit"
    assert _grade(None, 0.02, 0.05) == "ok"
```

- [ ] **Step 2: Run to verify failure**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_observability_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'admin.observability'` / 404s.

- [ ] **Step 3: Implement the module (part 1)**

Create `resume-optimizer/backend/admin/observability.py`:

```python
"""Admin AI-observability endpoints: health, series, latency, errors, traces.

Aggregates the llm_call_log ledger at read time (same philosophy as
admin.router's cache_efficiency). Failure rows exist since migration 0027.
All queries are windowed and row-capped; bucketing and percentiles happen in
Python so the same code path serves SQLite (no percentile_cont) and Postgres.
"""

import math
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_admin_user
from db.models import LlmCallLog, PipelineJob, User
from db.session import get_db

router = APIRouter(prefix="/admin/observability", tags=["admin-observability"])

_FETCH_CAP = 50_000
_ERROR_RATE_WARN, _ERROR_RATE_CRIT = 0.02, 0.05
_LATENCY_WARN_X, _LATENCY_CRIT_X = 1.5, 2.0
_COST_WARN_X, _COST_CRIT_X = 1.5, 2.5


def _percentiles(values, points=(50, 95, 99)):
    """Nearest-rank percentiles; each point is None when values is empty."""
    if not values:
        return {p: None for p in points}
    vs = sorted(values)
    return {p: float(vs[max(0, math.ceil(p / 100 * len(vs)) - 1)]) for p in points}


def _grade(value, warn, crit):
    """ok/warn/crit for a signal value; None (no data / no baseline) is ok."""
    if value is None:
        return "ok"
    if value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "ok"


async def _window_rows(db, since, columns):
    """Newest-first windowed fetch, hard-capped. Returns (rows, capped)."""
    rows = (await db.execute(
        select(*columns)
        .where(LlmCallLog.created_at >= since)
        .order_by(LlmCallLog.created_at.desc())
        .limit(_FETCH_CAP)
    )).all()
    return rows, len(rows) == _FETCH_CAP


@router.get("/health")
async def observability_health(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """24h signals vs a 7-day baseline, graded ok/warn/crit."""
    now = datetime.now(timezone.utc)
    day_rows, _c = await _window_rows(
        db, now - timedelta(hours=24),
        (LlmCallLog.status, LlmCallLog.latency_ms, LlmCallLog.cost_usd))
    week_rows, _c = await _window_rows(
        db, now - timedelta(days=7),
        (LlmCallLog.status, LlmCallLog.latency_ms, LlmCallLog.cost_usd))

    def _stats(rows):
        calls = len(rows)
        errors = sum(1 for r in rows if r.status == "error")
        lats = [r.latency_ms for r in rows if r.status == "ok" and r.latency_ms is not None]
        cost = sum(r.cost_usd or 0.0 for r in rows)
        return calls, errors, _percentiles(lats)[95], cost

    d_calls, d_errors, d_p95, d_cost = _stats(day_rows)
    w_calls, w_errors, w_p95, w_cost = _stats(week_rows)

    error_rate = (d_errors / d_calls) if d_calls else 0.0
    baseline_daily_cost = w_cost / 7.0
    cost_ratio = (d_cost / baseline_daily_cost) if baseline_daily_cost > 0 else None
    lat_ratio = (d_p95 / w_p95) if (d_p95 is not None and w_p95) else None

    return {
        "counts": {"calls_24h": d_calls, "errors_24h": d_errors,
                   "calls_7d": w_calls, "errors_7d": w_errors},
        "signals": {
            "error_rate": {
                "value": round(error_rate, 4),
                "baseline": round(w_errors / w_calls, 4) if w_calls else None,
                "status": _grade(error_rate, _ERROR_RATE_WARN, _ERROR_RATE_CRIT),
            },
            "p95_latency_ms": {
                "value": d_p95,
                "baseline": w_p95,
                "status": _grade(lat_ratio, _LATENCY_WARN_X, _LATENCY_CRIT_X),
            },
            "cost_burn_usd": {
                "value": round(d_cost, 4),
                "baseline": round(baseline_daily_cost, 4),
                "status": _grade(cost_ratio, _COST_WARN_X, _COST_CRIT_X),
            },
        },
    }


@router.get("/series")
async def observability_series(
    days: int = Query(30, ge=1, le=180),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Calls/errors/error-rate/p95 per bucket (daily; hourly when days <= 2).

    Cost/token series are deliberately absent — /admin/analytics/tokens
    already serves them (spec decision 5: no duplication).
    """
    now = datetime.now(timezone.utc)
    rows, capped = await _window_rows(
        db, now - timedelta(days=days),
        (LlmCallLog.created_at, LlmCallLog.status, LlmCallLog.latency_ms))
    hourly = days <= 2
    fmt = "%Y-%m-%d %H:00" if hourly else "%Y-%m-%d"
    buckets: dict[str, dict] = {}
    for r in rows:
        ts = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        b = buckets.setdefault(ts.astimezone(timezone.utc).strftime(fmt),
                               {"calls": 0, "errors": 0, "lats": []})
        b["calls"] += 1
        if r.status == "error":
            b["errors"] += 1
        elif r.latency_ms is not None:
            b["lats"].append(r.latency_ms)
    return {
        "bucket": "hour" if hourly else "day",
        "capped": capped,
        "series": [
            {"bucket": k, "calls": b["calls"], "errors": b["errors"],
             "error_rate_pct": round(100.0 * b["errors"] / b["calls"], 2) if b["calls"] else 0.0,
             "p95_latency_ms": _percentiles(b["lats"])[95]}
            for k, b in sorted(buckets.items())
        ],
    }
```

(`PipelineJob`, `HTTPException`, `func`, `_uuid` are used by Task 4's endpoints in this same file — keep the imports.)

- [ ] **Step 4: Register the router**

In `resume-optimizer/backend/main.py`: next to `from admin.router import router as admin_router` add
`from admin.observability import router as observability_router`, and directly below `app.include_router(admin_router)` add
`app.include_router(observability_router)`.

- [ ] **Step 5: Run the tests**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_observability_api.py tests/test_admin.py -q`
Expected: new file all passed (6 async + 2 unit); test_admin.py stays at its baseline (13 passed).

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/admin/observability.py resume-optimizer/backend/main.py resume-optimizer/backend/tests/test_observability_api.py
git commit -m "feat: admin observability endpoints - health grading and series"
```

---

### Task 4: Observability router — /latency + /errors + /trace

**Files:**
- Modify: `resume-optimizer/backend/admin/observability.py` (append endpoints)
- Test: `resume-optimizer/backend/tests/test_observability_api.py` (append tests)

**Interfaces:**
- Consumes: Task 3's module (`_percentiles`, `_window_rows`, `_FETCH_CAP`, router); Task 2's `job_id`-bearing rows.
- Produces: `GET /latency`, `GET /errors`, `GET /trace` response shapes below (Tasks 5–6 consume).

- [ ] **Step 1: Append the failing tests**

Append to `resume-optimizer/backend/tests/test_observability_api.py`:

```python
async def test_latency_percentiles_per_model(admin_client):
    await _seed([_row(model="groq/fast", latency=100) for _ in range(9)]
                + [_row(model="groq/fast", latency=1000)])
    r = await admin_client.get("/admin/observability/latency", params={"days": 7})
    body = r.json()
    fast = next(m for m in body["models"] if m["model"] == "groq/fast")
    assert fast["calls"] >= 10
    assert fast["latency_ms"]["p50"] == 100.0
    assert fast["latency_ms"]["p99"] == 1000.0


async def test_errors_breakdown_and_recent(admin_client):
    await _seed([_row(status="error", model="deepseek/x", error_code="429") for _ in range(3)])
    r = await admin_client.get("/admin/observability/errors", params={"days": 7})
    body = r.json()
    dsx = next(b for b in body["breakdown"] if b["model"] == "deepseek/x")
    assert dsx["count"] == 3
    assert dsx["error_type"] == "FakeError"
    assert len(body["recent"]) >= 3
    assert body["recent"][0]["error_type"] == "FakeError"


async def test_trace_requires_exactly_one_id(admin_client):
    r = await admin_client.get("/admin/observability/trace")
    assert r.status_code == 422
    r = await admin_client.get("/admin/observability/trace",
                               params={"trace_id": "t", "job_id": str(uuid.uuid4())})
    assert r.status_code == 422


async def test_trace_by_job_id_with_waterfall_offsets(admin_client):
    from db.models import JobStatus, PipelineJob
    jid = uuid.uuid4()
    t0 = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with _TestSession() as db:
        db.add(PipelineJob(id=jid, resume_text="r", status=JobStatus.done))
        r1 = _row(job_id=jid, latency=500)
        r1.created_at = t0
        r2 = _row(job_id=jid, latency=300)
        r2.created_at = t0 + timedelta(seconds=2)
        db.add(r1)
        db.add(r2)
        await db.commit()
    r = await admin_client.get("/admin/observability/trace", params={"job_id": str(jid)})
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["status"] == "done"
    assert len(body["calls"]) == 2
    assert body["calls"][0]["offset_ms"] == 0
    assert body["calls"][1]["offset_ms"] == 2000


async def test_trace_unknown_id_404(admin_client):
    r = await admin_client.get("/admin/observability/trace", params={"job_id": str(uuid.uuid4())})
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify failures**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_observability_api.py -q -k "latency or errors or trace"`
Expected: FAIL with 404 (routes don't exist).

- [ ] **Step 3: Append the endpoints**

Append to `resume-optimizer/backend/admin/observability.py`:

```python
@router.get("/latency")
async def observability_latency(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-model p50/p95/p99 for latency_ms and ttft_ms (successful calls)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows, capped = await _window_rows(
        db, since,
        (LlmCallLog.model, LlmCallLog.status, LlmCallLog.latency_ms, LlmCallLog.ttft_ms))
    per_model: dict[str, dict] = {}
    for r in rows:
        if r.status != "ok":
            continue
        m = per_model.setdefault(r.model, {"lats": [], "ttfts": [], "calls": 0})
        m["calls"] += 1
        if r.latency_ms is not None:
            m["lats"].append(r.latency_ms)
        if r.ttft_ms is not None:
            m["ttfts"].append(r.ttft_ms)
    models = []
    for name, m in sorted(per_model.items(), key=lambda kv: -kv[1]["calls"]):
        lp, tp = _percentiles(m["lats"]), _percentiles(m["ttfts"])
        models.append({
            "model": name, "calls": m["calls"],
            "latency_ms": {"p50": lp[50], "p95": lp[95], "p99": lp[99]},
            "ttft_ms": {"p50": tp[50], "p95": tp[95], "p99": tp[99]},
        })
    return {"window_days": days, "capped": capped, "models": models}


@router.get("/errors")
async def observability_errors(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Error breakdown by type x provider x model, plus the 50 newest errors."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    breakdown = (await db.execute(
        select(
            LlmCallLog.error_type, LlmCallLog.provider, LlmCallLog.model,
            func.count().label("count"),
            func.max(LlmCallLog.created_at).label("last_seen"),
            func.max(LlmCallLog.error_code).label("sample_error_code"),
        )
        .where(LlmCallLog.created_at >= since, LlmCallLog.status == "error")
        .group_by(LlmCallLog.error_type, LlmCallLog.provider, LlmCallLog.model)
        .order_by(func.count().desc())
    )).all()
    recent = (await db.execute(
        select(LlmCallLog)
        .where(LlmCallLog.created_at >= since, LlmCallLog.status == "error")
        .order_by(LlmCallLog.created_at.desc())
        .limit(50)
    )).scalars().all()
    return {
        "window_days": days,
        "breakdown": [
            {"error_type": r.error_type or "unknown", "provider": r.provider,
             "model": r.model, "count": int(r.count), "last_seen": str(r.last_seen),
             "sample_error_code": r.sample_error_code}
            for r in breakdown
        ],
        "recent": [
            {"created_at": str(r.created_at), "model": r.model, "provider": r.provider,
             "call_kind": r.call_kind, "error_type": r.error_type, "error_code": r.error_code,
             "attempt": r.attempt, "latency_ms": r.latency_ms,
             "trace_id": r.trace_id, "job_id": str(r.job_id) if r.job_id else None}
            for r in recent
        ],
    }


@router.get("/trace")
async def observability_trace(
    trace_id: str | None = Query(None),
    job_id: str | None = Query(None),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Waterfall: ordered LLM calls for one trace or pipeline job."""
    if bool(trace_id) == bool(job_id):
        raise HTTPException(status_code=422, detail="Pass exactly one of trace_id or job_id.")
    q = select(LlmCallLog).order_by(LlmCallLog.created_at, LlmCallLog.id)
    job = None
    if trace_id:
        q = q.where(LlmCallLog.trace_id == trace_id)
    else:
        try:
            jid = _uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="job_id is not a valid UUID.")
        q = q.where(LlmCallLog.job_id == jid)
        job = await db.get(PipelineJob, jid)
    calls = (await db.execute(q.limit(500))).scalars().all()
    if not calls:
        raise HTTPException(status_code=404, detail="No LLM calls found for that id.")

    def _aware(ts):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    t0 = _aware(calls[0].created_at)
    return {
        "trace_id": trace_id or calls[0].trace_id,
        "job": ({"status": job.status.value, "error_message": job.error_message,
                 "created_at": str(job.created_at)} if job is not None else None),
        "calls": [
            {"offset_ms": int((_aware(c.created_at) - t0).total_seconds() * 1000),
             "latency_ms": c.latency_ms, "call_kind": c.call_kind, "model": c.model,
             "status": c.status, "error_type": c.error_type, "finish_reason": c.finish_reason,
             "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
             "cached_input_tokens": c.cached_input_tokens, "cost_usd": c.cost_usd,
             "attempt": c.attempt}
            for c in calls
        ],
    }
```

- [ ] **Step 4: Run the full test file**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_observability_api.py -q`
Expected: all passed (13 tests).

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/admin/observability.py resume-optimizer/backend/tests/test_observability_api.py
git commit -m "feat: admin observability endpoints - latency percentiles, errors, trace waterfall"
```

---

### Task 5: Frontend — health tiles, route/nav, Observability page (trend + latency)

**Files:**
- Modify: `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx`
- Modify: `resume-optimizer/frontend/src/main.jsx` (admin routes ~line 75)
- Modify: `resume-optimizer/frontend/src/pages/admin/AdminLayout.jsx` (AdminNav items)
- Create: `resume-optimizer/frontend/src/pages/admin/Observability.jsx`

**Interfaces:**
- Consumes: `/admin/observability/health`, `/series`, `/latency` (shapes from Tasks 3–4); `adminUi.jsx` exports (`StatCard`, `ChartCard`, `ChartState`, `CHART`); recharts (already a dependency).
- Produces: route `/admin/observability` and the page component Task 6 extends.

- [ ] **Step 1: Health tiles on AdminDashboard**

In `AdminDashboard.jsx`:
1. Add state: `const [aiHealth, setAiHealth] = useState(null);`
2. Add to the existing `Promise.allSettled` array: `client.get('/admin/observability/health').then(r => setAiHealth(r.data)),`
3. Below the `cards` array, add:

```jsx
  const HEALTH_ACCENT = {
    ok:   'bg-accent-soft text-primary',
    warn: 'bg-hilite-soft text-hilite',
    crit: 'bg-err-soft text-err',
  };
  const fmtMs = (ms) => ms == null ? '—' : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
  const healthCards = aiHealth ? [
    {
      label: 'AI Error Rate (24h)',
      value: `${(aiHealth.signals.error_rate.value * 100).toFixed(1)}%`,
      sub: `${aiHealth.counts.errors_24h} of ${aiHealth.counts.calls_24h} calls`,
      icon: AlertTriangle,
      accent: HEALTH_ACCENT[aiHealth.signals.error_rate.status],
    },
    {
      label: 'AI p95 Latency (24h)',
      value: fmtMs(aiHealth.signals.p95_latency_ms.value),
      sub: `7d baseline ${fmtMs(aiHealth.signals.p95_latency_ms.baseline)}`,
      icon: Activity,
      accent: HEALTH_ACCENT[aiHealth.signals.p95_latency_ms.status],
    },
    {
      label: 'AI Spend (24h)',
      value: `$${aiHealth.signals.cost_burn_usd.value.toFixed(2)}`,
      sub: `daily norm $${(aiHealth.signals.cost_burn_usd.baseline ?? 0).toFixed(2)}`,
      icon: DollarSign,
      accent: HEALTH_ACCENT[aiHealth.signals.cost_burn_usd.status],
    },
  ] : [];
```

4. Render the row directly above the existing cards grid (inside the non-loading branch):

```jsx
        {healthCards.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            {healthCards.map(c => <StatCard key={c.label} {...c} />)}
          </div>
        )}
```

(`AlertTriangle`, `Activity`, `DollarSign` are already imported.)

- [ ] **Step 2: Route + nav**

1. `main.jsx`: add a lazy import next to the other admin page imports, matching their exact pattern (see how `PipelineRuns` is imported — clone that line): `Observability` from `./pages/admin/Observability`. Add inside the `/admin` route block: `<Route path="observability" element={<Observability />} />`.
2. `AdminLayout.jsx`: find the `AdminNav` nav-item list (the NavLink entries with `to="/admin/..."`). Clone the runs/analytics item as "AI Observability" → `to="/admin/observability"`, matching icon style (use the `Activity` icon from lucide-react, adding it to the existing lucide import).

- [ ] **Step 3: Create the page (trend + latency views)**

Create `resume-optimizer/frontend/src/pages/admin/Observability.jsx`:

```jsx
import { useEffect, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import client from '../../api/client';
import { ChartCard, ChartState, CHART } from './adminUi';

function fmtMs(ms) {
  if (ms == null) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export default function Observability() {
  const [days, setDays] = useState(30);
  const [series, setSeries] = useState(null);
  const [latency, setLatency] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.allSettled([
      client.get('/admin/observability/series',  { params: { days } }).then(r => setSeries(r.data)),
      client.get('/admin/observability/latency', { params: { days: Math.min(days, 90) } }).then(r => setLatency(r.data)),
    ]).then((results) => {
      const failed = results.find(r => r.status === 'rejected');
      if (failed) setError(failed.reason?.response?.data?.detail || failed.reason?.message);
      setLoading(false);
    });
  }, [days]);

  return (
    <div className="p-4 sm:p-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-ink">AI Observability</h1>
        <div className="flex gap-1">
          {[7, 30, 90].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors ${
                days === d ? 'bg-accent-soft text-primary' : 'text-ink-mute hover:bg-surface-2'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="p-3 bg-err-soft border border-err/30 rounded-lg text-sm text-err">
          Failed to load: {String(error)}
        </div>
      )}

      <ChartCard title="Calls vs errors">
        <ChartState isLoading={loading} empty={!series?.series?.length}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series?.series || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
              <XAxis dataKey="bucket" tick={CHART.tick} tickFormatter={b => b.slice(5)} />
              <YAxis tick={CHART.tick} allowDecimals={false} />
              <Tooltip contentStyle={CHART.tooltip} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="calls" stroke={CHART.neutral} name="Calls" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="errors" stroke={CHART.red} name="Errors" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </ChartState>
      </ChartCard>

      <ChartCard title="Latency percentiles by model">
        <ChartState isLoading={loading} empty={!latency?.models?.length}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-faint uppercase tracking-wide">
                  <th className="py-2 pr-4">Model</th>
                  <th className="py-2 pr-4 text-right">Calls</th>
                  <th className="py-2 pr-4 text-right">p50</th>
                  <th className="py-2 pr-4 text-right">p95</th>
                  <th className="py-2 pr-4 text-right">p99</th>
                  <th className="py-2 text-right">TTFT p95</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {(latency?.models || []).map(m => (
                  <tr key={m.model}>
                    <td className="py-2 pr-4 font-mono text-xs text-ink">{m.model}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink-mute">{m.calls}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink">{fmtMs(m.latency_ms.p50)}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink">{fmtMs(m.latency_ms.p95)}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink">{fmtMs(m.latency_ms.p99)}</td>
                    <td className="py-2 text-right font-mono text-xs text-ink-mute">{fmtMs(m.ttft_ms.p95)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ChartState>
      </ChartCard>
    </div>
  );
}
```

- [ ] **Step 4: Build check**

Run from `resume-optimizer/frontend/`: `npm run build`
Expected: vite build completes with no errors (warnings about chunk size are pre-existing).

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx resume-optimizer/frontend/src/pages/admin/AdminLayout.jsx resume-optimizer/frontend/src/main.jsx resume-optimizer/frontend/src/pages/admin/Observability.jsx
git commit -m "feat: admin AI health tiles and observability page (trend + latency)"
```

---

### Task 6: Frontend — errors panel, trace waterfall, PipelineRuns link

**Files:**
- Modify: `resume-optimizer/frontend/src/pages/admin/Observability.jsx`
- Modify: `resume-optimizer/frontend/src/pages/admin/PipelineRuns.jsx`

**Interfaces:**
- Consumes: `/admin/observability/errors`, `/trace` (Task 4 shapes); Task 5's page; `RunStatusBadge` from adminUi.
- Produces: `/admin/observability?job_id=<id>` deep-link contract (PipelineRuns uses it).

- [ ] **Step 1: Extend Observability.jsx**

1. Extend imports: `import { useSearchParams } from 'react-router-dom';` and add `RunStatusBadge` to the adminUi import.
2. Add state + fetch in the component:

```jsx
  const [errors, setErrors] = useState(null);
  const [trace, setTrace] = useState(null);
  const [traceQuery, setTraceQuery] = useState('');
  const [traceError, setTraceError] = useState(null);
  const [searchParams] = useSearchParams();

  async function loadTrace(params) {
    setTraceError(null);
    setTrace(null);
    try {
      const r = await client.get('/admin/observability/trace', { params });
      setTrace(r.data);
    } catch (e) {
      setTraceError(e.response?.data?.detail || e.message);
    }
  }

  useEffect(() => {
    const jobId = searchParams.get('job_id');
    if (jobId) {
      setTraceQuery(jobId);
      loadTrace({ job_id: jobId });
    }
  }, [searchParams]);
```

3. Add `client.get('/admin/observability/errors', { params: { days: Math.min(days, 90) } }).then(r => setErrors(r.data)),` to the existing `Promise.allSettled` array.
4. Add a lookup submit helper (UUIDs go to job_id, anything else to trace_id):

```jsx
  function submitTrace(e) {
    e.preventDefault();
    const q = traceQuery.trim();
    if (!q) return;
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(q);
    loadTrace(isUuid ? { job_id: q } : { trace_id: q });
  }
```

5. Append these two sections before the closing `</div>` of the page:

```jsx
      <ChartCard title="Errors by type">
        <ChartState isLoading={loading} empty={!errors?.breakdown?.length}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-faint uppercase tracking-wide">
                  <th className="py-2 pr-4">Type</th>
                  <th className="py-2 pr-4">Model</th>
                  <th className="py-2 pr-4 text-right">Count</th>
                  <th className="py-2 pr-4 text-right">Code</th>
                  <th className="py-2 text-right">Last seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {(errors?.breakdown || []).map((b, i) => (
                  <tr key={i}>
                    <td className="py-2 pr-4 text-err font-mono text-xs">{b.error_type}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-ink-mute">{b.model}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink">{b.count}</td>
                    <td className="py-2 pr-4 text-right font-mono text-xs text-ink-mute">{b.sample_error_code || '—'}</td>
                    <td className="py-2 text-right text-xs text-ink-faint">{new Date(b.last_seen).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(errors?.recent || []).length > 0 && (
            <div className="mt-4">
              <p className="text-xs text-ink-faint uppercase tracking-wide mb-2">Recent errors</p>
              <ul className="divide-y divide-line/60">
                {errors.recent.slice(0, 10).map((r, i) => (
                  <li key={i} className="py-2 flex items-center gap-3 text-xs">
                    <span className="text-ink-faint w-32 shrink-0">{new Date(r.created_at).toLocaleString()}</span>
                    <span className="text-err font-mono">{r.error_type}</span>
                    <span className="text-ink-mute font-mono truncate flex-1">{r.call_kind || '—'} · {r.model}</span>
                    {(r.job_id || r.trace_id) && (
                      <button
                        onClick={() => { const q = r.job_id || r.trace_id; setTraceQuery(q); loadTrace(r.job_id ? { job_id: q } : { trace_id: q }); }}
                        className="text-primary hover:underline shrink-0"
                      >
                        trace →
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </ChartState>
      </ChartCard>

      <ChartCard title="Trace waterfall">
        <form onSubmit={submitTrace} className="flex gap-2 mb-4">
          <input
            value={traceQuery}
            onChange={e => setTraceQuery(e.target.value)}
            placeholder="Paste a job id (UUID) or trace id"
            className="flex-1 bg-surface-2 border border-line rounded-lg px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint"
          />
          <button type="submit" className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-accent-soft text-primary">
            Look up
          </button>
        </form>
        {traceError && <p className="text-sm text-err mb-2">{String(traceError)}</p>}
        {trace && (
          <div className="space-y-1.5">
            {trace.job && (
              <p className="text-xs text-ink-faint mb-2 flex items-center gap-2">
                Job: <RunStatusBadge status={trace.job.status} />
                {trace.job.error_message && <span className="text-err truncate">{trace.job.error_message}</span>}
              </p>
            )}
            {(() => {
              const total = Math.max(...trace.calls.map(c => c.offset_ms + (c.latency_ms || 0)), 1);
              return trace.calls.map((c, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="w-36 truncate text-ink-mute">{c.call_kind || 'call'}</span>
                  <div className="flex-1 relative h-4 bg-surface-2 rounded">
                    <div
                      className="absolute h-4 rounded"
                      style={{
                        left: `${(c.offset_ms / total) * 100}%`,
                        width: `${Math.max(((c.latency_ms || 0) / total) * 100, 0.5)}%`,
                        background: c.status === 'error' ? CHART.red : CHART.green,
                      }}
                      title={`${c.model} · ${fmtMs(c.latency_ms)} · $${(c.cost_usd || 0).toFixed(4)}${c.error_type ? ' · ' + c.error_type : ''}${c.finish_reason ? ' · ' + c.finish_reason : ''}`}
                    />
                  </div>
                  <span className="w-16 text-right font-mono text-ink-faint">{fmtMs(c.latency_ms)}</span>
                </div>
              ));
            })()}
          </div>
        )}
      </ChartCard>
```

- [ ] **Step 2: PipelineRuns link**

In `PipelineRuns.jsx`: ensure `Link` is imported from `react-router-dom` (add it to the existing import if absent), then add to each run row's actions/cells (match the surrounding markup — place next to the existing per-row detail control):

```jsx
<Link to={`/admin/observability?job_id=${r.id}`} className="text-xs text-primary hover:underline shrink-0">LLM calls</Link>
```

(`r` is the row variable in the existing map — adapt the name to the actual one in the file.)

- [ ] **Step 3: Build check**

Run from `resume-optimizer/frontend/`: `npm run build`
Expected: completes with no errors.

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/frontend/src/pages/admin/Observability.jsx resume-optimizer/frontend/src/pages/admin/PipelineRuns.jsx
git commit -m "feat: admin error analytics and LLM trace waterfall"
```

---

### Task 7: Full-suite verification + push

**Files:** none (verification only; fix regressions if found).

- [ ] **Step 1: Run the full backend suite**

From `resume-optimizer/backend/`:
`/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -30`

- [ ] **Step 2: Compare against the baseline**

Expected: ~447 passed (428 baseline + ~19 new) / 18 failed, every failure mapping to the known pre-existing buckets (Global Constraints). Any NEW failure: re-run that file in isolation; if it fails in isolation it is a regression — fix it before pushing (small fixes inline; report if structural).

- [ ] **Step 3: Frontend build sanity + push**

```bash
cd resume-optimizer/frontend && npm run build && cd ../..
git push origin claude/effort-estimation-m4a4ep
git status -sb | head -1
```
Expected: build clean; push succeeds; branch in sync with origin.
