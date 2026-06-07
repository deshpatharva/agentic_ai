# Block B — Alembic Migrations: Design Spec
**Date:** 2026-06-02
**Branch:** backend_design
**Status:** Approved

## Problem

`db/session.py` calls `Base.metadata.create_all` on every startup. This is idempotent for new deployments but cannot handle schema changes — adding a column, renaming a field, or dropping a table requires manual SQL against the production database or risks silent data loss. There are no Alembic migrations, no version history, and no safety net for schema drift.

---

## Approach: Alembic inside FastAPI Lifespan

`init_db()` is replaced with a call to `alembic upgrade head` (via `asyncio.to_thread`) inside the FastAPI lifespan. If the migration fails, the exception propagates, the app refuses to start, and App Service keeps the previous version alive. PlanLimit seeding runs immediately after migration in the same `init_db()` function.

Tests keep their existing `Base.metadata.create_all` fixture — no changes to the test setup.

**Why lifespan (not startup command):** The App Service deployment already has `DATABASE_URL` resolved from Key Vault before the process starts. Running migrations inside Python lifespan keeps everything in one language and one error surface. The failure mode (app won't start) is the safest option for a single-instance setup.

---

## Files Changed

| Action | File | Responsibility |
|---|---|---|
| Create | `resume-optimizer/backend/alembic.ini` | Alembic config; DB URL injected at runtime from env |
| Create | `resume-optimizer/backend/alembic/env.py` | Async migration runner; imports `Base` for autogenerate |
| Create | `resume-optimizer/backend/alembic/script.py.mako` | Migration file template |
| Create | `resume-optimizer/backend/alembic/versions/0001_initial_schema.py` | Baseline migration capturing all 5 current tables |
| Modify | `resume-optimizer/backend/db/session.py` | Replace `create_all` with `_run_migrations()` |
| Modify | `resume-optimizer/requirements.txt` | Add `alembic>=1.13.0` |
| Modify | `resume-optimizer/backend/Dockerfile` | Remove redundant `alembic` from pip install |
| Modify | `.github/workflows/ci.yml` | Add `alembic check` step |

---

## Section 1: `alembic.ini`

Location: `resume-optimizer/backend/alembic.ini`

```ini
[alembic]
script_location = alembic
file_template = %%(rev)s_%%(slug)s
prepend_sys_path = .
version_path_separator = os
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

`sqlalchemy.url` is intentionally blank — `env.py` sets it at runtime from `config.DATABASE_URL` so no credentials appear in any committed file.

---

## Section 2: `alembic/env.py`

Location: `resume-optimizer/backend/alembic/env.py`

Uses the `run_sync` pattern for async SQLAlchemy — the standard Alembic async approach. Imports `Base.metadata` so `alembic revision --autogenerate` works for future schema changes.

```python
import asyncio
from logging.config import fileConfig
from pathlib import Path
import sys

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make backend/ importable when running alembic from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATABASE_URL
from db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
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

---

## Section 3: `alembic/script.py.mako`

Standard Alembic template — unchanged from the default. Required for `alembic revision` to generate new migration files.

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

---

## Section 4: `alembic/versions/0001_initial_schema.py`

The baseline migration. Creates all 5 tables exactly as defined by the current SQLAlchemy models. This migration runs on any fresh database and results in the same schema `create_all` would have produced.

**Tables created (in dependency order):**

1. `plan_limits` — no foreign keys
2. `users` — no foreign keys; unique index on `email`
3. `pipeline_jobs` — FK to `users(id)` with `SET NULL`; index on `user_id`, `status`
4. `resumes` — FK to `users(id)` with `CASCADE`; index on `user_id`
5. `pipeline_events` — FK to `pipeline_jobs(id)` with `CASCADE`; index on `job_id`

**Existing databases:** On a database where `create_all` already ran (dev laptops, existing prod if any), `alembic stamp head` must be run once before deploying this migration so Alembic knows the baseline is already applied. Instructions in the deployment checklist.

**`upgrade()`** creates all tables and indexes. **`downgrade()`** drops all tables in reverse dependency order.

---

## Section 5: `db/session.py` changes

Replace `init_db()` with a version that runs Alembic then seeds:

```python
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from config import DATABASE_URL
from db.models import Base, PlanLimit

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _run_migrations() -> None:
    """Run pending Alembic migrations synchronously. Called via asyncio.to_thread."""
    from alembic.config import Config
    from alembic import command
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """Run pending migrations then seed plan_limits on first run."""
    await asyncio.to_thread(_run_migrations)

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM plan_limits"))
        count = result.scalar()
        if count == 0:
            plans = [
                PlanLimit(plan="free",       daily_uploads=2,   max_stored_resumes=1,   job_scraping_enabled=False, price_cents=0),
                PlanLimit(plan="pro",        daily_uploads=20,  max_stored_resumes=10,  job_scraping_enabled=True,  price_cents=900),
                PlanLimit(plan="enterprise", daily_uploads=999, max_stored_resumes=999, job_scraping_enabled=True,  price_cents=2900),
            ]
            session.add_all(plans)
            await session.commit()
```

The `Base` import is no longer needed in `session.py` (it's now only used by `alembic/env.py` and the test fixture). Remove it.

---

## Section 6: `requirements.txt` and `Dockerfile`

**`requirements.txt`** — add:
```
alembic>=1.13.0
```

**`Dockerfile`** — remove `alembic` from the explicit `pip install` step (it's now in `requirements.txt`):
```dockerfile
# Remove alembic from this line:
RUN pip install --no-cache-dir \
    asyncpg \
    sqlalchemy[asyncio] \
    python-jose[cryptography] \
    bcrypt \
    passlib
```

---

## Section 7: CI — `alembic check`

Add a step to `.github/workflows/ci.yml` in the backend job, after smoke tests:

```yaml
- name: Check no un-generated migrations
  working-directory: resume-optimizer/backend
  env:
    DATABASE_URL: sqlite+aiosqlite:///./check_schema.db
  run: |
    alembic upgrade head
    alembic check
    rm -f check_schema.db
```

`alembic upgrade head` runs all migrations on a fresh SQLite database, then `alembic check` compares the resulting schema against the current models and exits non-zero if there is a diff. This catches the most common mistake: adding a column to `models.py` without running `alembic revision --autogenerate -m "describe change"`.

The check DB is separate from `test_ci.db` so the two steps are independent and the check file is cleaned up after.

---

## What Stays the Same

- `backend/tests/conftest.py` — still calls `Base.metadata.create_all` directly; no change
- `backend/tests/test_smoke.py` — no change
- `main.py` lifespan — still calls `await init_db()`, no change
- All agent code, API routes, frontend — untouched

---

## How to Handle Existing Databases

Any database where `create_all` already ran needs to be "stamped" once before the first migration deploy:

```bash
cd resume-optimizer/backend
alembic stamp head
```

This tells Alembic "the current schema is at revision head" without running any migrations. Only needed for databases created before Alembic was added — new databases (fresh deploys) will run `0001_initial_schema` from scratch.

---

## Out of Scope

- Block C (stuck pipeline recovery, health endpoint)
- Block D (rate limiting, Postgres VNet)
- Block E (observability)
- Block F (agent unit tests)
