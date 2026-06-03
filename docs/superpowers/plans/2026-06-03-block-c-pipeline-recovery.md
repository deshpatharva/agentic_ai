# Block C — Pipeline Recovery & Health Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stuck-job reaper that auto-recovers orphaned `running` jobs, a `GET /health` liveness endpoint, and a `stuck_jobs` field in admin stats.

**Architecture:** A `_reap_once()` helper contains the DB reap logic; `_reap_stuck_jobs()` calls it in an asyncio loop every 5 minutes, registered alongside the existing `_cleanup_events()` task in FastAPI lifespan. The `/health` endpoint runs DB ping, storage ping, and job counts in sequence and returns a JSON blob; HTTP 503 only when DB is down.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Azure Blob Storage SDK (azure-storage-blob), pytest-asyncio, React + TailwindCSS + lucide-react

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `resume-optimizer/backend/config.py` | Add `STUCK_JOB_TIMEOUT_MINUTES` env var |
| Modify | `resume-optimizer/backend/main.py` | Add `_reap_once()`, `_reap_stuck_jobs()`, lifespan wiring, `GET /health` |
| Modify | `resume-optimizer/backend/storage.py` | Add `ping_storage()` |
| Create | `resume-optimizer/backend/tests/test_health.py` | Reaper + health endpoint tests |
| Modify | `resume-optimizer/backend/admin/schemas.py` | Add `stuck_jobs: int` to `AdminStats` |
| Modify | `resume-optimizer/backend/admin/router.py` | Add `stuck_jobs` query to `GET /admin/stats` |
| Modify | `resume-optimizer/backend/tests/test_admin.py` | Update stats shape test for `stuck_jobs` |
| Modify | `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx` | Add 5th "Stuck Jobs" stat card |

---

## Task 1: Reaper + health endpoint (backend, TDD)

**Files:**
- Modify: `resume-optimizer/backend/config.py`
- Modify: `resume-optimizer/backend/main.py`
- Modify: `resume-optimizer/backend/storage.py`
- Create: `resume-optimizer/backend/tests/test_health.py`

### Context

`main.py` already has `_cleanup_events()` (an asyncio background coroutine registered via `create_task` in lifespan at line 70). Follow exactly this pattern for the reaper.

Current relevant imports in `main.py`:
- Line 7–16: standard library imports (asyncio, datetime, timedelta, timezone already imported)
- Line 21: `from fastapi.responses import FileResponse, RedirectResponse` — needs `JSONResponse` added
- Line 26: `from sqlalchemy import delete, select, func, update` — needs `text` added
- Line 32: `from config import MAX_ITERATIONS, SCORE_TARGET, BACKEND_URL, FRONTEND_URL, MODEL_SCORER, MAX_UPLOAD_BYTES, MAX_RESUME_CHARS, MAX_JD_CHARS` — needs `STUCK_JOB_TIMEOUT_MINUTES` added
- Line 41: `import storage as _storage` (already imported)
- Line 54: `_EVENT_TTL_HOURS = 24`
- Lines 57–64: `_cleanup_events()` async def
- Lines 67–72: `lifespan` context manager

`storage.py` public API: `upload_output`, `generate_download_url`, `delete_output`. The `_blob_service_client()` private helper builds a `BlobServiceClient` using `DefaultAzureCredential`. `AZURE_STORAGE_ACCOUNT_NAME` is imported at top of `storage.py`.

- [ ] **Step 1: Add `STUCK_JOB_TIMEOUT_MINUTES` to `config.py`**

Open `resume-optimizer/backend/config.py`. After the Azure Storage section (line 74), add:

```python
# ── Pipeline recovery ─────────────────────────────────────────────────────────
STUCK_JOB_TIMEOUT_MINUTES = int(os.environ.get("STUCK_JOB_TIMEOUT_MINUTES", "30"))
```

- [ ] **Step 2: Create `tests/test_health.py` with ALL tests**

Create `resume-optimizer/backend/tests/test_health.py`:

