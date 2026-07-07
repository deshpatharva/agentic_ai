# Review-Findings Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 10 verified findings from the 2026-07-06 deep review (spec: `resume-optimizer/docs/superpowers/specs/2026-07-06-review-findings-fixes-design.md`): rate-limiter port bug, SQLite-fatal migration, chat session bricking, unconfirmed paid launches, quota-refund holes, swallowed LLM errors, lost pre-opt edits, and hardcoded cache-savings pricing.

**Architecture:** Backend-only changes to a FastAPI + SQLAlchemy(async) + Alembic + LiteLLM app. The chat co-pilot gains a confirm-before-acting step (`_pending_confirm` in session context) and read-time job-status recovery; quota reservations stamp `pipeline_jobs.quota_reserved_on` so refunds hit the right daily counter row; cache savings are priced from LiteLLM's pricing map with the provider table as fallback.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async (aiosqlite locally / Postgres in prod), Alembic, slowapi, LiteLLM, pytest + pytest-asyncio (auto mode via pytest.ini).

## Global Constraints

- **Repo root:** `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai`. All backend paths below are relative to `resume-optimizer/backend/`. Work on branch `claude/effort-estimation-m4a4ep`. Do not push until the final task.
- **Test runner (WSL → Windows venv):** run from `resume-optimizer/backend/`:
  `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/<file> -q`
  The WSL system python lacks the deps. Bash `VAR=x` env prefixes do NOT cross the WSL→Windows boundary — set env vars INSIDE test files via `os.environ.setdefault(...)` before importing app modules (existing tests all do this).
- **Console is cp1252:** never put non-ASCII characters (❌, arrows, quotes) in test assertion literals or test output. Assert on ASCII substrings like `"Sorry"` instead.
- **Known-failure baseline (2026-07-06, before this plan):** 391 passed / 24 failed. The 24 are pre-existing: `test_migrations` (3, SQLite ALTER without batch mode), `test_chat_agent` + `test_pr7_edit_resume` (prompt-string drift + cp1252 mojibake), `test_auto_profile` (7, mocks non-existent `main._score_profiles`), `test_chat_sessions` (2), `test_optimizer_improvements`, `test_pipeline_integration`. Tasks 2 and 8 are EXPECTED to flip some of these to passing. No task may introduce a NEW failure.
- **Stay in scope:** only the 10 findings. The 12 confirmed cleanup findings (quota-SQL dedup, dead `_check_edit_quota` pair, unreachable `stream_chat` branch, etc.) are explicitly out of scope — do not delete or refactor them here, even where you edit adjacent lines.
- Commit after every task with the message given in its final step. Do not amend earlier commits.

---

### Task 1: Limiter — strip the port Azure appends to X-Forwarded-For

**Files:**
- Modify: `resume-optimizer/backend/limiter.py`
- Test: `resume-optimizer/backend/tests/test_ratelimit_key.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_strip_port(entry: str) -> str` (module-private helper in `limiter.py`); `_client_ip` behavior change: returns the bare IP for `"IP:port"` and `"[IPv6]:port"` XFF entries.

- [ ] **Step 1: Write the failing tests**

Append to `resume-optimizer/backend/tests/test_ratelimit_key.py` (it already defines `_make_req` at line 16 — reuse it):

```python
def test_strips_port_azure_format():
    # Azure App Service's front end appends the client as 'IP:port'.
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="203.0.113.9:54321")) == "203.0.113.9"


def test_strips_port_multi_entry():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="6.6.6.6, 203.0.113.9:49152")) == "203.0.113.9"


def test_port_varies_but_bucket_is_stable():
    from limiter import _client_ip
    a = _client_ip(_make_req(xff="203.0.113.9:54321"))
    b = _client_ip(_make_req(xff="203.0.113.9:54988"))
    assert a == b == "203.0.113.9"


def test_bracketed_ipv6_with_port():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="[2001:db8::1]:8080")) == "2001:db8::1"


def test_bare_ipv6_untouched():
    from limiter import _client_ip
    assert _client_ip(_make_req(xff="2001:db8::1")) == "2001:db8::1"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run (from `resume-optimizer/backend/`):
`/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_ratelimit_key.py -q`
Expected: the 5 new tests FAIL (e.g. `assert '203.0.113.9:54321' == '203.0.113.9'`); the 6 existing tests still PASS.

- [ ] **Step 3: Implement `_strip_port`**

In `resume-optimizer/backend/limiter.py`, add the helper above `_client_ip` and use it. The full new file content:

```python
from slowapi import Limiter


def _strip_port(entry: str) -> str:
    """Normalize an XFF entry to a bare IP.

    Azure App Service's front end appends the client as 'IP:port' — the ephemeral
    port would otherwise mint a fresh rate-limit bucket per TCP connection and
    silently disable every per-IP limit. Handles bracketed IPv6 ('[2001:db8::1]:8080')
    and 'IPv4:port'; a bare IPv6 (2+ colons, no brackets) or bare IPv4 (no colon)
    passes through untouched.
    """
    if entry.startswith("["):
        return entry[1:].split("]", 1)[0]
    if entry.count(":") == 1:
        return entry.split(":", 1)[0]
    return entry


def _client_ip(request) -> str:
    """Rate-limit key: the real client IP, resistant to X-Forwarded-For spoofing.

    On Azure App Service the platform front-end appends the true client IP as the
    LAST entry of X-Forwarded-For (standard XFF: each proxy appends the address it
    received the request from). Entries a client prepends to forge a fresh bucket
    sit to the left and are ignored. Falls back to the socket peer when the header
    is absent (local/dev). This must NOT trust the leftmost entry — that is exactly
    the value an attacker controls.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return _strip_port(parts[-1])
    client = getattr(request, "client", None)
    if client and client.host:
        return client.host
    return "127.0.0.1"


limiter = Limiter(key_func=_client_ip)
```

- [ ] **Step 4: Run the full test file — all pass**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_ratelimit_key.py -q`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/limiter.py resume-optimizer/backend/tests/test_ratelimit_key.py
git commit -m "fix: strip port from XFF rate-limit key (Azure appends IP:port)"
```

---

### Task 2: Migration 0022 — dialect-portable column check + batch rename

**Files:**
- Modify: `resume-optimizer/backend/alembic/versions/0022_rename_metadata_to_meta.py`

**Interfaces:**
- Consumes: the inspector pattern from `alembic/versions/0013_*.py` (`sa.inspect(conn).get_columns`).
- Produces: `alembic upgrade head` succeeds on SQLite.

- [ ] **Step 1: Reproduce the failure**

From `resume-optimizer/backend/`, run a fresh-SQLite upgrade (env var must be set inside the process — WSL prefixes don't reach the Windows python):

```bash
rm -f ./test_migrate_local.db
/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -c "import os; os.environ['DATABASE_URL']='sqlite+aiosqlite:///./test_migrate_local.db'; from alembic.config import main; main(argv=['upgrade','head'])"
```
Expected: FAILS at revision 0022 with `no such table: information_schema.columns`.

- [ ] **Step 2: Rewrite `_column_exists` and the rename**

Replace the body of `resume-optimizer/backend/alembic/versions/0022_rename_metadata_to_meta.py` from `def _column_exists` to the end of `upgrade()` with:

```python
def _column_exists(table: str, column: str) -> bool:
    # Dialect-portable (SQLite has no information_schema) — same pattern as 0013.
    conn = op.get_bind()
    cols = sa.inspect(conn).get_columns(table)
    return any(c["name"] == column for c in cols)


def upgrade() -> None:
    has_metadata = _column_exists("chat_messages", "metadata")
    has_meta = _column_exists("chat_messages", "meta")

    if has_metadata and not has_meta:
        # batch_alter_table so the rename works on SQLite (no native ALTER RENAME
        # COLUMN through Alembic's default path); on Postgres it's a plain ALTER.
        with op.batch_alter_table("chat_messages") as batch_op:
            batch_op.alter_column("metadata", new_column_name="meta")
    elif not has_metadata and not has_meta:
        op.add_column(
            "chat_messages",
            sa.Column("meta", sa.JSON(), nullable=True),
        )
```

Keep the module docstring, imports, revision identifiers, and `downgrade()` unchanged.

- [ ] **Step 3: Verify the upgrade now succeeds**

```bash
rm -f ./test_migrate_local.db
/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -c "import os; os.environ['DATABASE_URL']='sqlite+aiosqlite:///./test_migrate_local.db'; from alembic.config import main; main(argv=['upgrade','head'])"
rm -f ./test_migrate_local.db
```
Expected: completes through the latest revision with no traceback.

- [ ] **Step 4: Run the migration test file**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_migrations.py -q`
Expected: improvement over the known baseline (3 pre-existing failures were "SQLite can't ALTER TABLE without batch mode"). Record the counts; any test still failing must be failing for a pre-existing reason, not a new one.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0022_rename_metadata_to_meta.py
git commit -m "fix: make migration 0022 SQLite-portable (inspector + batch rename)"
```

---

### Task 3: Migration 0026 + model column `quota_reserved_on`

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0026_add_pipeline_job_quota_reserved_on.py`
- Modify: `resume-optimizer/backend/db/models.py` (PipelineJob, around line 105)

**Interfaces:**
- Consumes: revision `"0025"` as `down_revision` (verify: `grep '^revision' resume-optimizer/backend/alembic/versions/0025_*.py` must print `revision = "0025"`; if it differs, use the printed value).
- Produces: `PipelineJob.quota_reserved_on: Column(Date, nullable=True)` — Task 4 reads and writes it.

- [ ] **Step 1: Write the migration**

Create `resume-optimizer/backend/alembic/versions/0026_add_pipeline_job_quota_reserved_on.py`:

```python
"""add pipeline_jobs.quota_reserved_on

