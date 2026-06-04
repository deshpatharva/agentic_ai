# Block G.1 — Admin Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a protected admin section — backend API module with user management and stats, plus a React frontend under `/admin` — on top of a new `is_admin` database column.

**Architecture:** A new `backend/admin/` FastAPI module handles all `/admin/*` endpoints behind a `get_admin_user` dependency that enforces `is_admin=True`. Alembic migration `0002` adds the column. The React frontend adds `AdminRoute`, `AdminLayout`, and three admin pages under `/admin`. Existing JWT auth is reused throughout — no new token type.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest-asyncio, React 18, React Router v6, Zustand, Lucide React, Tailwind CSS, `react-hot-toast`

**Spec:** `docs/superpowers/specs/2026-06-02-block-g1-admin-foundation-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `resume-optimizer/backend/alembic/versions/0002_add_is_admin.py` | Migration: add is_admin column |
| Modify | `resume-optimizer/backend/db/models.py` | Add is_admin to User |
| Modify | `resume-optimizer/backend/auth/router.py` | Add is_admin to `_user_dict` |
| Create | `resume-optimizer/backend/admin/__init__.py` | Package marker |
| Create | `resume-optimizer/backend/admin/dependencies.py` | `get_admin_user` dependency |
| Create | `resume-optimizer/backend/admin/schemas.py` | Pydantic request/response models |
| Create | `resume-optimizer/backend/admin/router.py` | All `/admin/*` endpoints |
| Modify | `resume-optimizer/backend/main.py` | Register admin router |
| Create | `resume-optimizer/backend/tests/test_admin.py` | Admin endpoint tests |
| Create | `resume-optimizer/frontend/src/components/AdminRoute.jsx` | Admin auth guard |
| Create | `resume-optimizer/frontend/src/pages/admin/AdminLayout.jsx` | Admin shell + sidebar |
| Create | `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx` | Stats cards |
| Create | `resume-optimizer/frontend/src/pages/admin/UserList.jsx` | Paginated user table |
| Create | `resume-optimizer/frontend/src/pages/admin/UserDetail.jsx` | User detail + actions |
| Modify | `resume-optimizer/frontend/src/main.jsx` | Add `/admin` routes |

---

## Task 1: Migration 0002 + model update + auth dict

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0002_add_is_admin.py`
- Modify: `resume-optimizer/backend/db/models.py`
- Modify: `resume-optimizer/backend/auth/router.py`

- [ ] **Step 1: Read `db/models.py` and `auth/router.py`**

Read both files before editing:
- `c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend\db\models.py`
- `c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend\auth\router.py`

- [ ] **Step 2: Create the migration file**

Create `resume-optimizer/backend/alembic/versions/0002_add_is_admin.py`:

```python
"""Add is_admin column to users.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
```

`server_default=sa.text("false")` is required so PostgreSQL can backfill existing rows when adding the NOT NULL column.

- [ ] **Step 3: Add `is_admin` to the User model**

In `db/models.py`, find the `User` class. Add this column after `is_active`:

```python
is_admin = Column(Boolean, default=False, nullable=False)
```

- [ ] **Step 4: Add `is_admin` to `_user_dict` in `auth/router.py`**

Find the `_user_dict` function. Add `"is_admin": user.is_admin,` to the returned dict:

```python
def _user_dict(user: User, limits: PlanLimit = None) -> dict:
    d = {
        "id":          str(user.id),
        "email":       user.email,
        "full_name":   user.full_name or "",
        "plan":        user.plan.value,
        "is_active":   user.is_active,
        "is_admin":    user.is_admin,
        "created_at":  user.created_at.isoformat(),
    }
    if limits:
        d["limits"] = {
            "daily_uploads":        limits.daily_uploads,
            "max_stored_resumes":   limits.max_stored_resumes,
            "job_scraping_enabled": limits.job_scraping_enabled,
            "price_cents":          limits.price_cents,
        }
    return d
```

- [ ] **Step 5: Verify migration runs on SQLite**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend
$env:DATABASE_URL = "sqlite+aiosqlite:///./verify_g1.db"
alembic upgrade head
python -c "
import sqlite3
conn = sqlite3.connect('verify_g1.db')
cols = [row[1] for row in conn.execute('PRAGMA table_info(users)').fetchall()]
print('is_admin in users:', 'is_admin' in cols)
conn.close()
"
Remove-Item -ErrorAction SilentlyContinue verify_g1.db
```

Expected: `is_admin in users: True`

- [ ] **Step 6: Verify import check**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend
python -c "
import sys, os
sys.path.insert(0, '.')
os.environ['JWT_SECRET'] = 'test-secret-32-chars-long-enough-x'
from db.models import User
print(hasattr(User, 'is_admin'))
"
```

Expected: `True`

- [ ] **Step 7: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/backend/alembic/versions/0002_add_is_admin.py resume-optimizer/backend/db/models.py resume-optimizer/backend/auth/router.py
git commit -m "feat: add is_admin column — migration 0002, model, auth dict"
```

---

## Task 2: Admin module skeleton — dependencies + schemas

**Files:**
- Create: `resume-optimizer/backend/admin/__init__.py`
- Create: `resume-optimizer/backend/admin/dependencies.py`
- Create: `resume-optimizer/backend/admin/schemas.py`

- [ ] **Step 1: Create `admin/__init__.py`**

Create `resume-optimizer/backend/admin/__init__.py` — empty file.

- [ ] **Step 2: Create `admin/dependencies.py`**

Create `resume-optimizer/backend/admin/dependencies.py`:

```python
from fastapi import Depends, HTTPException
from db.models import User
from auth.dependencies import get_current_user


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """Dependency that enforces admin access. Returns 403 for non-admins, 401 for unauthenticated."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user
```

- [ ] **Step 3: Create `admin/schemas.py`**

Create `resume-optimizer/backend/admin/schemas.py`:

```python
from typing import Optional
from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    email: str


class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    plan: str
    is_active: bool
    is_admin: bool
    created_at: str
    resume_count: int


class UserDetail(UserListItem):
    runs_today: int
    total_resumes: int
    last_active: Optional[str]


class UserUpdate(BaseModel):
    plan: Optional[str] = None         # "free" | "pro" | "enterprise"
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None    # True promotes; False rejected by server


class AdminStats(BaseModel):
    total_users: int
    active_users: int
    pipeline_runs_today: int
    total_resumes: int
```

- [ ] **Step 4: Verify imports**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\backend
python -c "
import sys, os
sys.path.insert(0, '.')
os.environ['JWT_SECRET'] = 'test-secret-32-chars-long-enough-x'
from admin.dependencies import get_admin_user
from admin.schemas import AdminStats, UserDetail, UserListItem, UserUpdate, BootstrapRequest
print('admin module OK')
"
```

Expected: `admin module OK`

- [ ] **Step 5: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/backend/admin/
git commit -m "feat: admin module skeleton — dependencies, schemas"
```

---

## Task 3: Admin router + register in main.py (TDD)

**Files:**
- Create: `resume-optimizer/backend/admin/router.py`
- Create: `resume-optimizer/backend/tests/test_admin.py`
- Modify: `resume-optimizer/backend/main.py`

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_admin.py`:

```python
"""Admin endpoint tests."""
import os
import sys
import uuid
import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_admin.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base, User
from db.session import get_db
from main import app

TEST_DB_URL = "sqlite+aiosqlite:///./test_admin.db"
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
        os.remove("./test_admin.db")
    except FileNotFoundError:
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin_token(client):
    """Register a user and promote directly via DB (bypasses bootstrap)."""
    r = await client.post("/auth/register", json={
        "email": "admin_fixture@test.com",
        "password": "Test1234!",
        "full_name": "Admin",
    })
    user_id = r.json()["user"]["id"]

    async with _TestSession() as session:
        await session.execute(
            update(User).where(User.id == uuid.UUID(user_id)).values(is_admin=True)
        )
        await session.commit()

    r2 = await client.post("/auth/login", json={
        "email": "admin_fixture@test.com", "password": "Test1234!"
    })
    return r2.json()["access_token"]


@pytest_asyncio.fixture
async def user_token(client):
    """Register a regular non-admin user."""
    r = await client.post("/auth/register", json={
        "email": "regular_fixture@test.com", "password": "Test1234!"
    })
    return r.json()["access_token"]


# ── Bootstrap ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_creates_first_admin(client):
    """Bootstrap creates an admin on a fresh DB with no existing admins."""
    await client.post("/auth/register", json={
        "email": "bootstrap_user@test.com", "password": "Test1234!"
    })
    r = await client.post("/admin/bootstrap", json={"email": "bootstrap_user@test.com"})
    assert r.status_code == 200
    assert r.json()["is_admin"] is True


@pytest.mark.asyncio
async def test_bootstrap_blocks_second_call(client):
    """Bootstrap returns 403 once an admin already exists."""
    await client.post("/auth/register", json={
        "email": "bootstrap_user2@test.com", "password": "Test1234!"
    })
    r = await client.post("/admin/bootstrap", json={"email": "bootstrap_user2@test.com"})
    assert r.status_code == 403


# ── Stats ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_requires_admin(client, user_token):
    r = await client.get("/admin/stats", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_stats_returns_correct_shape(client, admin_token):
    r = await client.get("/admin/stats", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    data = r.json()
    for key in ("total_users", "active_users", "pipeline_runs_today", "total_resumes"):
        assert key in data, f"Missing key: {key}"
    assert data["total_users"] >= 1


# ── User list ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_list_requires_admin(client, user_token):
    r = await client.get("/admin/users", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_user_list_returns_paginated(client, admin_token):
    r = await client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    data = r.json()
    assert "total" in data and "results" in data and "page" in data
    assert isinstance(data["results"], list)


@pytest.mark.asyncio
async def test_user_list_search_filters_by_email(client, admin_token):
    r = await client.get(
        "/admin/users?search=admin_fixture",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert all("admin_fixture" in u["email"] for u in results)


# ── User detail ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_detail_returns_full_fields(client, admin_token, user_token):
    # Get the regular user's ID from the list
    r = await client.get(
        "/admin/users?search=regular_fixture",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["total"] >= 1
    user_id = r.json()["results"][0]["id"]

    r2 = await client.get(
        f"/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 200
    data = r2.json()
    assert data["email"] == "regular_fixture@test.com"
    for key in ("runs_today", "total_resumes", "last_active"):
        assert key in data, f"Missing key: {key}"


# ── User update ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_user_plan(client, admin_token):
    r = await client.get(
        "/admin/users?search=regular_fixture",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    user_id = r.json()["results"][0]["id"]

    r2 = await client.patch(
        f"/admin/users/{user_id}",
        json={"plan": "pro"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 200
    assert r2.json()["plan"] == "pro"


@pytest.mark.asyncio
async def test_update_cannot_suspend_admin(client, admin_token):
    r = await client.get(
        "/admin/users?search=admin_fixture",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    admin_id = r.json()["results"][0]["id"]

    r2 = await client.patch(
        f"/admin/users/{admin_id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_update_promote_to_admin(client, admin_token):
    r = await client.get(
        "/admin/users?search=regular_fixture",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    user_id = r.json()["results"][0]["id"]

    r2 = await client.patch(
        f"/admin/users/{user_id}",
        json={"is_admin": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 200
    assert r2.json()["is_admin"] is True


@pytest.mark.asyncio
async def test_update_cannot_demote_admin(client, admin_token):
    r = await client.get(
        "/admin/users?search=admin_fixture",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    admin_id = r.json()["results"][0]["id"]

    r2 = await client.patch(
        f"/admin/users/{admin_id}",
        json={"is_admin": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_update_invalid_plan_rejected(client, admin_token):
    r = await client.get(
        "/admin/users?search=regular_fixture",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    user_id = r.json()["results"][0]["id"]

    r2 = await client.patch(
        f"/admin/users/{user_id}",
        json={"plan": "diamond"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 400
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer
pytest backend/tests/test_admin.py -v 2>&1 | head -30
```

Expected: errors about missing `/admin/bootstrap` or `/admin/stats` routes (404s or import errors). The important thing is the tests run and fail — not that they pass.

- [ ] **Step 3: Create `admin/router.py`**

Create `resume-optimizer/backend/admin/router.py`:

```python
"""Admin API routes. All endpoints (except /bootstrap) require get_admin_user."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from admin.dependencies import get_admin_user
from admin.schemas import AdminStats, BootstrapRequest, UserUpdate
from db.models import JobStatus, PipelineJob, PlanType, Resume, User
from db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

_VALID_PLANS = {"free", "pro", "enterprise"}


def _user_dict(user: User, resume_count: int) -> dict:
    return {
        "id":           str(user.id),
        "email":        user.email,
        "full_name":    user.full_name or "",
        "plan":         user.plan.value,
        "is_active":    user.is_active,
        "is_admin":     user.is_admin,
        "created_at":   user.created_at.isoformat(),
        "resume_count": resume_count,
    }


async def _user_detail(user: User, db: AsyncSession) -> dict:
    uid = user.id
    total_resumes = (
        await db.execute(select(func.count(Resume.id)).where(Resume.user_id == uid))
    ).scalar() or 0

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    runs_today = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.user_id == uid,
                PipelineJob.created_at >= today_start,
                PipelineJob.status == JobStatus.done,
            )
        )
    ).scalar() or 0

    last_active = (
        await db.execute(
            select(func.max(Resume.created_at)).where(Resume.user_id == uid)
        )
    ).scalar()

    return {
        **_user_dict(user, total_resumes),
        "runs_today":    runs_today,
        "total_resumes": total_resumes,
        "last_active":   last_active.isoformat() if last_active else None,
    }


# ── Bootstrap ─────────────────────────────────────────────────────────────────

@router.post("/bootstrap")
async def bootstrap(
    body: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
):
    """Promote a user to admin. Self-disables once any admin exists."""
    admin_count = (
        await db.execute(select(func.count(User.id)).where(User.is_admin == True))
    ).scalar()
    if admin_count > 0:
        raise HTTPException(status_code=403, detail="An admin already exists.")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.is_admin = True
    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id), "email": user.email, "is_admin": user.is_admin}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=AdminStats)
async def get_stats(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
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
    )


# ── User list ─────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
):
    base_filter = []
    if search:
        base_filter.append(func.lower(User.email).like(f"{search.lower()}%"))

    total = (
        await db.execute(select(func.count(User.id)).where(*base_filter))
    ).scalar() or 0

    users = (
        await db.execute(
            select(User)
            .where(*base_filter)
            .order_by(User.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    user_ids = [u.id for u in users]
    counts = {}
    if user_ids:
        rows = (
            await db.execute(
                select(Resume.user_id, func.count(Resume.id))
                .where(Resume.user_id.in_(user_ids))
                .group_by(Resume.user_id)
            )
        ).all()
        counts = {str(row[0]): row[1] for row in rows}

    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "results":  [_user_dict(u, counts.get(str(u.id), 0)) for u in users],
    }


# ── User detail ───────────────────────────────────────────────────────────────

@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found.")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    return await _user_detail(user, db)


# ── User update ───────────────────────────────────────────────────────────────

@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found.")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if body.plan is not None and body.plan not in _VALID_PLANS:
        raise HTTPException(status_code=400, detail=f"plan must be one of {sorted(_VALID_PLANS)}")
    if body.is_active is False and user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot suspend an admin user.")
    if body.is_active is False and str(user.id) == str(admin.id):
        raise HTTPException(status_code=400, detail="Cannot suspend yourself.")
    if body.is_admin is False:
        raise HTTPException(status_code=400, detail="Admin demotion via API is not allowed.")

    if body.plan is not None:
        user.plan = PlanType(body.plan)
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_admin is True:
        user.is_admin = True

    await db.commit()
    await db.refresh(user)
    return await _user_detail(user, db)
```

- [ ] **Step 4: Register admin router in `main.py`**

Open `resume-optimizer/backend/main.py`. Find the existing `app.include_router(auth_router)` and `app.include_router(dashboard_router)` lines. Add the admin router import and registration:

```python
# Add to imports (near the other router imports):
from admin.router import router as admin_router

# Add after the existing include_router calls:
app.include_router(admin_router)
```

- [ ] **Step 5: Run admin tests — expect all pass**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer
pytest backend/tests/test_admin.py -v
```

Expected: all 14 tests pass.

Note: `test_bootstrap_creates_first_admin` runs FIRST (before `admin_token` fixture creates an admin via direct DB). `test_bootstrap_blocks_second_call` runs SECOND and correctly gets 403. This ordering works because pytest runs tests in file order by default.

- [ ] **Step 6: Run full backend test suite**

```bash
pytest backend/tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass (33 prior + 14 new = 47 total). Pre-existing Windows SQLite teardown error is acceptable.

- [ ] **Step 7: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/backend/admin/router.py resume-optimizer/backend/main.py resume-optimizer/backend/tests/test_admin.py
git commit -m "feat: admin router — bootstrap, stats, user list/detail/update + tests"
```

---

## Task 4: Frontend — AdminRoute + AdminLayout + routing

**Files:**
- Create: `resume-optimizer/frontend/src/components/AdminRoute.jsx`
- Create: `resume-optimizer/frontend/src/pages/admin/AdminLayout.jsx`
- Modify: `resume-optimizer/frontend/src/main.jsx`

- [ ] **Step 1: Read `main.jsx` and `ProtectedRoute.jsx`**

Read both files to understand existing routing and auth guard pattern:
- `c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\frontend\src\main.jsx`
- `c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\frontend\src\components\ProtectedRoute.jsx`

- [ ] **Step 2: Create `AdminRoute.jsx`**

Create `resume-optimizer/frontend/src/components/AdminRoute.jsx`:

```jsx
import { Navigate } from 'react-router-dom';
import useAuthStore from '../store/authStore';

export default function AdminRoute({ children }) {
  const { token, user } = useAuthStore();
  if (!token) return <Navigate to="/login" replace />;
  if (user && !user.is_admin) return <Navigate to="/" replace />;
  return children;
}
```

- [ ] **Step 3: Create `admin/` directory and `AdminLayout.jsx`**

Create `resume-optimizer/frontend/src/pages/admin/AdminLayout.jsx`:

```jsx
import { NavLink, Outlet } from 'react-router-dom';
import { LayoutDashboard, Users } from 'lucide-react';
import useAuthStore from '../../store/authStore';

export default function AdminLayout() {
  const { user } = useAuthStore();

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0">
        <div className="px-4 py-5 border-b border-gray-800">
          <p className="text-xs font-bold tracking-widest text-red-400 uppercase">Admin</p>
          <p className="text-xs text-gray-500 mt-0.5 truncate">{user?.email}</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          <NavLink
            to="/admin"
            end
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`
            }
          >
            <LayoutDashboard className="w-4 h-4" />
            Dashboard
          </NavLink>
          <NavLink
            to="/admin/users"
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`
            }
          >
            <Users className="w-4 h-4" />
            Users
          </NavLink>
        </nav>
      </aside>

      {/* Page content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Add admin routes to `main.jsx`**

In `main.jsx`, add these imports near the top (with the other page imports):

```jsx
import AdminRoute from './components/AdminRoute';
import AdminLayout from './pages/admin/AdminLayout';
import AdminDashboard from './pages/admin/AdminDashboard';
import UserList from './pages/admin/UserList';
import UserDetail from './pages/admin/UserDetail';
```

Then add the admin route block inside the router (alongside the existing routes). The exact placement depends on the current router structure — add it as a sibling to the existing top-level routes:

```jsx
<Route
  path="/admin"
  element={<AdminRoute><AdminLayout /></AdminRoute>}
>
  <Route index element={<AdminDashboard />} />
  <Route path="users" element={<UserList />} />
  <Route path="users/:id" element={<UserDetail />} />
</Route>
```

- [ ] **Step 5: Create placeholder admin page files so the build doesn't fail**

Create these three placeholder files (they'll be replaced in Task 5):

`resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx`:
```jsx
export default function AdminDashboard() {
  return <div className="p-8 text-white">Dashboard — coming in Task 5</div>;
}
```

`resume-optimizer/frontend/src/pages/admin/UserList.jsx`:
```jsx
export default function UserList() {
  return <div className="p-8 text-white">Users — coming in Task 5</div>;
}
```

`resume-optimizer/frontend/src/pages/admin/UserDetail.jsx`:
```jsx
export default function UserDetail() {
  return <div className="p-8 text-white">User Detail — coming in Task 5</div>;
}
```

- [ ] **Step 6: Verify frontend builds**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\frontend
npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 7: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/frontend/src/components/AdminRoute.jsx resume-optimizer/frontend/src/pages/admin/ resume-optimizer/frontend/src/main.jsx
git commit -m "feat: AdminRoute guard, AdminLayout sidebar, /admin route wiring"
```

---

## Task 5: Frontend — Admin pages (Dashboard, UserList, UserDetail)

**Files:**
- Modify: `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx`
- Modify: `resume-optimizer/frontend/src/pages/admin/UserList.jsx`
- Modify: `resume-optimizer/frontend/src/pages/admin/UserDetail.jsx`

- [ ] **Step 1: Implement `AdminDashboard.jsx`**

Replace the placeholder content of `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx`:

```jsx
import { useEffect, useState } from 'react';
import { Users, Activity, FileText, Zap } from 'lucide-react';
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
    { label: 'Total Users',          key: 'total_users',          icon: Users,    color: 'bg-blue-600' },
    { label: 'Active Users',          key: 'active_users',         icon: Activity, color: 'bg-green-600' },
    { label: 'Pipeline Runs Today',   key: 'pipeline_runs_today',  icon: Zap,      color: 'bg-purple-600' },
    { label: 'Total Resumes Stored',  key: 'total_resumes',        icon: FileText, color: 'bg-orange-600' },
  ];

  return (
    <div className="p-8">
      <h1 className="text-xl font-bold text-white mb-6">Dashboard</h1>
      {loading ? (
        <div className="grid grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
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

- [ ] **Step 2: Implement `UserList.jsx`**

Replace the placeholder content of `resume-optimizer/frontend/src/pages/admin/UserList.jsx`:

```jsx
import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, ChevronRight } from 'lucide-react';
import client from '../../api/client';

const PLAN_BADGE = {
  free:       'bg-gray-700 text-gray-200',
  pro:        'bg-blue-900 text-blue-200',
  enterprise: 'bg-purple-900 text-purple-200',
};

export default function UserList() {
  const navigate = useNavigate();
  const [users, setUsers]       = useState([]);
  const [total, setTotal]       = useState(0);
  const [page, setPage]         = useState(1);
  const [search, setSearch]     = useState('');
  const [rawInput, setRawInput] = useState('');
  const [loading, setLoading]   = useState(true);
  const perPage = 20;

  // Debounce raw input → search
  useEffect(() => {
    const t = setTimeout(() => { setSearch(rawInput); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [rawInput]);

  const fetchUsers = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ page, per_page: perPage });
    if (search) params.set('search', search);
    client.get(`/admin/users?${params}`)
      .then(r => { setUsers(r.data.results); setTotal(r.data.total); })
      .finally(() => setLoading(false));
  }, [page, search]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-white">
          Users <span className="text-gray-500 text-base font-normal">({total})</span>
        </h1>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            placeholder="Search by email…"
            value={rawInput}
            onChange={e => setRawInput(e.target.value)}
            className="pl-9 pr-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-gray-500 w-56"
          />
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wide">
              <th className="px-4 py-3 text-left">Email</th>
              <th className="px-4 py-3 text-left">Plan</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-left">Resumes</th>
              <th className="px-4 py-3 text-left">Joined</th>
              <th className="px-4 py-3 w-8" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-gray-600">Loading…</td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-gray-600">No users found.</td>
              </tr>
            ) : users.map(u => (
              <tr
                key={u.id}
                onClick={() => navigate(`/admin/users/${u.id}`)}
                className="border-b border-gray-800 hover:bg-gray-800 cursor-pointer transition-colors"
              >
                <td className="px-4 py-3 text-white">
                  {u.email}
                  {u.is_admin && (
                    <span className="ml-2 text-xs bg-red-900 text-red-300 px-1.5 py-0.5 rounded">admin</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PLAN_BADGE[u.plan] || PLAN_BADGE.free}`}>
                    {u.plan}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${u.is_active ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
                    {u.is_active ? 'Active' : 'Suspended'}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400">{u.resume_count}</td>
                <td className="px-4 py-3 text-gray-400">{new Date(u.created_at).toLocaleDateString()}</td>
                <td className="px-4 py-3 text-gray-600"><ChevronRight className="w-4 h-4" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-5">
          <button
            disabled={page === 1}
            onClick={() => setPage(p => p - 1)}
            className="px-3 py-1.5 text-sm text-gray-400 bg-gray-900 border border-gray-700 rounded-lg disabled:opacity-40 hover:bg-gray-800 transition-colors"
          >
            Prev
          </button>
          <span className="text-sm text-gray-500">Page {page} of {totalPages}</span>
          <button
            disabled={page === totalPages}
            onClick={() => setPage(p => p + 1)}
            className="px-3 py-1.5 text-sm text-gray-400 bg-gray-900 border border-gray-700 rounded-lg disabled:opacity-40 hover:bg-gray-800 transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Implement `UserDetail.jsx`**

Replace the placeholder content of `resume-optimizer/frontend/src/pages/admin/UserDetail.jsx`:

```jsx
import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Shield } from 'lucide-react';
import toast from 'react-hot-toast';
import client from '../../api/client';
import useAuthStore from '../../store/authStore';

const PLANS = ['free', 'pro', 'enterprise'];

export default function UserDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user: me } = useAuthStore();
  const [user, setUser]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);

  useEffect(() => {
    client.get(`/admin/users/${id}`)
      .then(r => setUser(r.data))
      .catch(() => navigate('/admin/users'))
      .finally(() => setLoading(false));
  }, [id, navigate]);

  const patch = async (body) => {
    setSaving(true);
    try {
      const r = await client.patch(`/admin/users/${id}`, body);
      setUser(r.data);
      toast.success('Saved');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Update failed');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="p-8 text-gray-500">Loading…</div>;
  if (!user) return null;

  const isSelf = me?.id === user.id;

  return (
    <div className="p-8 max-w-xl">
      <button
        onClick={() => navigate('/admin/users')}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-white mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back to users
      </button>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">{user.full_name || user.email}</h1>
          <p className="text-gray-500 text-sm mt-0.5">{user.email}</p>
          <p className="text-gray-600 text-xs mt-1">
            Joined {new Date(user.created_at).toLocaleDateString()}
          </p>
        </div>
        {user.is_admin && (
          <span className="flex items-center gap-1 text-xs bg-red-900 text-red-300 px-2.5 py-1 rounded-full">
            <Shield className="w-3 h-3" /> Admin
          </span>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-5">
        {[
          { label: 'Resumes',    value: user.total_resumes },
          { label: 'Runs today', value: user.runs_today },
          { label: 'Last active', value: user.last_active ? new Date(user.last_active).toLocaleDateString() : '—' },
        ].map(s => (
          <div key={s.label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500">{s.label}</p>
            <p className="text-lg font-semibold text-white mt-0.5">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Plan */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-3">
        <p className="text-xs text-gray-500 uppercase tracking-wide mb-3">Plan</p>
        <div className="flex gap-2">
          {PLANS.map(plan => (
            <button
              key={plan}
              disabled={saving || user.plan === plan}
              onClick={() => patch({ plan })}
              className={`px-4 py-2 rounded-lg text-sm font-medium capitalize transition-colors ${
                user.plan === plan
                  ? 'bg-violet-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              } disabled:opacity-60`}
            >
              {plan}
            </button>
          ))}
        </div>
      </div>

      {/* Promote to admin */}
      {!user.is_admin && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-3">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-3">Admin Access</p>
          <button
            disabled={saving}
            onClick={() => {
              if (confirm(`Promote ${user.email} to admin?`)) patch({ is_admin: true });
            }}
            className="px-4 py-2 bg-red-900 hover:bg-red-800 text-red-200 rounded-lg text-sm font-medium transition-colors disabled:opacity-60"
          >
            Promote to admin
          </button>
        </div>
      )}

      {/* Suspend / reactivate */}
      {!user.is_admin && !isSelf && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-3">Account Status</p>
          <button
            disabled={saving}
            onClick={() => patch({ is_active: !user.is_active })}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-60 ${
              user.is_active
                ? 'bg-red-900 hover:bg-red-800 text-red-200'
                : 'bg-green-900 hover:bg-green-800 text-green-200'
            }`}
          >
            {user.is_active ? 'Suspend account' : 'Reactivate account'}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run frontend build**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\frontend
npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git add resume-optimizer/frontend/src/pages/admin/
git commit -m "feat: admin pages — Dashboard stats, UserList with search/pagination, UserDetail with plan/suspend actions"
```

---

## Task 6: Final verification + push

- [ ] **Step 1: Run complete backend test suite**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer
pytest backend/tests/ -v --tb=short 2>&1 | tail -25
```

Expected: 47 tests pass (33 prior + 14 admin). Pre-existing Windows teardown error is acceptable.

- [ ] **Step 2: Run frontend build one more time**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer\frontend
npm run build
```

Expected: clean build, no errors.

- [ ] **Step 3: Verify git log — all Block G.1 commits present**

```bash
git -C c:\Users\deshp\Documents\github_repo\agentic_ai log --oneline -8
```

Expected commits (most recent first):
- `feat: admin pages — Dashboard stats, UserList with search/pagination, UserDetail with plan/suspend actions`
- `feat: AdminRoute guard, AdminLayout sidebar, /admin route wiring`
- `feat: admin router — bootstrap, stats, user list/detail/update + tests`
- `feat: admin module skeleton — dependencies, schemas`
- `feat: add is_admin column — migration 0002, model, auth dict`

- [ ] **Step 4: Push**

```bash
cd c:\Users\deshp\Documents\github_repo\agentic_ai
git push origin backend_design
```

---

## Bootstrap Instructions (one-time setup)

After deploying Block G.1:

1. Register your account at the app URL (if not already registered)
2. Call: `POST /admin/bootstrap` with body `{"email": "your@email.com"}`
   - In Swagger UI at `/docs` → expand POST /admin/bootstrap → Try it out
3. Log out and log back in — the admin token is now active
4. Visit `https://your-app.azurestaticapps.net/admin`

This endpoint permanently self-disables once called. Subsequent admins are promoted from the UserDetail page.
