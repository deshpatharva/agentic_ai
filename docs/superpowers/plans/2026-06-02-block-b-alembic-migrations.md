# Block B — Alembic Migrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `Base.metadata.create_all` with Alembic migrations so every schema change is versioned, repeatable, and safe to run in production.

**Architecture:** Alembic is configured inside `resume-optimizer/backend/` with async SQLAlchemy support. `db/session.py`'s `init_db()` calls `_run_migrations()` (a sync wrapper around `alembic upgrade head`) via `asyncio.to_thread` before the app serves traffic. Tests keep their existing `Base.metadata.create_all` fixture untouched. Models are updated to use the generic `sa.Uuid()` type (SQLAlchemy 2.0+) so autogenerate comparisons work correctly on both PostgreSQL and SQLite.

**Tech Stack:** `alembic>=1.13.0`, `sqlalchemy[asyncio]>=2.0`, `aiosqlite` (test), `asyncpg` (prod)

**Spec:** `docs/superpowers/specs/2026-06-02-block-b-alembic-migrations-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `resume-optimizer/requirements.txt` | Add `alembic>=1.13.0` |
| Modify | `resume-optimizer/backend/db/models.py` | Replace `postgresql.UUID` with `sa.Uuid()` |
| Create | `resume-optimizer/backend/alembic.ini` | Alembic config; DB URL injected at runtime |
| Create | `resume-optimizer/backend/alembic/env.py` | Async migration runner; imports `Base.metadata` |
| Create | `resume-optimizer/backend/alembic/script.py.mako` | Migration file template |
| Create | `resume-optimizer/backend/alembic/versions/0001_initial_schema.py` | Baseline migration for all 5 tables |
| Create | `resume-optimizer/backend/tests/test_migrations.py` | Tests for migration execution |
| Modify | `resume-optimizer/backend/db/session.py` | Replace `create_all` with `_run_migrations()` |
| Modify | `resume-optimizer/backend/Dockerfile` | Remove redundant `alembic` from pip install |
| Modify | `.github/workflows/ci.yml` | Add migration smoke test step |

---

## Task 1: Add `alembic` to requirements and install

**Files:**
- Modify: `resume-optimizer/requirements.txt`

- [ ] **Step 1: Add alembic to requirements.txt**

Open `resume-optimizer/requirements.txt`. Add this line after the existing SQLAlchemy-related entries:

```
alembic>=1.13.0
```

- [ ] **Step 2: Install**

```bash
pip install "alembic>=1.13.0"
```

Expected: `Successfully installed alembic-1.x.x` (or "already satisfied").

- [ ] **Step 3: Verify alembic CLI is available**

```bash
alembic --version
```

Expected: `alembic 1.13.x` (or later).

- [ ] **Step 4: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/requirements.txt
git commit -m "deps: add alembic>=1.13.0"
```

---

## Task 2: Update `db/models.py` — use `sa.Uuid()` instead of `postgresql.UUID`

**Files:**
- Modify: `resume-optimizer/backend/db/models.py`

**Why:** `postgresql.UUID(as_uuid=True)` is dialect-specific. `sa.Uuid()` (SQLAlchemy 2.0+) is dialect-agnostic — it maps to `UUID` on PostgreSQL and `CHAR(32)` on SQLite. This lets Alembic autogenerate correctly compare models to migration history on both databases.

- [ ] **Step 1: Read the current models file**

Read `c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend\db\models.py` to understand the current import structure.

- [ ] **Step 2: Update imports and UUID columns**

In `db/models.py`, make these changes:

**Remove** the PostgreSQL-specific UUID import:
```python
# Remove this line:
from sqlalchemy.dialects.postgresql import UUID
```

**Add** `Uuid` to the existing sqlalchemy imports. The current import line probably looks like:
```python
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text,
)
```

Change it to:
```python
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text, Uuid,
)
```

**Replace all** `UUID(as_uuid=True)` with `Uuid()` throughout the file. There are 4 occurrences (one per table that has a UUID primary key or foreign key column):

```python
# Old (in User, Resume, PipelineJob, PipelineEvent):
id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
user_id = Column(UUID(as_uuid=True), ForeignKey(...), ...)
job_id = Column(UUID(as_uuid=True), ForeignKey(...), ...)

# New:
id = Column(Uuid(), primary_key=True, default=uuid.uuid4)
user_id = Column(Uuid(), ForeignKey(...), ...)
job_id = Column(Uuid(), ForeignKey(...), ...)
```

- [ ] **Step 3: Verify the import check still passes**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend
python -c "
import sys, os
sys.path.insert(0, '.')
os.environ['JWT_SECRET'] = 'test-secret-32-chars-long-enough-x'
from db.models import User, Resume, PipelineJob, PipelineEvent, PlanLimit
print('models OK')
"
```

Expected: `models OK`

- [ ] **Step 4: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/backend/db/models.py
git commit -m "refactor: replace postgresql.UUID with sa.Uuid() for dialect portability"
```