The daily-run reservation increments the counter row for the date the
reservation is made (date.today() at claim time), but the refund was attributed
to created_at — a different calendar day for prepare-Monday/run-Tuesday flows
and error-job retries, so the refund silently no-oped. Stamping the reservation
date on the job lets the refund target the exact row the reservation took.

NULL means "reserved before this column existed" — refunds for those rows fall
back to created_at, matching the old behavior.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("quota_reserved_on", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "quota_reserved_on")
```

- [ ] **Step 2: Add the model column**

In `resume-optimizer/backend/db/models.py`, first check the SQLAlchemy import line (`grep -n "^from sqlalchemy import" resume-optimizer/backend/db/models.py`) and add `Date` to it if absent. Then in `PipelineJob`, directly below the existing `quota_refunded` column (which carries its own comment), add:

```python
    # Calendar date the run's quota slot was reserved (date.today() at claim
    # time). Refunds decrement this exact daily_usage_counters row; NULL means
    # pre-0026 legacy — refund falls back to created_at.
    quota_reserved_on = Column(Date, nullable=True)
```

- [ ] **Step 3: Verify migration runs and model imports**

```bash
rm -f ./test_migrate_local.db
/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -c "import os; os.environ['DATABASE_URL']='sqlite+aiosqlite:///./test_migrate_local.db'; from alembic.config import main; main(argv=['upgrade','head'])"
rm -f ./test_migrate_local.db
/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -c "import os; os.environ.setdefault('JWT_SECRET','x'*32); from db.models import PipelineJob; print(PipelineJob.quota_reserved_on is not None)"
```
Expected: upgrade completes; second command prints `True`.

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0026_add_pipeline_job_quota_reserved_on.py resume-optimizer/backend/db/models.py
git commit -m "feat: add pipeline_jobs.quota_reserved_on for exact refund dating"
```

---

### Task 4: Quota — stamp reservations, reset the refund flag, refund the stamped date

**Files:**
- Modify: `resume-optimizer/backend/auth/dependencies.py` (`reserve_run_quota`, line 148)
- Modify: `resume-optimizer/backend/main.py` (`_refund_job_quota` line 101, `_reap_once` line 151, `run_pipeline` reserve block lines 409–426, the pipeline-task refund call near line 1288)
- Modify: `resume-optimizer/backend/chat/router.py` (`_launch_and_stream`, line 330)
- Modify: `resume-optimizer/backend/chat/handoff.py` (`fire_optimizer` job insert, ~line 111)
- Test: `resume-optimizer/backend/tests/test_quota_reserved_date.py` (new)

**Interfaces:**
- Consumes: `PipelineJob.quota_reserved_on` from Task 3.
- Produces:
  - `reserve_run_quota(user: User, db: AsyncSession, on_date: date | None = None) -> bool` (backward compatible — existing callers pass nothing).
  - `_refund_job_quota(job_id, user_id, reserved_on, created_at, db) -> None` — NEW third parameter `reserved_on` (a `datetime.date` or None). All callers updated in this task.
  - `fire_optimizer(user, session, handoff, reserved_on: date | None = None)` — stamps the job row at insert.

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_quota_reserved_date.py`:

```python
"""Refunds must decrement the daily counter row the reservation incremented.

Locks in the two refund fixes: (a) reserve_run_quota(on_date=...) + the
quota_reserved_on stamp keep reservation and refund on the same calendar row
even across midnight / prepare-then-run-later flows; (b) resetting
quota_refunded=False when a job is re-reserved re-arms the refund for retries.
"""

import os
import sys
import uuid
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_quota_date.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest_asyncio
from sqlalchemy import text


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_user(daily_uploads: int = 5):
    from db.models import User, PlanType, PlanLimit
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"qdate-{uuid.uuid4().hex[:8]}@test.com",
            password_hash="x",
            plan=PlanType.free,
        )
        db.add(user)
        existing = await db.get(PlanLimit, "free")
        if not existing:
            db.add(PlanLimit(
                plan="free", daily_uploads=daily_uploads, daily_edits=5,
                max_stored_resumes=1, job_scraping_enabled=False, price_cents=0,
            ))
        await db.commit()
        await db.refresh(user)
        return user


async def _runs_on(user_id, day: date) -> int:
    from db.session import AsyncSessionLocal
    uid_hex = uuid.UUID(str(user_id)).hex
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT runs FROM daily_usage_counters WHERE user_id = :uid AND date = :d"),
            {"uid": uid_hex, "d": day.isoformat()},
        )
        got = row.scalar()
        return int(got) if got is not None else 0


async def _seed_counter(user_id, day: date, runs: int) -> None:
    from db.session import AsyncSessionLocal
    uid_hex = uuid.UUID(str(user_id)).hex
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("INSERT INTO daily_usage_counters (user_id, date, runs, edits) "
                 "VALUES (:uid, :d, :runs, 0)"),
            {"uid": uid_hex, "d": day.isoformat(), "runs": runs},
        )
        await db.commit()