```python
"""Tests for _reap_once reaper helper and GET /health endpoint."""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_health.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base, JobStatus, PipelineJob
from db.session import get_db
from main import app, _reap_once

TEST_DB_URL = "sqlite+aiosqlite:///./test_health.db"
_engine = create_async_engine(TEST_DB_URL, echo=False)
_TestSession = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _TestSession() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    try:
        os.remove("./test_health.db")
    except FileNotFoundError:
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Reaper tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reap_once_marks_stuck_job_as_error():
    """A job stuck in running for > timeout minutes is transitioned to error."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.running,
            updated_at=old_time,
            created_at=old_time,
        ))
        await db.commit()

    async with _TestSession() as db:
        reaped = await _reap_once(db)

    assert str(job_id) in reaped

    async with _TestSession() as db:
        result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_id))
        job = result.scalar_one()
        assert job.status == JobStatus.error
        assert "timed out" in job.error_message


@pytest.mark.asyncio
async def test_reap_once_ignores_recent_running_job():
    """A job that started recently is NOT reaped."""
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.running,
            updated_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    async with _TestSession() as db:
        reaped = await _reap_once(db)

    assert str(job_id) not in reaped

    async with _TestSession() as db:
        result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_id))
        job = result.scalar_one()
        assert job.status == JobStatus.running


@pytest.mark.asyncio
async def test_reap_once_ignores_done_job():
    """A done job is never touched, even if updated_at is old."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=3)
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.done,
            updated_at=old_time,
            created_at=old_time,
        ))
        await db.commit()

    async with _TestSession() as db:
        reaped = await _reap_once(db)

    assert str(job_id) not in reaped

    async with _TestSession() as db:
        result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_id))
        job = result.scalar_one()
        assert job.status == JobStatus.done


# ── Health endpoint tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_200_with_expected_shape(client):
    """GET /health returns 200 with db/storage/job count fields."""
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["db"] == "ok"
    assert data["storage"] == "skipped"   # AZURE_STORAGE_ACCOUNT_NAME not set in tests
    assert "stuck_jobs" in data
    assert "pending_jobs" in data
    assert data["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_health_counts_stuck_jobs(client):
    """stuck_jobs count reflects running jobs older than the timeout."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.running,
            updated_at=old_time,
            created_at=old_time,
        ))
        await db.commit()

    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["stuck_jobs"] >= 1


@pytest.mark.asyncio
async def test_health_counts_pending_jobs(client):
    """pending_jobs count reflects jobs with status=pending."""
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.pending,
            updated_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["pending_jobs"] >= 1
```

- [ ] **Step 3: Run tests — verify they FAIL**

```
cd resume-optimizer
python -m pytest backend/tests/test_health.py -v --tb=short 2>&1 | tail -20
```

Expected: errors with `ImportError: cannot import name '_reap_once' from 'main'`

- [ ] **Step 4: Add `ping_storage()` to `storage.py`**

Open `resume-optimizer/backend/storage.py`. Append at the end of the file (after `delete_output`):

```python


def ping_storage() -> str:
    """Check storage connectivity. Returns 'ok', 'error', or 'skipped'."""
    if not AZURE_STORAGE_ACCOUNT_NAME:
        return "skipped"
    try:
        _blob_service_client().get_account_information()
        return "ok"
    except Exception:
        return "error"
```

- [ ] **Step 5: Update `main.py` imports**

In `resume-optimizer/backend/main.py`, make these three targeted edits:

**5a.** Add `import logging` after the `import uuid` line (line 11):
```python
import logging
```

**5b.** Change `from fastapi.responses import FileResponse, RedirectResponse` to:
```python
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
```

**5c.** Change `from sqlalchemy import delete, select, func, update` to:
```python
from sqlalchemy import delete, select, func, text, update
```

**5d.** Change the config import line (line 32) — add `STUCK_JOB_TIMEOUT_MINUTES`:
```python
from config import MAX_ITERATIONS, SCORE_TARGET, BACKEND_URL, FRONTEND_URL, MODEL_SCORER, MAX_UPLOAD_BYTES, MAX_RESUME_CHARS, MAX_JD_CHARS, STUCK_JOB_TIMEOUT_MINUTES
```

- [ ] **Step 6: Add `_reap_once()` and `_reap_stuck_jobs()` to `main.py`**

In `resume-optimizer/backend/main.py`, after the `_cleanup_events()` function (after line 64), insert:

```python

_logger = logging.getLogger(__name__)


async def _reap_once(db: AsyncSession) -> list[str]:
    """Find stuck running jobs and mark them error. Returns list of reaped IDs."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
    result = await db.execute(
        select(PipelineJob).where(
            PipelineJob.status == JobStatus.running,
            PipelineJob.updated_at < cutoff,
        )
    )
    stuck = result.scalars().all()
    if not stuck:
        return []
    now = datetime.now(timezone.utc)
    ids = []
    for job in stuck:
        job.status = JobStatus.error
        job.error_message = "Job timed out — worker may have restarted."
        job.updated_at = now
        ids.append(str(job.id))
    await db.commit()
    return ids


async def _reap_stuck_jobs():
    """Periodically mark stuck running jobs as error (every 5 minutes)."""
    while True:
        await asyncio.sleep(300)
        async with AsyncSessionLocal() as db:
            ids = await _reap_once(db)
            if ids:
                _logger.warning("Reaped %d stuck jobs: %s", len(ids), ids)
```

