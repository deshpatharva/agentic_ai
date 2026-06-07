# Block G.2 — Free Trials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every new user a 7-day Pro trial automatically on registration, enforced lazily at request time via an `_effective_plan()` helper in `check_plan_limit`.

**Architecture:** A new `trial_expires_at` nullable DateTime column on `users` (migration 0003). On registration, the field is set to `now + TRIAL_DAYS`. A small `_effective_plan(user)` helper in `auth/dependencies.py` returns `"pro"` when the trial is active, otherwise `user.plan.value`. `check_plan_limit` calls this helper to pick the right `PlanLimit` row — no background job needed. Auth responses expose `trial_expires_at` so the frontend can render a countdown banner.

**Tech Stack:** SQLAlchemy 2.0 async, Alembic, FastAPI, pytest-asyncio, React + TailwindCSS

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `resume-optimizer/backend/alembic/versions/0003_add_trial_expires_at.py` | Migration: add nullable DateTime column |
| Modify | `resume-optimizer/backend/db/models.py` | Add `trial_expires_at` to User |
| Modify | `resume-optimizer/backend/config.py` | Add `TRIAL_DAYS` env var |
| Modify | `resume-optimizer/backend/auth/router.py` | Set trial on register; add to `_user_dict()` |
| Modify | `resume-optimizer/backend/auth/dependencies.py` | `_effective_plan()` helper + update `check_plan_limit` |
| Modify | `resume-optimizer/backend/admin/schemas.py` | Add `trial_expires_at` to `UserListItem`/`UserDetail` |
| Modify | `resume-optimizer/backend/admin/router.py` | Add `trial_expires_at` to `_user_dict()` |
| Create | `resume-optimizer/backend/tests/test_trials.py` | 6 trial tests |
| Create | `resume-optimizer/frontend/src/components/TrialBanner.jsx` | Amber countdown banner |
| Modify | `resume-optimizer/frontend/src/components/layout/Sidebar.jsx` | Mount `TrialBanner` |

---