async def _make_job(user_id, reserved_on, refunded: bool):
    from db.models import PipelineJob, JobStatus
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        job = PipelineJob(
            user_id=user_id,
            resume_text="resume body",
            status=JobStatus.error,
            quota_reserved_on=reserved_on,
            quota_refunded=refunded,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id, job.created_at


async def test_reserve_on_date_targets_that_day(db_tables):
    from auth.dependencies import reserve_run_quota
    from db.session import AsyncSessionLocal
    user = await _make_user()
    yesterday = date.today() - timedelta(days=1)
    async with AsyncSessionLocal() as db:
        assert await reserve_run_quota(user, db, on_date=yesterday) is True
    assert await _runs_on(user.id, yesterday) == 1
    assert await _runs_on(user.id, date.today()) == 0


async def test_refund_targets_reserved_on_row(db_tables):
    from main import _refund_job_quota
    from db.session import AsyncSessionLocal
    user = await _make_user()
    yesterday = date.today() - timedelta(days=1)
    await _seed_counter(user.id, yesterday, runs=1)
    job_id, created_at = await _make_job(user.id, reserved_on=yesterday, refunded=False)
    async with AsyncSessionLocal() as db:
        await _refund_job_quota(job_id, user.id, yesterday, created_at, db)
    assert await _runs_on(user.id, yesterday) == 0


async def test_refund_is_idempotent(db_tables):
    from main import _refund_job_quota
    from db.session import AsyncSessionLocal
    user = await _make_user()
    yesterday = date.today() - timedelta(days=1)
    await _seed_counter(user.id, yesterday, runs=1)
    job_id, created_at = await _make_job(user.id, reserved_on=yesterday, refunded=False)
    async with AsyncSessionLocal() as db:
        await _refund_job_quota(job_id, user.id, yesterday, created_at, db)
        await _refund_job_quota(job_id, user.id, yesterday, created_at, db)
    assert await _runs_on(user.id, yesterday) == 0  # not -1: second call no-ops


async def test_reset_flag_rearms_refund_for_retry(db_tables):
    """A job already refunded once (quota_refunded=True) must be refundable again
    after re-reservation resets the flag — the finding-6 retry hole."""
    from main import _refund_job_quota
    from db.models import PipelineJob
    from db.session import AsyncSessionLocal
    from sqlalchemy import update
    user = await _make_user()
    today = date.today()
    await _seed_counter(user.id, today, runs=1)
    job_id, created_at = await _make_job(user.id, reserved_on=None, refunded=True)
    async with AsyncSessionLocal() as db:
        # What run_pipeline now does after every successful reservation:
        await db.execute(
            update(PipelineJob).where(PipelineJob.id == job_id)
            .values(quota_reserved_on=today, quota_refunded=False)
        )
        await db.commit()
        await _refund_job_quota(job_id, user.id, today, created_at, db)
    assert await _runs_on(user.id, today) == 0


async def test_legacy_job_falls_back_to_created_at(db_tables):
    from main import _refund_job_quota
    from db.session import AsyncSessionLocal
    user = await _make_user()
    job_id, created_at = await _make_job(user.id, reserved_on=None, refunded=False)
    # created_at is one day old (see _make_job) — seed that local calendar day.
    from auth.dependencies import _counter_date_for
    legacy_day = date.fromisoformat(_counter_date_for(created_at))
    await _seed_counter(user.id, legacy_day, runs=1)
    async with AsyncSessionLocal() as db:
        await _refund_job_quota(job_id, user.id, None, created_at, db)
    assert await _runs_on(user.id, legacy_day) == 0
```

- [ ] **Step 2: Run to verify failures**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_quota_reserved_date.py -q`
Expected: FAIL — `reserve_run_quota` rejects the `on_date` kwarg (TypeError) and `_refund_job_quota` rejects 5 positional args.

- [ ] **Step 3: Implement `reserve_run_quota(on_date=...)`**

In `resume-optimizer/backend/auth/dependencies.py`:
1. Confirm `date` is already imported (`from datetime import date` appears near the top — `_counter_date_for` uses it).
2. Change the signature at line 148 and the date line at 163:

```python
async def reserve_run_quota(user: User, db: AsyncSession, on_date: date | None = None) -> bool:
```

and replace `today_str = date.today().isoformat()` with:

```python
    today_str = (on_date or date.today()).isoformat()
```

Append to the docstring's final paragraph:

```
    on_date lets the caller pin the reservation to the date it will also stamp on
    the job (quota_reserved_on), so reservation, stamp, and refund agree even if
    midnight passes between those statements.
```

3. Do NOT touch `reserve_edit_quota` / `refund_edit_quota` / `refund_run_quota` — out of scope.

- [ ] **Step 4: Implement the refund + reaper changes in `main.py`**

1. Add `date` to main.py's datetime import (`grep -n "from datetime import" resume-optimizer/backend/main.py`, extend that line with `date`).
2. Replace `_refund_job_quota` (lines 101–120) with:

```python
async def _refund_job_quota(job_id, user_id, reserved_on, created_at, db: AsyncSession) -> None:
    """Idempotently refund the run reserved for a job.

    Both the failing pipeline task and the stuck-job reaper can reach the same
    job; the atomic quota_refunded flip ensures exactly one of them decrements
    the counter. The refund targets the reservation date stamped on the job
    (quota_reserved_on) so it decrements the exact daily counter row the
    reservation incremented; legacy rows (NULL stamp, pre-0026) fall back to
    created_at as before.
    """
    result = await db.execute(
        update(PipelineJob)
        .where(PipelineJob.id == job_id, PipelineJob.quota_refunded.is_(False))
        .values(quota_refunded=True)
    )
    if result.rowcount != 1:
        await db.commit()  # already refunded by the other path — nothing to do
        return
    if user_id is not None:
        run_date = reserved_on.isoformat() if reserved_on else _counter_date_for(created_at)
        await refund_run_quota(str(user_id), db, run_date=run_date)
    else:
        await db.commit()
```

3. In `_reap_once` (line 151): change the capture tuple and the refund loop —
   `reaped.append((job.id, job.user_id, job.created_at))` becomes
   `reaped.append((job.id, job.user_id, job.quota_reserved_on, job.created_at))`, and

```python
    for job_id, user_id, reserved_on, created_at in reaped:
        try:
            await _refund_job_quota(job_id, user_id, reserved_on, created_at, db)
```

4. Find every remaining `_refund_job_quota(` caller: `grep -rn "_refund_job_quota(" resume-optimizer/backend/`. The pipeline-task error path (near line 1288) currently passes `(job_row.id, job_row.user_id, job_row.created_at, db)` — change to `(job_row.id, job_row.user_id, job_row.quota_reserved_on, job_row.created_at, db)`. Update any other caller the grep reveals the same way.

5. In `run_pipeline` (lines 409–426), replace the reserve block with:

```python
    # Reserve the run slot only after winning the claim — the single authoritative
    # limit check. On limit, revert the job to pending so a retry works, and return
    # the one canonical 429.
    today = date.today()
    if not await reserve_run_quota(current_user, db, on_date=today):
        await db.execute(
            update(PipelineJob).where(PipelineJob.id == job_uuid).values(status=JobStatus.pending)
        )
        await db.commit()
        raise HTTPException(
            status_code=429,
            detail={
                "error": "limit_reached",
                "plan": current_user.plan.value,
                "upgrade_message": "You've reached your daily limit. Upgrade to Pro for more runs/day.",
            },
        )

    # Stamp the reservation on the job and re-arm the refund: the refund targets
    # quota_reserved_on's counter row, and a retried failed job (whose first
    # failure already flipped quota_refunded=True) must be refundable again.
    await db.execute(
        update(PipelineJob)
        .where(PipelineJob.id == job_uuid)
        .values(quota_reserved_on=today, quota_refunded=False)
    )
    await db.commit()
```

- [ ] **Step 5: Stamp the chat-launched path**

1. `resume-optimizer/backend/chat/handoff.py`: add `date` to its datetime import; change the `fire_optimizer` signature (line 55) to

```python
async def fire_optimizer(
    user, session, handoff: dict, reserved_on: date | None = None
):
```

(keep the existing return annotation/docstring; check the exact current signature line with `sed -n 55,60p resume-optimizer/backend/chat/handoff.py` and only add the parameter), and add `quota_reserved_on=reserved_on,` to the `PipelineJob(...)` constructor (~line 112, alongside `status=JobStatus.running`).

2. `resume-optimizer/backend/chat/router.py` `_launch_and_stream` (line 330): add `date` to the router's datetime import (line 17), then:

```python
    today = date.today()
    async with AsyncSessionLocal() as qdb:
        reserved_ok = await reserve_run_quota(current_user, qdb, on_date=today)
```

and change the fire call to `job_id, sse_token = await fire_optimizer(current_user, session, handoff_payload, reserved_on=today)`.

3. Confirm no other `fire_optimizer(` callers exist: `grep -rn "fire_optimizer(" resume-optimizer/backend/ --include=*.py` — only the definition and `_launch_and_stream` should appear (plus imports).

- [ ] **Step 6: Run the new tests and the neighboring quota suites**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_quota_reserved_date.py tests/test_quota_reservation.py tests/test_quota_cluster.py -q`
Expected: all pass (the two existing quota files passed at baseline and must stay green).

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/auth/dependencies.py resume-optimizer/backend/main.py resume-optimizer/backend/chat/router.py resume-optimizer/backend/chat/handoff.py resume-optimizer/backend/tests/test_quota_reserved_date.py
git commit -m "fix: stamp reservation date on jobs and re-arm refunds on retry"
```

---

### Task 5: Chat — real error events for LLM failures (keep fallback for empty)

**Files:**
- Modify: `resume-optimizer/backend/chat/router.py` (`event_generator`, lines 480–521)
- Test: `resume-optimizer/backend/tests/test_chat_error_events.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: SSE contract — when both LLM attempts raise, the stream yields `final` ("Sorry — I hit an error…"), then `error`, then `done`, and persists NO assistant ChatMessage. `fallback_response` persists only for empty-but-successful responses.

- [ ] **Step 1: Write the failing test**

Create `resume-optimizer/backend/tests/test_chat_error_events.py`:

```python
"""A provider outage must surface an SSE 'error' event — not a canned reply
persisted to history as if the model said it (deep-review finding 8)."""

import os
import sys
import types
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-for-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_chat_err.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import httpx
import pytest_asyncio
from sqlalchemy import select


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_user():
    from db.models import User, PlanType
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"cerr-{uuid.uuid4().hex[:8]}@test.com",
            password_hash="x",
            plan=PlanType.free,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest_asyncio.fixture
async def client(db_tables):
    from main import app
    from chat.dependencies import require_complete_profile
    from db.session import get_db, AsyncSessionLocal

    user = await _make_user()

    async def _override_user():
        return user

    async def _override_db():
        async with AsyncSessionLocal() as s:
            yield s

    app.dependency_overrides[require_complete_profile] = _override_user
    app.dependency_overrides[get_db] = _override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _assistant_messages():
    from db.models import ChatMessage
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        )).scalars().all()
        return rows