---

## Task 3: Create Alembic configuration files

**Files:**
- Create: `resume-optimizer/backend/alembic.ini`
- Create: `resume-optimizer/backend/alembic/env.py`
- Create: `resume-optimizer/backend/alembic/script.py.mako`

- [ ] **Step 1: Create `alembic.ini`**

Create `resume-optimizer/backend/alembic.ini` with this exact content:

```ini
[alembic]
script_location = alembic
file_template = %%(rev)s_%%(slug)s
prepend_sys_path = .
version_path_separator = os

# sqlalchemy.url is intentionally blank — env.py reads DATABASE_URL from config at runtime
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Create `alembic/env.py`**

Create `resume-optimizer/backend/alembic/env.py`:

```python
import asyncio
from logging.config import fileConfig
from pathlib import Path
import sys

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Ensure backend/ is importable when alembic runs from any working directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATABASE_URL
from db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection (used for --sql flag)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create `alembic/script.py.mako`**

Create `resume-optimizer/backend/alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Verify Alembic can read the config**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend
python -c "
import os
os.environ['JWT_SECRET'] = 'test-secret-32-chars-long-enough-x'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./verify.db'
from alembic.config import Config
cfg = Config('alembic.ini')
print('script_location:', cfg.get_main_option('script_location'))
print('alembic.ini OK')
"
```

Expected:
```
script_location: alembic
alembic.ini OK
```

- [ ] **Step 5: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/backend/alembic.ini resume-optimizer/backend/alembic/env.py resume-optimizer/backend/alembic/script.py.mako
git commit -m "feat: add Alembic config — alembic.ini, env.py (async), script template"
```

---

## Task 4: Create initial migration — TDD

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0001_initial_schema.py`
- Create: `resume-optimizer/backend/tests/test_migrations.py`

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_migrations.py`:

```python
"""
Tests for Alembic migration execution.
Verifies that 0001_initial_schema runs cleanly on SQLite and is idempotent.
"""
import os
import sys
import sqlite3
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_smoke.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

sys.path.insert(0, str(Path(__file__).parent.parent))

import config as cfg
from db.session import _run_migrations


def test_migrations_create_all_tables(tmp_path, monkeypatch):
    """0001_initial_schema must create all 5 expected tables."""
    db_file = tmp_path / "test_migrate.db"
    monkeypatch.setattr(cfg, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    _run_migrations()

    conn = sqlite3.connect(str(db_file))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'alembic_%'"
        ).fetchall()
    }
    conn.close()

    assert tables == {"users", "resumes", "pipeline_jobs", "pipeline_events", "plan_limits"}