- [ ] **Step 7: Register `_reap_stuck_jobs()` in lifespan**

Replace the existing `lifespan` function (lines 67–72):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    cleanup_task = asyncio.create_task(_cleanup_events())
    reap_task = asyncio.create_task(_reap_stuck_jobs())
    yield
    cleanup_task.cancel()
    reap_task.cancel()
```

- [ ] **Step 8: Add `GET /health` endpoint to `main.py`**

After `app.include_router(admin_router)` (line 89), insert:

```python

@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Liveness probe — no auth required."""
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    storage_status = await asyncio.to_thread(_storage.ping_storage)

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
    stuck_count = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.status == JobStatus.running,
                PipelineJob.updated_at < cutoff,
            )
        )
    ).scalar() or 0

    pending_count = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.status == JobStatus.pending,
            )
        )
    ).scalar() or 0

    overall_status = "ok" if (db_ok and storage_status != "error") else "degraded"
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status": overall_status,
            "db": "ok" if db_ok else "error",
            "storage": storage_status,
            "stuck_jobs": stuck_count,
            "pending_jobs": pending_count,
        },
    )
```

- [ ] **Step 9: Run tests — verify they PASS**

```
cd resume-optimizer
python -m pytest backend/tests/test_health.py -v --tb=short 2>&1 | tail -25
```

Expected: `7 passed`

- [ ] **Step 10: Commit**

```bash
git add resume-optimizer/backend/config.py \
        resume-optimizer/backend/main.py \
        resume-optimizer/backend/storage.py \
        resume-optimizer/backend/tests/test_health.py
git commit -m "feat: stuck-job reaper and GET /health liveness endpoint"
```

---

## Task 2: Admin stats — `stuck_jobs` field (TDD)

**Files:**
- Modify: `resume-optimizer/backend/admin/schemas.py`
- Modify: `resume-optimizer/backend/admin/router.py`
- Modify: `resume-optimizer/backend/tests/test_admin.py`

### Context

`AdminStats` is in `admin/schemas.py` lines 32–36. The `GET /admin/stats` handler is in `admin/router.py` lines 93–115. It currently runs 4 count queries. The existing `test_stats_returns_correct_shape` is at `tests/test_admin.py` lines 121–127, checking 4 keys.

`admin/router.py` current datetime import (line 2): `from datetime import datetime, timezone` — `timedelta` is missing, add it.
`admin/router.py` current config import: none — add `from config import STUCK_JOB_TIMEOUT_MINUTES`.

- [ ] **Step 1: Update `test_stats_returns_correct_shape` to expect `stuck_jobs`**

In `resume-optimizer/backend/tests/test_admin.py`, change the test at line 121:

Old:
```python
    for key in ("total_users", "active_users", "pipeline_runs_today", "total_resumes"):
        assert key in data, f"Missing key: {key}"
```

New:
```python
    for key in ("total_users", "active_users", "pipeline_runs_today", "total_resumes", "stuck_jobs"):
        assert key in data, f"Missing key: {key}"
```

- [ ] **Step 2: Run test — verify it FAILS**

```
cd resume-optimizer
python -m pytest backend/tests/test_admin.py::test_stats_returns_correct_shape -v --tb=short
```

Expected: `FAILED` — `AssertionError: Missing key: stuck_jobs`

- [ ] **Step 3: Add `stuck_jobs: int` to `AdminStats`**

In `resume-optimizer/backend/admin/schemas.py`, replace the `AdminStats` class (lines 32–36):

```python
class AdminStats(BaseModel):
    total_users: int
    active_users: int
    pipeline_runs_today: int
    total_resumes: int
    stuck_jobs: int
```

- [ ] **Step 4: Update `admin/router.py` imports and `GET /admin/stats` handler**

**4a.** Change line 2 of `admin/router.py`:

Old:
```python
from datetime import datetime, timezone
```

New:
```python
from datetime import datetime, timedelta, timezone
```

**4b.** After `from db.session import get_db` (line 14), add:

```python
from config import STUCK_JOB_TIMEOUT_MINUTES
```

**4c.** Replace the `get_stats` function body (lines 98–115):

```python
@router.get("/stats", response_model=AdminStats)
async def get_stats(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    stuck_cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
    return AdminStats(
        total_users=(await db.execute(select(func.count(User.id)))).scalar() or 0,
        active_users=(
            await db.execute(select(func.count(User.id)).where(User.is_active == True))
        ).scalar() or 0,
        total_resumes=(await db.execute(select(func.count(Resume.id)))).scalar() or 0,
        pipeline_runs_today=(
            await db.execute(
                select(func.count(PipelineJob.id)).where(
                    PipelineJob.created_at >= today_start,
                    PipelineJob.status == JobStatus.done,
                )
            )
        ).scalar() or 0,
        stuck_jobs=(
            await db.execute(
                select(func.count(PipelineJob.id)).where(
                    PipelineJob.status == JobStatus.running,
                    PipelineJob.updated_at < stuck_cutoff,
                )
            )
        ).scalar() or 0,
    )
```

- [ ] **Step 5: Run test — verify it PASSES**

```
cd resume-optimizer
python -m pytest backend/tests/test_admin.py::test_stats_returns_correct_shape -v --tb=short
```

Expected: `PASSED`

- [ ] **Step 6: Run the full admin test file**

```
cd resume-optimizer
python -m pytest backend/tests/test_admin.py -v --tb=short 2>&1 | tail -20
```

Expected: same pass count as before (pre-existing fixture issues unchanged), no new failures.

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/admin/schemas.py \
        resume-optimizer/backend/admin/router.py \
        resume-optimizer/backend/tests/test_admin.py
git commit -m "feat: add stuck_jobs count to admin stats endpoint"
```

---

## Task 3: Frontend — "Stuck Jobs" stat card

**Files:**
- Modify: `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx`

### Context

Current `AdminDashboard.jsx` renders 4 stat cards from a `cards` array (lines 33–38). `StatCard` takes `{ label, value, icon, color }` — `color` is a Tailwind bg class applied to the icon container. The loading skeleton at line 44 renders `[...Array(4)]`.

The 5th card should show "Stuck Jobs". When value is `0`, use neutral `bg-gray-600`. When value is `> 0`, use `bg-amber-500` to draw attention. Since `color` in the current design is static, pass a computed `color` based on the stat value instead.

Lucide icons already imported: `Users`, `Activity`, `FileText`, `Zap`. Add `AlertTriangle` for stuck jobs.

- [ ] **Step 1: Update `AdminDashboard.jsx`**

Replace the entire file `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx`:

```jsx
import { useEffect, useState } from 'react';
import { Users, Activity, FileText, Zap, AlertTriangle } from 'lucide-react';
import client from '../../api/client';

function StatCard({ label, value, icon: Icon, color }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
          <p className="text-2xl font-bold text-white mt-1">
            {value ?? <span className="text-gray-600">—</span>}
          </p>
        </div>
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
          <Icon className="w-5 h-5 text-white" />
        </div>
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    client.get('/admin/stats')
      .then(r => setStats(r.data))
      .finally(() => setLoading(false));
  }, []);

  const cards = [
    { label: 'Total Users',         key: 'total_users',         icon: Users,         color: 'bg-blue-600' },
    { label: 'Active Users',         key: 'active_users',        icon: Activity,      color: 'bg-green-600' },
    { label: 'Pipeline Runs Today',  key: 'pipeline_runs_today', icon: Zap,           color: 'bg-purple-600' },
    { label: 'Total Resumes Stored', key: 'total_resumes',       icon: FileText,      color: 'bg-orange-600' },
    {
      label: 'Stuck Jobs',
      key: 'stuck_jobs',
      icon: AlertTriangle,
      color: stats?.stuck_jobs > 0 ? 'bg-amber-500' : 'bg-gray-600',
    },
  ];

  return (
    <div className="p-8">
      <h1 className="text-xl font-bold text-white mb-6">Dashboard</h1>
      {loading ? (
        <div className="grid grid-cols-2 gap-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-900 border border-gray-800 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {cards.map(c => (
            <StatCard key={c.key} label={c.label} value={stats?.[c.key]} icon={c.icon} color={c.color} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run frontend build**

```
cd resume-optimizer/frontend
npm run build 2>&1 | tail -15
```

Expected: clean build, no errors.

- [ ] **Step 3: Commit**

```bash
git add resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx
git commit -m "feat: add Stuck Jobs stat card to admin dashboard"
```

---

## Task 4: Final verification + push

**Files:** none (verification only)

- [ ] **Step 1: Run the complete backend test suite**

```
cd resume-optimizer
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all health tests pass (7 new), admin stats test passes, no regressions. Pre-existing Windows teardown noise is acceptable.

- [ ] **Step 2: Run frontend build one final time**

```
cd resume-optimizer/frontend
npm run build 2>&1 | tail -10
```

Expected: clean build.

- [ ] **Step 3: Verify git log**

```
git log --oneline -5
```

Expected (most recent first):
```
feat: add Stuck Jobs stat card to admin dashboard
feat: add stuck_jobs count to admin stats endpoint
feat: stuck-job reaper and GET /health liveness endpoint
```

- [ ] **Step 4: Push to origin**

```
git push origin backend_design
```

Expected: `branch 'backend_design' set up to track 'origin/backend_design'` or `Everything up-to-date` after the push completes.