async def test_llm_exception_yields_error_event_and_persists_nothing(client, monkeypatch):
    from chat import router as chat_router

    async def _boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(chat_router, "complete_with_tools", _boom)

    # No JD in the message -> AWAITING_JD phase -> tools exist -> complete_with_tools path.
    resp = await client.post("/optimize/chat", json={"message": "hello there"})
    body = resp.text
    assert "event: error" in body
    assert "Sorry" in body
    assert await _assistant_messages() == []  # nothing persisted as if the model spoke


async def test_empty_response_still_uses_fallback_not_error(client, monkeypatch):
    from chat import router as chat_router

    async def _empty(*args, **kwargs):
        return {
            "message": types.SimpleNamespace(content="", tool_calls=None),
            "input_tokens": 1,
            "output_tokens": 0,
        }

    monkeypatch.setattr(chat_router, "complete_with_tools", _empty)

    resp = await client.post("/optimize/chat", json={"message": "hello there"})
    body = resp.text
    assert "event: error" not in body
    rows = await _assistant_messages()
    assert len(rows) == 1  # the deterministic fallback is a real (persisted) reply
```

Note: `message_text` / `parse_tool_calls` live in `chat/tools.py`. If the `SimpleNamespace(content="", tool_calls=None)` stub trips either helper, read those two functions and match the stub to the attribute shape they read — keep the assertions unchanged.

- [ ] **Step 2: Run to verify the first test fails**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_chat_error_events.py -q`
Expected: `test_llm_exception_yields_error_event_and_persists_nothing` FAILS (today the exception is swallowed, `fallback_response` is persisted, and no `error` event appears). The empty-response test may already pass.

- [ ] **Step 3: Restructure the attempt/retry block**

In `resume-optimizer/backend/chat/router.py`, replace lines 480–521 (from `# First attempt` through the `display = fallback_response(phase, ctx)` block) with:

```python
        # Attempt loop: one retry covers both a raised call and an empty result.
        # An exception on the final attempt is a real outage — surface it as an
        # SSE error (like main did) instead of persisting a canned reply the
        # model never produced. fallback_response stays reserved for calls that
        # SUCCEEDED but returned nothing.
        llm_exc = None
        for attempt in (1, 2):
            llm_exc = None
            try:
                if phase_tools:
                    result = await complete_with_tools(window, MODEL_CHAT_AGENT, phase_tools)
                    message = result["message"]
                    display = message_text(message).strip()
                    tool_calls = parse_tool_calls(message)
                    usage = {"input_tokens": result.get("input_tokens", 0),
                             "output_tokens": result.get("output_tokens", 0)}
                else:
                    # No tools available (e.g. OPTIMIZING) — stream text response
                    chunks = []
                    async for chunk in stream_chat(window, MODEL_CHAT_AGENT):
                        if chunk["type"] == "token":
                            chunks.append(chunk["text"])
                            yield {"event": "token", "data": json.dumps({"text": chunk["text"]})}
                        elif chunk["type"] == "usage":
                            usage = {"input_tokens": chunk.get("input_tokens", 0),
                                     "output_tokens": chunk.get("output_tokens", 0)}
                    display = "".join(chunks).strip()
            except Exception as exc:
                llm_exc = exc
                _logger.exception(
                    "chat completion failed for session %s (attempt %d)", session_id_str, attempt
                )
            if display or tool_calls:
                break
            if attempt == 1:
                _logger.info(
                    "chat: %s for session %s, retrying once",
                    "error" if llm_exc else "empty response", session_id_str,
                )

        if llm_exc is not None:
            yield {"event": "final", "data": json.dumps({"content": "❌ Sorry — I hit an error. Please try again."})}
            yield {"event": "error", "data": json.dumps({"message": "Agent failed — please try again."})}
            yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
            return

        # Final fallback — deterministic response based on phase
        if not display and not tool_calls:
            _logger.warning("chat: both attempts empty for session %s (phase=%s), using fallback", session_id_str, phase)
            display = fallback_response(phase, ctx)
```

(The false `temperature=0.7` log line is gone; everything after — tool-call processing, persistence — is untouched.)