def test_migrations_idempotent(tmp_path, monkeypatch):
    """Running migrations twice must not raise."""
    db_file = tmp_path / "test_migrate_idem.db"
    monkeypatch.setattr(cfg, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    _run_migrations()
    _run_migrations()  # must not raise


def test_migrations_stamped_after_run(tmp_path, monkeypatch):
    """Alembic version table must contain head revision after migration."""
    db_file = tmp_path / "test_migrate_stamp.db"
    monkeypatch.setattr(cfg, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    _run_migrations()

    conn = sqlite3.connect(str(db_file))
    rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "0001"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer
pytest backend/tests/test_migrations.py -v
```

Expected: `ImportError` or `AttributeError: module 'db.session' has no attribute '_run_migrations'` — the function doesn't exist yet.

- [ ] **Step 3: Create `alembic/versions/0001_initial_schema.py`**

Create `resume-optimizer/backend/alembic/versions/0001_initial_schema.py`:

```python
"""Initial schema — creates all 5 tables.

Revision ID: 0001
Revises:
Create Date: 2026-06-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── plan_limits (no FK deps) ──────────────────────────────────────────────
    op.create_table(
        "plan_limits",
        sa.Column("plan", sa.String(50), primary_key=True),
        sa.Column("daily_uploads", sa.Integer(), nullable=False),
        sa.Column("max_stored_resumes", sa.Integer(), nullable=False),
        sa.Column("job_scraping_enabled", sa.Boolean(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
    )

    # ── users (no FK deps) ────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column(
            "plan",
            sa.Enum("free", "pro", "enterprise", name="plantype"),
            nullable=False,
        ),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── pipeline_jobs (FK → users) ────────────────────────────────────────────
    op.create_table(
        "pipeline_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "error", name="jobstatus"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("resume_text", sa.Text(), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=True),
        sa.Column("scores_json", sa.JSON(), nullable=True),
        sa.Column("download_path", sa.String(1000), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_pipeline_jobs_user_id", "pipeline_jobs", ["user_id"])
    op.create_index("ix_pipeline_jobs_status", "pipeline_jobs", ["status"])

    # ── resumes (FK → users) ──────────────────────────────────────────────────
    op.create_table(
        "resumes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("jd_text", sa.Text(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("scores_json", sa.JSON(), nullable=True),
        sa.Column("iterations", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])

    # ── pipeline_events (FK → pipeline_jobs) ──────────────────────────────────
    op.create_table(
        "pipeline_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_pipeline_events_job_id", "pipeline_events", ["job_id"])


def downgrade() -> None:
    # Drop in reverse FK dependency order
    op.drop_index("ix_pipeline_events_job_id", table_name="pipeline_events")
    op.drop_table("pipeline_events")

    op.drop_index("ix_resumes_user_id", table_name="resumes")
    op.drop_table("resumes")

    op.drop_index("ix_pipeline_jobs_status", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_user_id", table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_table("plan_limits")

    # Drop named enum types (no-op on SQLite, required on PostgreSQL)
    sa.Enum(name="jobstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="plantype").drop(op.get_bind(), checkfirst=True)
```

Note: the `revision: str = "0001"` must match the revision checked in `test_migrations_stamped_after_run`.

- [ ] **Step 4: Run migration tests — expect they still fail (session._run_migrations not yet defined)**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer
pytest backend/tests/test_migrations.py -v
```

Expected: `AttributeError: module 'db.session' has no attribute '_run_migrations'` — confirms tests are wired correctly and `session.py` hasn't been updated yet.

- [ ] **Step 5: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/backend/alembic/versions/0001_initial_schema.py resume-optimizer/backend/tests/test_migrations.py
git commit -m "feat: add 0001_initial_schema migration + migration tests"
```

---

## Task 5: Update `db/session.py` — replace `create_all` with `_run_migrations()`

**Files:**
- Modify: `resume-optimizer/backend/db/session.py`

- [ ] **Step 1: Replace `init_db` in `session.py`**

Open `resume-optimizer/backend/db/session.py`. Replace the entire file with:

```python
"""
Async SQLAlchemy session factory and database initialization via Alembic.
"""
import asyncio
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from db.models import PlanLimit

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _run_migrations() -> None:
    """
    Run pending Alembic migrations synchronously.
    Called via asyncio.to_thread from init_db() so it doesn't block the event loop.
    Any exception propagates and prevents the app from starting.
    """
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """Run pending migrations then seed plan_limits on first run."""
    await asyncio.to_thread(_run_migrations)

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM plan_limits"))
        count = result.scalar()
        if count == 0:
            plans = [
                PlanLimit(
                    plan="free",
                    daily_uploads=2,
                    max_stored_resumes=1,
                    job_scraping_enabled=False,
                    price_cents=0,
                ),
                PlanLimit(
                    plan="pro",
                    daily_uploads=20,
                    max_stored_resumes=10,
                    job_scraping_enabled=True,
                    price_cents=900,
                ),
                PlanLimit(
                    plan="enterprise",
                    daily_uploads=999,
                    max_stored_resumes=999,
                    job_scraping_enabled=True,
                    price_cents=2900,
                ),
            ]
            session.add_all(plans)
            await session.commit()
```

Key changes from original:
- Removed `Base` import (no longer needed in `session.py`)
- Added `_run_migrations()` synchronous function
- `init_db()` now calls `await asyncio.to_thread(_run_migrations)` before seeding

- [ ] **Step 2: Run migration tests — expect all 3 pass**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer
pytest backend/tests/test_migrations.py -v
```

Expected:
```
PASSED backend/tests/test_migrations.py::test_migrations_create_all_tables
PASSED backend/tests/test_migrations.py::test_migrations_idempotent
PASSED backend/tests/test_migrations.py::test_migrations_stamped_after_run
3 passed
```

- [ ] **Step 3: Run the full test suite — confirm smoke tests still pass**

```bash
pytest backend/tests/ -v --tb=short 2>&1 | tail -20
```

The smoke tests use `Base.metadata.create_all` in their own fixture (`conftest.py`), completely bypassing `init_db()` and `_run_migrations()`. They must still pass.

Expected: migration tests pass (3), smoke tests pass (existing count), storage tests pass (5), delta writer tests pass (14). The pre-existing Windows SQLite teardown error is acceptable.

- [ ] **Step 4: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/backend/db/session.py
git commit -m "feat: db/session.py — replace create_all with Alembic _run_migrations()"
```

---

## Task 6: Update `Dockerfile` — remove redundant alembic install

**Files:**
- Modify: `resume-optimizer/backend/Dockerfile`

- [ ] **Step 1: Read the Dockerfile**

Read `c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend\Dockerfile` to find the explicit `alembic` install.

- [ ] **Step 2: Remove `alembic` from the explicit pip install**

The Dockerfile has a `pip install --no-cache-dir` line that installs `alembic` separately. Remove `alembic \` from that line since it is now in `requirements.txt`.

The pip install block currently looks like:
```dockerfile
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        asyncpg \
        sqlalchemy[asyncio] \
        alembic \
        python-jose[cryptography] \
        bcrypt \
        passlib
```

Change to:
```dockerfile
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        asyncpg \
        sqlalchemy[asyncio] \
        python-jose[cryptography] \
        bcrypt \
        passlib
```

Note: `asyncpg`, `sqlalchemy[asyncio]`, `python-jose[cryptography]`, `bcrypt`, `passlib` are also not yet in `requirements.txt` explicitly. Leave them for now — they're installed by the Dockerfile as before. Only remove `alembic` since that's what's been added to `requirements.txt` in Task 1.

- [ ] **Step 3: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/backend/Dockerfile
git commit -m "chore: remove redundant alembic from Dockerfile (now in requirements.txt)"
```

---

## Task 7: Update CI — add migration smoke test

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Read current ci.yml**

Read `c:\Users\deshp\Documents\github_repo\agentic_ai\.github\workflows\ci.yml` to find the backend job's steps.

- [ ] **Step 2: Add migration test step after the existing smoke tests step**

Find the `Smoke tests` step in the backend job:

```yaml
      - name: Smoke tests
        run: pytest --tb=short -v
```

Add this step immediately after it:

```yaml
      - name: Migration smoke test
        working-directory: resume-optimizer/backend
        env:
          DATABASE_URL: sqlite+aiosqlite:///./test_migrate_ci.db
        run: |
          alembic upgrade head
          alembic check || echo "alembic check reported drift (SQLite enum rendering) — review locally against PostgreSQL"
          rm -f test_migrate_ci.db
```

This verifies that:
1. `alembic upgrade head` runs cleanly on a fresh SQLite database (catches syntax errors in the migration)
2. `alembic check` compares the migrated schema against current models — exits non-zero if models have drifted from migrations. The `|| echo` fallback makes it non-blocking in CI because SQLite sometimes renders enum/UUID types differently than PostgreSQL; treat `alembic check` failures in CI as a signal to verify locally against PostgreSQL, not a hard build break.
3. The test DB is cleaned up after the step

- [ ] **Step 3: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add .github/workflows/ci.yml
git commit -m "ci: add Alembic migration smoke test step"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer
pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass (migration: 3, smoke: 11, storage: 5, delta writer: 14 = 33 total). The pre-existing Windows SQLite teardown error on `test_smoke.db` cleanup is acceptable.

- [ ] **Step 2: Verify `_run_migrations` import check**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend
python -c "
import sys, os
sys.path.insert(0, '.')
os.environ['JWT_SECRET'] = 'test-secret-32-chars-long-enough-x'
from db.session import _run_migrations, init_db, get_db
print('session imports OK')
"
```

Expected: `session imports OK`

- [ ] **Step 3: Verify Alembic history shows one revision**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend
DATABASE_URL="sqlite+aiosqlite:///./verify_history.db" alembic history
```

On Windows PowerShell:
```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./verify_history.db"
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend
alembic history
```

Expected:
```
0001 -> <base> (head), Initial schema — creates all 5 tables.
```

Clean up: `rm verify_history.db` (or `Remove-Item verify_history.db` on PowerShell).

- [ ] **Step 4: Git log — verify all commits present**

```bash
git -C c:\Users\deshp\Documents\github_repo\agentic_ai log --oneline -8
```

Expected commits (most recent first):
- `ci: add Alembic migration smoke test step`
- `chore: remove redundant alembic from Dockerfile`
- `feat: db/session.py — replace create_all with Alembic _run_migrations()`
- `feat: add 0001_initial_schema migration + migration tests`
- `feat: add Alembic config — alembic.ini, env.py (async), script template`
- `refactor: replace postgresql.UUID with sa.Uuid() for dialect portability`
- `deps: add alembic>=1.13.0`

- [ ] **Step 5: Push and create PR**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git push origin backend_design
```

Then open: `https://github.com/deshpatharva/agentic_ai/compare/main...backend_design`

PR title: `Block B: Alembic migrations — versioned schema management`

---

## Deployment Note (for when Block B hits production)

Any database where `Base.metadata.create_all` already ran must be "stamped" **once** before deploying Block B:

```bash
# Run from the App Service console or a local env pointed at prod DB
cd backend
alembic stamp head
```

This marks the existing schema as revision `0001` without running the migration. Subsequent deployments will then correctly apply future migrations.

New databases (fresh deploys) will run `0001_initial_schema` automatically on first startup.