## Task 1: Migration + model + config

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0003_add_trial_expires_at.py`
- Modify: `resume-optimizer/backend/db/models.py`
- Modify: `resume-optimizer/backend/config.py`

### Context

Migration pattern from `0002_add_is_admin.py`:
- `revision = "0003"`, `down_revision = "0002"`
- Use `op.add_column` with `sa.Column("trial_expires_at", sa.DateTime(), nullable=True)`
- No server default — existing users get `NULL`

`db/models.py` current last column on User (line 46): `created_at = Column(DateTime, ...)`

`config.py` current last non-empty section: `OUTPUTS_CONTAINER` (Azure Storage), `RATE_LIMIT_AUTH`, `LOG_LEVEL`. Add `TRIAL_DAYS` after `LOG_LEVEL`.

- [ ] **Step 1: Create `alembic/versions/0003_add_trial_expires_at.py`**

```python
"""Add trial_expires_at column to users.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("trial_expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "trial_expires_at")
```

- [ ] **Step 2: Add `trial_expires_at` to `db/models.py`**

In the `User` class, after `created_at` (line 46), add:

```python
    trial_expires_at       = Column(DateTime, nullable=True)
```

- [ ] **Step 3: Add `TRIAL_DAYS` to `config.py`**

After the `LOG_LEVEL` line, add:

```python
# ── Free trial ────────────────────────────────────────────────────────────────
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "7"))
```

- [ ] **Step 4: Verify migration smoke test**

```
cd resume-optimizer/backend
python -c "from db.models import User; print(hasattr(User, 'trial_expires_at'))"
```

Expected: `True`

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0003_add_trial_expires_at.py \
        resume-optimizer/backend/db/models.py \
        resume-optimizer/backend/config.py
git commit -m "feat: add trial_expires_at to users — migration 0003, model, config"
```

---

## Task 2: Registration + auth responses + plan-limit helper (TDD)

**Files:**
- Create: `resume-optimizer/backend/tests/test_trials.py`
- Modify: `resume-optimizer/backend/auth/router.py`
- Modify: `resume-optimizer/backend/auth/dependencies.py`

### Context

**`auth/router.py`** current `register` function (line 76–95):
```python
@router.post("/register", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    ...
    user = User(
        email=body.email,
        password_hash=pwd_context.hash(body.password),
        full_name=body.full_name,
    )
```

Current imports in `auth/router.py` (line 5): `from datetime import datetime, timedelta, timezone`
Current config import (line 14): `from config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET, RATE_LIMIT_AUTH`

`_user_dict()` (lines 54–71) builds the user dict returned by login/register/me.

**`auth/dependencies.py`** current `check_plan_limit` (lines 67–99): fetches `PlanLimit` by `user.plan.value` directly (line 72).

The `_effective_plan(user)` helper will be a module-level function (not async, not a dependency) — imported in tests for direct testing and called inside `check_plan_limit`.

- [ ] **Step 1: Create `tests/test_trials.py` (write tests first — TDD)**

```python
"""Tests for G.2 free trials — registration, effective plan logic, auth responses."""
import os
import sys
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_trials.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base, PlanType, User
from db.session import get_db
from main import app
from auth.dependencies import _effective_plan

TEST_DB_URL = "sqlite+aiosqlite:///./test_trials.db"
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
    await _engine.dispose()
    try:
        os.remove("./test_trials.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Registration ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_user_gets_trial(client):
    """Register response includes trial_expires_at ~TRIAL_DAYS from now."""
    from config import TRIAL_DAYS
    r = await client.post("/auth/register", json={
        "email": "trial_new@test.com",
        "password": "Test1234!",
        "full_name": "Trial",
    })
    assert r.status_code == 200
    user_data = r.json()["user"]
    assert user_data["trial_expires_at"] is not None
    expires = datetime.fromisoformat(user_data["trial_expires_at"].rstrip("Z"))
    expected = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
    assert abs((expires - expected).total_seconds()) < 60


@pytest.mark.asyncio
async def test_trial_in_login_response(client):
    """Login response also includes trial_expires_at."""
    await client.post("/auth/register", json={
        "email": "trial_login@test.com",
        "password": "Test1234!",
    })
    r = await client.post("/auth/login", json={
        "email": "trial_login@test.com",
        "password": "Test1234!",
    })
    assert r.status_code == 200
    assert "trial_expires_at" in r.json()["user"]


# ── Effective plan helper ─────────────────────────────────────────────────────

def test_active_trial_gives_pro():
    """User with future trial_expires_at gets effective plan 'pro'."""
    user = object.__new__(User)
    user.trial_expires_at = datetime.utcnow() + timedelta(days=1)
    user.plan = PlanType.free
    assert _effective_plan(user) == "pro"


def test_expired_trial_gives_actual_plan():
    """User with past trial_expires_at gets their actual plan."""
    user = object.__new__(User)
    user.trial_expires_at = datetime.utcnow() - timedelta(days=1)
    user.plan = PlanType.free
    assert _effective_plan(user) == "free"


def test_no_trial_gives_actual_plan():
    """User with trial_expires_at=None gets their actual plan."""
    user = object.__new__(User)
    user.trial_expires_at = None
    user.plan = PlanType.free
    assert _effective_plan(user) == "free"


def test_trial_expiry_boundary():
    """Trial is inactive the moment trial_expires_at passes (1 second ago)."""
    user = object.__new__(User)
    user.trial_expires_at = datetime.utcnow() - timedelta(seconds=1)
    user.plan = PlanType.free
    assert _effective_plan(user) == "free"
```

- [ ] **Step 2: Run tests — verify they FAIL**

```
cd resume-optimizer
python -m pytest backend/tests/test_trials.py -v --tb=short 2>&1 | tail -20
```

Expected: `ImportError: cannot import name '_effective_plan' from 'auth.dependencies'` (helper not defined yet).

- [ ] **Step 3: Add `_effective_plan` helper to `auth/dependencies.py`**

In `resume-optimizer/backend/auth/dependencies.py`, change the import at line 7:

Old:
```python
from datetime import date
```

New:
```python
from datetime import date, datetime
```

Then add this function before `check_plan_limit` (before line 67):

```python
def _effective_plan(user: User) -> str:
    """Return the user's effective plan, honouring an active free trial.

    trial_expires_at is stored as naive UTC (DateTime column). Compare
    against datetime.utcnow() — also naive UTC — to avoid TypeError.
    """
    if user.trial_expires_at and user.trial_expires_at > datetime.utcnow():
        return "pro"
    return user.plan.value
```

- [ ] **Step 4: Update `check_plan_limit` to use `_effective_plan`**

In `auth/dependencies.py`, replace line 72:

Old:
```python
    result = await db.execute(select(PlanLimit).where(PlanLimit.plan == user.plan.value))
```

New:
```python
    result = await db.execute(select(PlanLimit).where(PlanLimit.plan == _effective_plan(user)))
```

- [ ] **Step 5: Update `auth/router.py` — set trial on registration**

**5a.** Change the config import line (line 14) — add `TRIAL_DAYS`:

Old:
```python
from config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET, RATE_LIMIT_AUTH
```

New:
```python
from config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET, RATE_LIMIT_AUTH, TRIAL_DAYS
```

**5b.** In the `register` function, change the `User(...)` constructor call to include `trial_expires_at`:

Old:
```python
    user = User(
        email=body.email,
        password_hash=pwd_context.hash(body.password),
        full_name=body.full_name,
    )
```

New:
```python
    user = User(
        email=body.email,
        password_hash=pwd_context.hash(body.password),
        full_name=body.full_name,
        trial_expires_at=datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
    )
```

**5c.** In `_user_dict()`, add `trial_expires_at` to the returned dict (after `"is_admin"`):

Old (inside the `d = {...}` dict literal):
```python
        "is_admin":    user.is_admin,
        "created_at":  user.created_at.isoformat(),
```

New:
```python
        "is_admin":         user.is_admin,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "created_at":       user.created_at.isoformat(),
```

- [ ] **Step 6: Run tests — verify they PASS**

```
cd resume-optimizer
python -m pytest backend/tests/test_trials.py -v --tb=short 2>&1 | tail -20
```

Expected: `6 passed`

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/auth/router.py \
        resume-optimizer/backend/auth/dependencies.py \
        resume-optimizer/backend/tests/test_trials.py
git commit -m "feat: set trial on registration, _effective_plan helper, update check_plan_limit"
```

---

## Task 3: Admin schemas + router

**Files:**
- Modify: `resume-optimizer/backend/admin/schemas.py`
- Modify: `resume-optimizer/backend/admin/router.py`

### Context

`admin/schemas.py` current `UserListItem` fields: `id`, `email`, `full_name`, `plan`, `is_active`, `is_admin`, `created_at`, `resume_count`. `UserDetail` extends it.

`admin/router.py` `_user_dict()` at lines 20–30 builds the dict. It currently has `"is_admin": user.is_admin` as the last field before `"created_at"`.

- [ ] **Step 1: Update `admin/schemas.py`**

In `UserListItem`, add `trial_expires_at` after `is_admin`:

Old:
```python
class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    plan: str
    is_active: bool
    is_admin: bool
    created_at: str
    resume_count: int
```

New:
```python
from typing import Optional

class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    plan: str
    is_active: bool
    is_admin: bool
    trial_expires_at: Optional[str] = None
    created_at: str
    resume_count: int
```

(`Optional` is already imported at the top of the file — if not, add `from typing import Optional`.)

- [ ] **Step 2: Update `admin/router.py` — add `trial_expires_at` to `_user_dict()`**

In `admin/router.py`, change `_user_dict()` (lines 20–30):

Old:
```python
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
```

New:
```python
def _user_dict(user: User, resume_count: int) -> dict:
    return {
        "id":               str(user.id),
        "email":            user.email,
        "full_name":        user.full_name or "",
        "plan":             user.plan.value,
        "is_active":        user.is_active,
        "is_admin":         user.is_admin,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "created_at":       user.created_at.isoformat(),
        "resume_count":     resume_count,
    }
```

- [ ] **Step 3: Verify import works**

```
cd resume-optimizer/backend
python -c "from admin.schemas import UserListItem; print(UserListItem.__fields__.keys())"
```

Expected output includes `trial_expires_at`.

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/backend/admin/schemas.py \
        resume-optimizer/backend/admin/router.py
git commit -m "feat: add trial_expires_at to admin user list and detail responses"
```

---

## Task 4: Frontend — `TrialBanner` + `Sidebar` update

**Files:**
- Create: `resume-optimizer/frontend/src/components/TrialBanner.jsx`
- Modify: `resume-optimizer/frontend/src/components/layout/Sidebar.jsx`

### Context

`Sidebar.jsx` bottom section (lines 51–70):
```jsx
<div className="px-4 py-4 border-t border-gray-800">
  {user?.plan === 'free' && (
    <Link to="/dashboard/settings" ...>Upgrade to Pro</Link>
  )}
  <div className="flex items-center gap-3"> ...user info... </div>
</div>
```

`TrialBanner` goes just inside the bottom `<div>`, before the "Upgrade to Pro" link. When trial is inactive or expired, it renders nothing — the Upgrade button shows as normal.

- [ ] **Step 1: Create `frontend/src/components/TrialBanner.jsx`**

```jsx
import useAuthStore from '../store/authStore';

export default function TrialBanner() {
  const { user } = useAuthStore();
  if (!user?.trial_expires_at) return null;

  const expires = new Date(user.trial_expires_at);
  const daysLeft = Math.ceil((expires - Date.now()) / 86_400_000);
  if (daysLeft <= 0) return null;

  return (
    <div className="mx-3 mb-2 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2 text-xs text-amber-400">
      <span className="font-semibold">Pro Trial</span>
      {' — '}{daysLeft} day{daysLeft !== 1 ? 's' : ''} left
    </div>
  );
}
```

- [ ] **Step 2: Update `Sidebar.jsx`**

**2a.** Add import at the top (after existing imports):
```jsx
import TrialBanner from '../TrialBanner';
```

**2b.** In the bottom `<div>` (around line 51), add `<TrialBanner />` as the first child:

Old:
```jsx
      <div className="px-4 py-4 border-t border-gray-800">
        {user?.plan === 'free' && (
```

New:
```jsx
      <div className="px-4 py-4 border-t border-gray-800">
        <TrialBanner />
        {user?.plan === 'free' && (
```

- [ ] **Step 3: Build the frontend**

```
cd resume-optimizer/frontend
npm run build 2>&1 | tail -10
```

Expected: clean build, no errors.

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/frontend/src/components/TrialBanner.jsx \
        resume-optimizer/frontend/src/components/layout/Sidebar.jsx
git commit -m "feat: TrialBanner component — amber countdown in sidebar for active trials"
```

---

## Task 5: Final verification + push

- [ ] **Step 1: Run trial tests in isolation**

```
cd resume-optimizer
python -m pytest backend/tests/test_trials.py -v 2>&1 | tail -10
```

Expected: `6 passed`

- [ ] **Step 2: Run full backend test suite**

```
cd resume-optimizer
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: 6 new trial tests pass. Pre-existing cross-module DB isolation failures acceptable.

- [ ] **Step 3: Run frontend build**

```
cd resume-optimizer/frontend
npm run build 2>&1 | tail -10
```

Expected: clean.

- [ ] **Step 4: Verify git log**

```
git log --oneline -5
```

Expected (most recent first):
```
feat: TrialBanner component — amber countdown in sidebar for active trials
feat: add trial_expires_at to admin user list and detail responses
feat: set trial on registration, _effective_plan helper, update check_plan_limit
feat: add trial_expires_at to users — migration 0003, model, config
```

- [ ] **Step 5: Push**

```
git push origin backend_design
```