- [ ] **Step 4: Run the new tests**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_chat_error_events.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/chat/router.py resume-optimizer/backend/tests/test_chat_error_events.py
git commit -m "fix: surface chat LLM failures as SSE errors instead of canned replies"
```

---

### Task 6: State machine — confirm before launching or downloading

**Files:**
- Modify: `resume-optimizer/backend/chat/state_machine.py` (`try_deterministic`, lines 56–122)
- Modify: `resume-optimizer/backend/chat/router.py` (persist context after `try_deterministic`, line 455)
- Test: `resume-optimizer/backend/tests/test_chat_confirm_flow.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - Context key contract `ctx["_pending_confirm"] = {"action": "launch" | "download", "profile_id": str}`. `try_deterministic` POPS it at entry (single-shot) and sets it on proposals; it MUTATES the `ctx` dict passed in. Task 7's recovery sets the same key.
  - Bare/fuzzy label matches return `{"action": "respond", ...}` proposals. Bare affirmations with no pending proposal return None (LLM handles them). Picker clicks unchanged.

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_chat_confirm_flow.py`:

```python
"""Confirm-before-acting: ambiguous short messages must PROPOSE paid actions,
never fire them (deep-review findings 4 and 5). Pure state-machine unit tests."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")

from chat.state_machine import (
    AWAITING_JD, JD_CAPTURED, try_deterministic,
)

PROFILES = [
    {"id": "p1", "label": "Data Engineer"},
    {"id": "p2", "label": "Software Engineer"},
]


def _jd_ctx(**extra):
    ctx = {"jd_text": "We need a data engineer with Kafka experience."}
    ctx.update(extra)
    return ctx


def test_bare_label_proposes_launch_instead_of_firing():
    ctx = _jd_ctx()
    out = try_deterministic(JD_CAPTURED, "Data Engineer", ctx, PROFILES)
    assert out["action"] == "respond"
    assert "yes" in out["response"].lower()
    assert ctx["_pending_confirm"] == {"action": "launch", "profile_id": "p1"}


def test_fuzzy_label_proposes_not_launches():
    ctx = _jd_ctx()
    out = try_deterministic(JD_CAPTURED, "data engineering", ctx, PROFILES)
    assert out["action"] == "respond"
    assert ctx["_pending_confirm"]["action"] == "launch"


def test_yes_with_pending_launch_fires():
    ctx = _jd_ctx(_pending_confirm={"action": "launch", "profile_id": "p1"})
    out = try_deterministic(JD_CAPTURED, "yes", ctx, PROFILES)
    assert out["action"] == "launch"
    assert out["profile_id"] == "p1"
    assert "_pending_confirm" not in ctx  # consumed


def test_yes_without_pending_goes_to_llm():
    # The gap-question case: "yes" may answer "do you have Kafka experience?"
    ctx = _jd_ctx(_jd_matched_profiles=[{"id": "p1", "label": "Data Engineer"}])
    out = try_deterministic(JD_CAPTURED, "yes", ctx, PROFILES)
    assert out is None


def test_other_message_clears_pending():
    ctx = _jd_ctx(_pending_confirm={"action": "launch", "profile_id": "p1"})
    out = try_deterministic(JD_CAPTURED, "actually, tell me about the gaps first", ctx, PROFILES)
    assert out is None  # goes to the LLM
    assert "_pending_confirm" not in ctx  # proposal dropped


def test_bare_label_in_awaiting_jd_proposes_download():
    ctx = {}
    out = try_deterministic(AWAITING_JD, "Software Engineer", ctx, PROFILES)
    assert out["action"] == "respond"
    assert ctx["_pending_confirm"] == {"action": "download", "profile_id": "p2"}


def test_yes_with_pending_download_fires():
    ctx = {"_pending_confirm": {"action": "download", "profile_id": "p2"}}
    out = try_deterministic(AWAITING_JD, "yes", ctx, PROFILES)
    assert out["action"] == "download"
    assert out["profile_id"] == "p2"


def test_picker_click_still_fires_instantly():
    ctx = _jd_ctx()
    out = try_deterministic(JD_CAPTURED, 'Use my "Data Engineer" profile', ctx, PROFILES)
    assert out["action"] == "launch"
    assert out["profile_id"] == "p1"
```

- [ ] **Step 2: Run to verify failures**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_chat_confirm_flow.py -q`
Expected: most FAIL (`test_picker_click_still_fires_instantly` passes; the label tests fail because today's code returns `"action": "launch"` directly).

- [ ] **Step 3: Rewrite the deterministic branches**

In `resume-optimizer/backend/chat/state_machine.py`, replace `try_deterministic` (lines 56–122) with:

```python
def try_deterministic(
    phase: str, message: str, ctx: dict, profiles: list[dict]
) -> dict | None:
    """Try to handle the input without an LLM call.

    Returns {"action": str, "response": str, ...} or None if the LLM is needed.
    MUTATES ctx: pops "_pending_confirm" at entry (proposals are single-shot) and
    sets it when returning a confirmation proposal — the router persists ctx when
    it changed.

    Actions:
      "respond"   — just send the response text, no tool call
      "launch"    — call fire_optimizer with profile_id
      "download"  — call resolve_profile_download with profile_id

    Paid or irreversible actions are never fired from ambiguous free text: a bare
    profile label PROPOSES the action into ctx["_pending_confirm"], and only an
    explicit affirmation on the very next turn executes it. A bare "yes" with no
    pending proposal falls through to the LLM, which sees the conversation and can
    tell a launch confirmation from an answer to the gap question.
    """
    text = message.strip()

    # ── Pending confirmation from the previous turn (single-shot) ────────────
    pending = ctx.pop("_pending_confirm", None)
    if pending and _AFFIRM_RE.match(text):
        profile = next((p for p in profiles if p.get("id") == pending.get("profile_id")), None)
        label = profile["label"] if profile else "selected"
        if pending.get("action") == "launch" and not ctx.get("_optimizer_launched"):
            return {
                "action": "launch",
                "profile_id": pending["profile_id"],
                "response": f'Launching the optimizer with your "{label}" profile…',
            }
        if pending.get("action") == "download":
            return {
                "action": "download",
                "profile_id": pending["profile_id"],
                "response": f'Generating your "{label}" resume as a Word document…',
            }

    # ── Profile picker click: 'Use my "Senior Data Engineer" profile' ────────
    picker_match = _PICKER_RE.match(text)
    if picker_match:
        label = picker_match.group(1)
        profile = _find_profile_by_label(label, profiles)
        if profile:
            if phase == JD_CAPTURED and ctx.get("jd_text") and not ctx.get("_optimizer_launched"):
                return {
                    "action": "launch",
                    "profile_id": profile["id"],
                    "response": f'Launching the optimizer with your "{profile["label"]}" profile now…',
                }
            return {
                "action": "download",
                "profile_id": profile["id"],
                "response": f'Generating your "{profile["label"]}" resume…',
            }

    # ── Bare profile label (e.g. user types "Senior Data Engineer") ──────────
    # Free text is ambiguous ("data engineering" may answer the gap question), so
    # a label match only PROPOSES — it must never consume quota by itself.
    if not _URL_RE.match(text) and len(text) < 120:
        profile = _find_profile_by_label(text, profiles)
        if profile:
            if phase == JD_CAPTURED and ctx.get("jd_text") and not ctx.get("_optimizer_launched"):
                ctx["_pending_confirm"] = {"action": "launch", "profile_id": profile["id"]}
                return {
                    "action": "respond",
                    "response": (
                        f'Ready to optimize with your "{profile["label"]}" profile? '
                        "Say yes to launch, or tell me anything to add first "
                        "(real experience, tools, context)."
                    ),
                }
            if phase == AWAITING_JD:
                ctx["_pending_confirm"] = {"action": "download", "profile_id": profile["id"]}
                return {
                    "action": "respond",
                    "response": (
                        f'Want me to export your "{profile["label"]}" profile as a '
                        "Word document? Say yes to download."
                    ),
                }

    # ── Optimizing phase — block input ───────────────────────────────────────
    if phase == OPTIMIZING:
        return {
            "action": "respond",
            "response": "The optimizer is still running — I'll let you know as soon as it's done.",
        }

    return None
```

Note what changed: the old auto-launch affirmation branch (`_get_recommended_profile` + `_AFFIRM_RE`, old lines 105–113) is deleted — keep the `_get_recommended_profile` function itself (Task 7 uses it).

- [ ] **Step 4: Persist context changes in the router**

In `resume-optimizer/backend/chat/router.py`, replace the two lines at 454–455:

```python
    # ── 5. Try deterministic handling first ──────────────────────────────────
    deterministic = try_deterministic(phase, body.message, ctx, profiles_list)
```

with:

```python
    # ── 5. Try deterministic handling first ──────────────────────────────────
    # Snapshot first: after JD resolution above, session.context and ctx can be
    # the SAME dict object, so comparing them post-mutation would always be
    # equal; and SQLAlchemy only detects JSON-column changes on reassignment.
    ctx_snapshot = dict(ctx)
    deterministic = try_deterministic(phase, body.message, ctx, profiles_list)

    # try_deterministic mutates ctx (_pending_confirm set/consumed/dropped) —
    # persist so the proposal survives to the next turn.
    if ctx != ctx_snapshot:
        session.context = dict(ctx)
        session.updated_at = datetime.now(timezone.utc)
        await db.commit()
```

- [ ] **Step 5: Run the new tests plus the label-match suite**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_chat_confirm_flow.py tests/test_handoff_label_match.py -q`
Expected: `test_chat_confirm_flow.py` all pass. If `test_handoff_label_match.py` asserts the OLD behavior (a bare label returning `"action": "launch"`/`"download"` directly), update those assertions to the new contract: `out["action"] == "respond"` plus `ctx["_pending_confirm"]["action"] == "launch"` (or `"download"`); tests that only exercise `_find_profile_by_label` need no change.

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/chat/state_machine.py resume-optimizer/backend/chat/router.py resume-optimizer/backend/tests/test_chat_confirm_flow.py resume-optimizer/backend/tests/test_handoff_label_match.py
git commit -m "fix: require confirmation before deterministic launch/download"
```

---

### Task 7: Chat recovery — detect failed runs at read time

**Files:**
- Modify: `resume-optimizer/backend/chat/router.py` (new helper `_check_optimizer_job` + call in `optimize_chat`; `_launch_and_stream` line ~350)
- Test: `resume-optimizer/backend/tests/test_chat_recovery.py` (new)

**Interfaces:**
- Consumes: `ctx["_pending_confirm"]` contract from Task 6; `ChatSession.job_id` (already set by `fire_optimizer` at handoff.py:135 — the spec's `_job_id` context key is unnecessary; the column is the same information, already persisted).
- Produces: `_check_optimizer_job(session, ctx, profiles_list, db) -> dict | None` in `chat/router.py` — returns None while the job is genuinely running; otherwise MUTATES ctx (clears `_optimizer_launched`, may set `last_error` / `_pending_confirm`) and returns a deterministic-result dict `{"action": "respond", "response": str}`.

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_chat_recovery.py`:

```python
"""A failed or vanished pipeline run must un-brick the chat session at read time
(deep-review finding 3): clear _optimizer_launched, offer a retry, and only claim
'still running' when the job row says so."""

import os
import sys
import types
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-for-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_chat_recovery.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest_asyncio

PROFILES = [{"id": "", "label": "Data Engineer"}]  # id filled per-test


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_job(status_name: str, profile_id=None):
    from db.models import PipelineJob, JobStatus
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        job = PipelineJob(
            user_id=None,
            profile_id=profile_id,
            resume_text="resume body",
            status=getattr(JobStatus, status_name),
            error_message="boom" if status_name == "error" else None,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def test_running_job_returns_none(db_tables):
    from chat.router import _check_optimizer_job
    from db.session import AsyncSessionLocal
    job_id = await _make_job("running")
    ctx = {"_optimizer_launched": True, "jd_text": "some jd"}
    async with AsyncSessionLocal() as db:
        out = await _check_optimizer_job(types.SimpleNamespace(job_id=job_id), ctx, PROFILES, db)
    assert out is None
    assert ctx.get("_optimizer_launched") is True  # untouched


async def test_error_job_recovers_and_offers_retry(db_tables):
    from chat.router import _check_optimizer_job
    from db.session import AsyncSessionLocal
    prof_id = uuid.uuid4()
    profiles = [{"id": str(prof_id), "label": "Data Engineer"}]
    job_id = await _make_job("error", profile_id=prof_id)
    ctx = {"_optimizer_launched": True, "jd_text": "some jd"}
    async with AsyncSessionLocal() as db:
        out = await _check_optimizer_job(types.SimpleNamespace(job_id=job_id), ctx, profiles, db)
    assert out["action"] == "respond"
    assert "failed" in out["response"]
    assert "_optimizer_launched" not in ctx
    assert ctx["_pending_confirm"] == {"action": "launch", "profile_id": str(prof_id)}
    assert ctx["last_error"] == "boom"


async def test_missing_job_recovers(db_tables):
    from chat.router import _check_optimizer_job
    from db.session import AsyncSessionLocal
    ctx = {"_optimizer_launched": True, "jd_text": "some jd"}
    async with AsyncSessionLocal() as db:
        out = await _check_optimizer_job(types.SimpleNamespace(job_id=None), ctx, [], db)
    assert out["action"] == "respond"
    assert "_optimizer_launched" not in ctx


async def test_done_job_points_to_dashboard(db_tables):
    from chat.router import _check_optimizer_job
    from db.session import AsyncSessionLocal
    job_id = await _make_job("done")
    ctx = {"_optimizer_launched": True, "jd_text": "some jd"}
    async with AsyncSessionLocal() as db:
        out = await _check_optimizer_job(types.SimpleNamespace(job_id=job_id), ctx, [], db)
    assert out["action"] == "respond"
    assert "dashboard" in out["response"].lower()
    assert "_optimizer_launched" not in ctx
    assert "_pending_confirm" not in ctx
```

- [ ] **Step 2: Run to verify failure**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_chat_recovery.py -q`
Expected: FAIL — `ImportError: cannot import name '_check_optimizer_job'`.

- [ ] **Step 3: Implement `_check_optimizer_job`**

In `resume-optimizer/backend/chat/router.py`:

1. Extend the imports: add `PipelineJob, JobStatus` to the existing `from db.models import ...` line (line 38), and add `_get_recommended_profile` to the `from chat.state_machine import ...` line (line 30).

2. Add the helper directly above `_launch_and_stream` (line 330):

```python
async def _check_optimizer_job(session, ctx: dict, profiles_list: list[dict], db) -> dict | None:
    """When the session believes a run is in flight, verify against the jobs table.

    The session context only learns about SUCCESS (last_result is written by the
    pipeline's success path) — a failed, reaped, or vanished job would otherwise
    leave the session in OPTIMIZING forever, answering every message with the
    canned "still running" line. Returns None while the job really is running;
    otherwise mutates ctx to leave OPTIMIZING and returns the deterministic reply
    for this turn (a retry proposal on failure, a dashboard pointer on
    done-without-result).
    """
    job = await db.get(PipelineJob, session.job_id) if session.job_id else None
    if job is not None and job.status in (JobStatus.running, JobStatus.pending):
        return None

    ctx.pop("_optimizer_launched", None)

    if job is not None and job.status == JobStatus.done:
        # Success landed on the job but last_result never reached this session
        # (partial write) — don't fake results; point at the canonical copy.
        return {
            "action": "respond",
            "response": "That optimization finished — check your dashboard for the results, "
                        "or paste a new job description to run again.",
        }

    ctx["last_error"] = (job.error_message if job is not None else None) or "Optimizer run failed."
    pid = str(job.profile_id) if (job is not None and job.profile_id) else None
    profile = next((p for p in profiles_list if p["id"] == pid), None)
    if profile is None:
        profile = _get_recommended_profile(ctx, profiles_list)
    if profile:
        ctx["_pending_confirm"] = {"action": "launch", "profile_id": profile["id"]}
        return {
            "action": "respond",
            "response": f'That optimization run failed and your quota was refunded. '
                        f'Say yes to retry with your "{profile["label"]}" profile.',
        }
    return {
        "action": "respond",
        "response": "That optimization run failed and your quota was refunded. "
                    "Paste a job description or pick a profile to try again.",
    }
```

3. Wire it into `optimize_chat` — the step-5 block from Task 6 becomes:

```python
    # ── 5. Try deterministic handling first ──────────────────────────────────
    # Snapshot first: after JD resolution above, session.context and ctx can be
    # the SAME dict object, so comparing them post-mutation would always be
    # equal; and SQLAlchemy only detects JSON-column changes on reassignment.
    ctx_snapshot = dict(ctx)

    # If the session believes a run is in flight, reconcile with the jobs table
    # first — a failed/reaped/vanished job must not brick the session.
    recovery = None
    if phase == OPTIMIZING:
        recovery = await _check_optimizer_job(session, ctx, profiles_list, db)

    deterministic = recovery or try_deterministic(phase, body.message, ctx, profiles_list)

    # try_deterministic/_check_optimizer_job mutate ctx (_pending_confirm,
    # _optimizer_launched, last_error) — persist so changes survive to next turn.
    if ctx != ctx_snapshot:
        session.context = dict(ctx)
        session.updated_at = datetime.now(timezone.utc)
        await db.commit()
```

(This replaces Task 6's version of the same block — the persist lines are identical; only the recovery call is new.)

- [ ] **Step 4: Run the tests**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_chat_recovery.py tests/test_chat_confirm_flow.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/chat/router.py resume-optimizer/backend/tests/test_chat_recovery.py
git commit -m "fix: un-brick chat sessions when the optimizer run failed or vanished"
```

---

### Task 8: Restore pre-optimization profile edits

**Files:**
- Modify: `resume-optimizer/backend/chat/state_machine.py` (`tools_for_phase`, lines 41–53)
- Modify: `resume-optimizer/backend/chat/agent.py` (`_PHASE_INSTRUCTIONS`, lines 32–50)
- Test: assertions appended to `resume-optimizer/backend/tests/test_chat_confirm_flow.py`

**Interfaces:**
- Consumes: `EDIT_TOOL` (already imported in state_machine.py line 12); `apply_edit`'s `profile_id` path (already implemented — no handoff changes).
- Produces: `tools_for_phase(AWAITING_JD)` and `tools_for_phase(JD_CAPTURED)` include the edit tool; agent prompts contain the literal heading `RESUME EDITS` in those phases (which `test_pr7_edit_resume.py::test_system_prompt_has_edit_guidance` greps for).

- [ ] **Step 1: Write the failing tests**

Append to `resume-optimizer/backend/tests/test_chat_confirm_flow.py`:

```python
def test_edit_tool_available_before_optimization():
    from chat.state_machine import tools_for_phase, AWAITING_JD as P_AWAIT, JD_CAPTURED as P_JD
    from chat.tools import EDIT_TOOL
    for phase in (P_AWAIT, P_JD):
        names = [t["function"]["name"] for t in tools_for_phase(phase)]
        assert EDIT_TOOL in names, f"edit tool missing in {phase}"


def test_pre_opt_prompts_document_edits():
    from chat.agent import render_system_prompt
    from chat.state_machine import AWAITING_JD as P_AWAIT, JD_CAPTURED as P_JD
    for phase in (P_AWAIT, P_JD):
        prompt = render_system_prompt({"profiles": PROFILES}, phase)
        assert "RESUME EDITS" in prompt, f"edit guidance missing in {phase} prompt"
```

- [ ] **Step 2: Run to verify failures**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_chat_confirm_flow.py -q`
Expected: the two new tests FAIL; the rest pass.

- [ ] **Step 3: Add the tool and prompt guidance**

1. `resume-optimizer/backend/chat/state_machine.py` — `tools_for_phase` becomes:

```python
def tools_for_phase(phase: str) -> list[dict]:
    if phase == AWAITING_JD:
        return [_TOOLS_BY_NAME[DOWNLOAD_TOOL], _TOOLS_BY_NAME[EDIT_TOOL]]
    if phase == JD_CAPTURED:
        return [_TOOLS_BY_NAME[LAUNCH_TOOL], _TOOLS_BY_NAME[DOWNLOAD_TOOL], _TOOLS_BY_NAME[EDIT_TOOL]]
    if phase == OPTIMIZING:
        return []
    # RESULTS_READY
    return [
        _TOOLS_BY_NAME[SAVE_TOOL],
        _TOOLS_BY_NAME[DOWNLOAD_TOOL],
        _TOOLS_BY_NAME[EDIT_TOOL],
    ]
```

2. `resume-optimizer/backend/chat/agent.py` — insert a shared guidance constant above `_PHASE_INSTRUCTIONS` (line 32) and use it in both pre-opt phases:

```python
_EDIT_GUIDANCE = """\
RESUME EDITS: to change a saved profile (e.g. "remove the objective section"), call \
edit_resume with the user's request verbatim as instruction and that profile's exact \
id as profile_id. Ask which profile they mean if it's ambiguous. Never invent experience."""
```

Then change the two dict entries:

```python
    AWAITING_JD: f"""\
The user has not provided a job description yet.
Ask for one — they can paste the text or a URL. Keep it to one sentence.
If the user asks to download a profile, call download_profile with the profile's id.
{_EDIT_GUIDANCE}""",

    JD_CAPTURED: f"""\
A job description has been captured.
YOUR TOOLS: launch_optimizer(profile_id, added_context), download_profile(profile_id), \
edit_resume(instruction, profile_id).

CONVERSATION FLOW:
1. Recommend the best-matching profile by name with one sentence on why it fits.
2. If GAPS are listed in CONTEXT, mention the 1–2 most important and ask whether the user \
has real experience (at which company, how). Ask at most once.
3. When the user confirms — "yes", "go", "run", "ok", profile picker button, or any clear \
affirmation — call launch_optimizer immediately with that profile's exact id.
- 'Use my "[label]" profile' from picker = direct selection AND confirmation, no follow-up needed.
- added_context must contain ONLY facts the user actually stated — never placeholders.
- NEVER call launch_optimizer on the same turn the JD is first captured.
{_EDIT_GUIDANCE}""",
```

(OPTIMIZING and RESULTS_READY entries stay exactly as they are.)

- [ ] **Step 4: Run the tests, including the previously-failing prompt-guidance test**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_chat_confirm_flow.py -q`
then: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_pr7_edit_resume.py -q -k system_prompt`
Expected: confirm-flow file all green; `test_system_prompt_has_edit_guidance` now PASSES (it was in the known-failure baseline). Other `test_pr7_edit_resume` failures (cp1252 mojibake) may remain — pre-existing.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/chat/state_machine.py resume-optimizer/backend/chat/agent.py resume-optimizer/backend/tests/test_chat_confirm_flow.py
git commit -m "fix: restore pre-optimization profile edits in chat"
```

---

### Task 9: Cache savings — LiteLLM pricing map first, table fallback

**Files:**
- Modify: `resume-optimizer/backend/utils/cost.py`
- Modify: `resume-optimizer/backend/admin/router.py` (`cache_efficiency`, savings line ~1033)
- Test: `resume-optimizer/backend/tests/test_cache_savings.py` (new)

**Interfaces:**
- Consumes: `DEFAULT_PROVIDER_RATES`, `litellm` (both already in `utils/cost.py`).
- Produces:
  - `cache_rates(model: str) -> tuple[float, float]` — `(input_cost_per_token, cache_read_cost_per_token)`, LiteLLM-first.
  - `estimate_cache_savings(model_cached_tokens: Iterable[tuple[str, int]]) -> float` — USD.

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_cache_savings.py`:

```python
"""Cache savings must be priced per model from LiteLLM's pricing map — the same
source resolve_cost() trusts — with DEFAULT_PROVIDER_RATES as fallback only
(deep-review finding 10; hardcoded $0.30/1M x 75% was up to 10x off)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")


def test_cache_rates_prefers_litellm(monkeypatch):
    import utils.cost as cost
    monkeypatch.setattr(
        cost.litellm, "get_model_info",
        lambda m: {"input_cost_per_token": 3e-06, "cache_read_input_token_cost": 3e-07},
    )
    inp, cached = cost.cache_rates("anthropic/some-model")
    assert inp == 3e-06
    assert cached == 3e-07


def test_cache_rates_defaults_cached_fraction_when_unpublished(monkeypatch):
    import utils.cost as cost
    monkeypatch.setattr(
        cost.litellm, "get_model_info",
        lambda m: {"input_cost_per_token": 4e-06},  # no cache_read rate published
    )
    inp, cached = cost.cache_rates("groq/some-model")
    assert inp == 4e-06
    assert cached == 4e-06 * 0.25


def test_cache_rates_falls_back_to_provider_table(monkeypatch):
    import utils.cost as cost

    def _unmapped(m):
        raise ValueError("model isn't mapped")

    monkeypatch.setattr(cost.litellm, "get_model_info", _unmapped)
    inp, cached = cost.cache_rates("deepseek/unmapped-model")
    expected_inp = cost.DEFAULT_PROVIDER_RATES["deepseek"][0] / 1_000_000
    assert inp == expected_inp
    assert cached == expected_inp * 0.25


def test_estimate_cache_savings_sums_per_model(monkeypatch):
    import utils.cost as cost
    rates = {"m1": (2e-06, 5e-07), "m2": (1e-06, 2.5e-07)}
    monkeypatch.setattr(cost, "cache_rates", lambda m: rates[m])
    got = cost.estimate_cache_savings([("m1", 1_000_000), ("m2", 2_000_000), ("m3", 0)])
    # m1: 1M * 1.5e-06 = 1.5 ; m2: 2M * 0.75e-06 = 1.5 ; m3 skipped (0 tokens)
    assert abs(got - 3.0) < 1e-9
```

- [ ] **Step 2: Run to verify failures**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_cache_savings.py -q`
Expected: FAIL — `AttributeError: module 'utils.cost' has no attribute 'cache_rates'`.

- [ ] **Step 3: Implement the helpers**

Append to `resume-optimizer/backend/utils/cost.py`:

```python
_FALLBACK_CACHED_FRACTION = 0.25


def cache_rates(model: str) -> tuple[float, float]:
    """(input_cost_per_token, cache_read_cost_per_token) for a model, in USD/token.

    LiteLLM's bundled pricing map is primary — the same source resolve_cost()
    trusts at call time, updated with the library instead of hand-maintained.
    Falls back to DEFAULT_PROVIDER_RATES when LiteLLM has no mapping, assuming
    cache reads at 25% of input when no rate is published.
    """
    try:
        info = litellm.get_model_info(model)
        inp = float(info.get("input_cost_per_token") or 0.0)
        if inp > 0:
            cached = float(info.get("cache_read_input_token_cost") or 0.0)
            return inp, cached if cached > 0 else inp * _FALLBACK_CACHED_FRACTION
    except Exception:
        pass
    provider = model.split("/", 1)[0]
    provider = {"gemini": "google"}.get(provider, provider)
    in_per_1m = DEFAULT_PROVIDER_RATES.get(provider, (0.0, 0.0))[0]
    inp = in_per_1m / 1_000_000
    return inp, inp * _FALLBACK_CACHED_FRACTION


def estimate_cache_savings(model_cached_tokens) -> float:
    """USD saved by cache reads: cached_tokens x (input_rate - cache_read_rate),
    summed per model. model_cached_tokens: iterable of (model, cached_token_count)."""
    total = 0.0
    for model, cached_tok in model_cached_tokens:
        if not cached_tok:
            continue
        inp, cached = cache_rates(model)
        total += cached_tok * (inp - cached)
    return total
```

- [ ] **Step 4: Rewire `cache_efficiency`**

In `resume-optimizer/backend/admin/router.py`:

1. Check how `utils.cost` is imported (`grep -n "utils.cost\|from utils" resume-optimizer/backend/admin/router.py`) and add `estimate_cache_savings` to that import (or add `from utils.cost import estimate_cache_savings`).
2. In `cache_efficiency` (function starts line 970), add a per-model aggregate after the `daily` query (~line 1020):

```python
    by_model = (await db.execute(
        select(
            LlmCallLog.model,
            func.coalesce(func.sum(LlmCallLog.cached_input_tokens), 0).label("cached_tokens"),
        )
        .where(LlmCallLog.created_at >= cutoff)
        .group_by(LlmCallLog.model)
    )).all()
    savings = estimate_cache_savings((r.model, int(r.cached_tokens)) for r in by_model)
```

3. Replace the hardcoded line

```python
        "estimated_savings_usd": round(total_cached * 0.75 / 1_000_000 * 0.30, 4),
```

with

```python
        "estimated_savings_usd": round(savings, 4),
```

- [ ] **Step 5: Refresh the stale fallback rates**

Print LiteLLM's current numbers for the models this app actually uses (get the model list from `grep -n "^MODEL_\|MODEL_.*=" resume-optimizer/backend/config.py`):

```bash
/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -c "
import litellm
for m in ['deepseek/deepseek-v4-pro', 'gemini/gemini-2.5-flash']:  # extend with every MODEL_* value from config.py
    try:
        i = litellm.get_model_info(m)
        print(m, 'in/1M:', (i.get('input_cost_per_token') or 0)*1e6, 'out/1M:', (i.get('output_cost_per_token') or 0)*1e6)
    except Exception as e:
        print(m, 'UNMAPPED:', e)
"
```

Update the four tuples in `DEFAULT_PROVIDER_RATES` (utils/cost.py lines 10–15) to the printed per-1M values for each provider's in-use model (for a provider whose model is unmapped, use the provider's published pricing page — do not guess). Add one comment line above the dict: `# Refreshed 2026-07-06 from litellm's pricing map — fallback only; resolve_cost()/cache_rates() prefer LiteLLM.` Keep the keys unchanged (`anthropic`, `google`, `groq`, `deepseek`) — `ALLOWED_PROVIDERS` derives from them.

- [ ] **Step 6: Run the new tests plus the cost suites**

Run: `/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/test_cache_savings.py tests/test_cost_flow.py tests/test_cost_tracking.py tests/test_provider_constants.py tests/test_deepseek_cost_fallback.py -q`
Expected: all pass. If `test_provider_constants.py` pins the OLD tuple values, update its expected numbers to the refreshed ones (the test exists to catch accidental drift, not to freeze stale prices — note the refresh in the test's docstring).

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/utils/cost.py resume-optimizer/backend/admin/router.py resume-optimizer/backend/tests/test_cache_savings.py resume-optimizer/backend/tests/test_provider_constants.py
git commit -m "fix: price cache savings from LiteLLM's map with table fallback"
```

---

### Task 10: Full-suite verification and push

**Files:**
- No source changes expected — verification only.

**Interfaces:**
- Consumes: everything above.
- Produces: a pushed branch with a recorded before/after test baseline.

- [ ] **Step 1: Run the full backend suite**

From `resume-optimizer/backend/`:
`/mnt/c/Users/deshp/Documents/github_repo/agentic_ai/resume-optimizer/.venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -30`

- [ ] **Step 2: Compare against the baseline**

Baseline was **391 passed / 24 failed**. Acceptance:
- Every still-failing test must be on the known pre-existing list (Global Constraints) — zero NEW failures.
- Expected flips to passing: up to 3 in `test_migrations` (Task 2) and `test_pr7_edit_resume::test_system_prompt_has_edit_guidance` (Task 8). Passed count should be ≥ 391 + (number of new tests, ~24) − 0.
- If a pre-existing failure changed its error message because of these changes (e.g. `test_chat_agent` prompt-drift tests), read it and confirm the failure is the same pre-existing category, not a regression. Fix regressions before proceeding.

- [ ] **Step 3: Record and push**

Note the final counts in the commit message and push:

```bash
git push origin claude/effort-estimation-m4a4ep
```

(If any stragglers were fixed in Step 2, commit them first with `fix: <what>` messages.)
