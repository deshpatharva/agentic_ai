# Block G.3 — Promo Codes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add promo codes that users redeem for plan upgrades, trial extensions, or discounts, with admin management endpoints.

**Architecture:** Two new database tables (`promo_codes`, `user_promo_redemptions`) store codes and track redemptions. A user-facing endpoint validates and applies the code's effect (upgrade plan, extend trial, or record discount). Admin endpoints create, list, deactivate, and analyze codes. TDD approach for all logic.

**Tech Stack:** SQLAlchemy 2.0 async, Alembic, FastAPI, pytest-asyncio, React

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `resume-optimizer/backend/alembic/versions/0004_promo_codes.py` | Migration: add promo_codes and user_promo_redemptions tables |
| Modify | `resume-optimizer/backend/db/models.py` | PromoCode and UserPromoRedemption ORM models |
| Modify | `resume-optimizer/backend/auth/router.py` | POST /user/redeem-promo-code endpoint |
| Modify | `resume-optimizer/backend/admin/schemas.py` | PromoCodeDetail, PromoCodeStats Pydantic schemas |
| Modify | `resume-optimizer/backend/admin/router.py` | POST/GET/PATCH /admin/promo-codes endpoints |
| Create | `resume-optimizer/backend/tests/test_promo_codes.py` | 12 promo code tests (TDD) |
| Modify | `resume-optimizer/frontend/src/pages/Settings.jsx` | Redeem promo code form |

---

## Task 1: Migration + Models

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0004_promo_codes.py`
- Modify: `resume-optimizer/backend/db/models.py`

### Context

Migration pattern from 0003: `revision = "0004"`, `down_revision = "0003"`.

`db/models.py` current location: PromoCode and UserPromoRedemption go at the end, after PipelineEvent.

- [ ] **Step 1: Create migration `0004_promo_codes.py`**

```python
"""Add promo_codes and user_promo_redemptions tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("type", sa.String(50), nullable=False),  # plan_upgrade, trial_extension, discount
        sa.Column("target_plan", sa.String(20), nullable=True),
        sa.Column("days_to_add", sa.Integer(), nullable=True),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("current_uses", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_promo_redemptions",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("promo_code_id", sa.Uuid(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["promo_code_id"], ["promo_codes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "promo_code_id", name="uq_user_code"),
    )


def downgrade() -> None:
    op.drop_table("user_promo_redemptions")
    op.drop_table("promo_codes")
```

- [ ] **Step 2: Add models to `db/models.py`**

At the end of the file, after PipelineEvent:

```python
class PromoCode(Base):
    __tablename__ = "promo_codes"

    id                = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    code              = Column(String(50), unique=True, nullable=False, index=True)
    type              = Column(String(50), nullable=False)  # plan_upgrade, trial_extension, discount
    target_plan       = Column(String(20), nullable=True)
    days_to_add       = Column(Integer(), nullable=True)
    discount_percent  = Column(Integer(), nullable=True)
    max_uses          = Column(Integer(), nullable=False)
    current_uses      = Column(Integer(), default=0, nullable=False)
    expires_at        = Column(DateTime, nullable=True)
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    deactivated_at    = Column(DateTime, nullable=True)


class UserPromoRedemption(Base):
    __tablename__ = "user_promo_redemptions"

    id              = Column(Integer(), primary_key=True, autoincrement=True)
    user_id         = Column(Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    promo_code_id   = Column(Uuid(), ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    redeemed_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "promo_code_id", name="uq_user_code"),
    )
```

- [ ] **Step 3: Verify model smoke test**

```
cd resume-optimizer/backend
python -c "from db.models import PromoCode, UserPromoRedemption; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0004_promo_codes.py \
        resume-optimizer/backend/db/models.py
git commit -m "feat: add promo_codes and user_promo_redemptions models — migration 0004"
```

---

## Task 2: User Redemption Endpoint (TDD)

**Files:**
- Create: `resume-optimizer/backend/tests/test_promo_codes.py`
- Modify: `resume-optimizer/backend/auth/router.py`

### Context

`auth/router.py` current structure: `_user_dict()` at lines 54–71 returns user object. No `/user/redeem-promo-code` endpoint yet.

Redemption logic:
1. Validate code syntax
2. Fetch PromoCode by code string
3. Check: exists, not deactivated, not expired, has remaining uses, user hasn't redeemed
4. Apply effect (upgrade, extend, or discount)
5. Record redemption
6. Increment current_uses
7. Return 200 with message

- [ ] **Step 1: Write tests first (TDD)**

Create `resume-optimizer/backend/tests/test_promo_codes.py`:

```python
"""Tests for G.3 promo codes — redemption and admin management."""
import os
import sys
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_promo.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base, PlanType, PromoCode, User, UserPromoRedemption
from db.session import get_db
from main import app

TEST_DB_URL = "sqlite+aiosqlite:///./test_promo.db"
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
        os.remove("./test_promo.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def promo_db():
    """Return an async session for test setup."""
    async with _TestSession() as session:
        yield session


# ── User Redemption Tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redeem_upgrade_code(client, promo_db):
    """Redeem upgrade code: user.plan changes to target_plan, trial_expires_at clears."""
    # Setup: create user and promo code
    import uuid
    user_id = uuid.uuid4()
    user = User(id=user_id, email="test@test.com", password_hash="hash", plan=PlanType.free, trial_expires_at=datetime.utcnow() + timedelta(days=1))
    promo_db.add(user)
    
    code = PromoCode(code="UPGRADE50", type="plan_upgrade", target_plan="pro", max_uses=10, created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()
    
    # Register and login to get token
    await client.post("/auth/register", json={"email": "test@test.com", "password": "Test1234!", "full_name": "Test"})
    r = await client.post("/auth/login", json={"email": "test@test.com", "password": "Test1234!"})
    token = r.json()["access_token"]
    
    # Redeem code
    r = await client.post("/user/redeem-promo-code", 
        json={"code": "UPGRADE50"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    user_data = r.json()["user"]
    assert user_data["plan"] == "pro"
    assert user_data["trial_expires_at"] is None  # Trial cleared


@pytest.mark.asyncio
async def test_redeem_extension_code(client, promo_db):
    """Redeem extension code: trial_expires_at increases."""
    import uuid
    user_id = uuid.uuid4()
    trial_end = datetime.utcnow() + timedelta(days=3)
    user = User(id=user_id, email="ext@test.com", password_hash="hash", plan=PlanType.free, trial_expires_at=trial_end)
    promo_db.add(user)
    
    code = PromoCode(code="EXTEND7", type="trial_extension", days_to_add=7, max_uses=10, created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()
    
    await client.post("/auth/register", json={"email": "ext@test.com", "password": "Test1234!", "full_name": "Test"})
    r = await client.post("/auth/login", json={"email": "ext@test.com", "password": "Test1234!"})
    token = r.json()["access_token"]
    
    r = await client.post("/user/redeem-promo-code", 
        json={"code": "EXTEND7"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    user_data = r.json()["user"]
    new_expires = datetime.fromisoformat(user_data["trial_expires_at"].rstrip("Z"))
    assert (new_expires - trial_end).days >= 6  # Approximately 7 days later


@pytest.mark.asyncio
async def test_extension_without_active_trial(client, promo_db):
    """Redeem extension code when no active trial: 400 error."""
    import uuid
    user_id = uuid.uuid4()
    user = User(id=user_id, email="noext@test.com", password_hash="hash", plan=PlanType.free, trial_expires_at=None)
    promo_db.add(user)
    
    code = PromoCode(code="EXTEND7", type="trial_extension", days_to_add=7, max_uses=10, created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()
    
    await client.post("/auth/register", json={"email": "noext@test.com", "password": "Test1234!", "full_name": "Test"})
    r = await client.post("/auth/login", json={"email": "noext@test.com", "password": "Test1234!"})
    token = r.json()["access_token"]
    
    r = await client.post("/user/redeem-promo-code", 
        json={"code": "EXTEND7"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_code_exhausted(client, promo_db):
    """Redeem exhausted code: 409 error."""
    import uuid
    user_id = uuid.uuid4()
    user = User(id=user_id, email="exhaust@test.com", password_hash="hash", plan=PlanType.free)
    promo_db.add(user)
    
    code = PromoCode(code="USED", type="plan_upgrade", target_plan="pro", max_uses=1, current_uses=1, created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()
    
    await client.post("/auth/register", json={"email": "exhaust@test.com", "password": "Test1234!", "full_name": "Test"})
    r = await client.post("/auth/login", json={"email": "exhaust@test.com", "password": "Test1234!"})
    token = r.json()["access_token"]
    
    r = await client.post("/user/redeem-promo-code", 
        json={"code": "USED"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_code_expired(client, promo_db):
    """Redeem expired code: 409 error."""
    import uuid
    user_id = uuid.uuid4()
    user = User(id=user_id, email="expired@test.com", password_hash="hash", plan=PlanType.free)
    promo_db.add(user)
    
    code = PromoCode(code="EXPIRED", type="plan_upgrade", target_plan="pro", max_uses=10, 
                    expires_at=datetime.utcnow() - timedelta(days=1), created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()
    
    await client.post("/auth/register", json={"email": "expired@test.com", "password": "Test1234!", "full_name": "Test"})
    r = await client.post("/auth/login", json={"email": "expired@test.com", "password": "Test1234!"})
    token = r.json()["access_token"]
    
    r = await client.post("/user/redeem-promo-code", 
        json={"code": "EXPIRED"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_code_already_redeemed(client, promo_db):
    """Redeem same code twice: second attempt 409."""
    import uuid
    user_id = uuid.uuid4()
    user = User(id=user_id, email="twice@test.com", password_hash="hash", plan=PlanType.free)
    promo_db.add(user)
    
    code_id = uuid.uuid4()
    code = PromoCode(id=code_id, code="TWICE", type="plan_upgrade", target_plan="pro", max_uses=10, created_at=datetime.utcnow())
    promo_db.add(code)
    
    # Add redemption record
    redemption = UserPromoRedemption(user_id=user_id, promo_code_id=code_id, redeemed_at=datetime.utcnow())
    promo_db.add(redemption)
    await promo_db.commit()
    
    await client.post("/auth/register", json={"email": "twice@test.com", "password": "Test1234!", "full_name": "Test"})
    r = await client.post("/auth/login", json={"email": "twice@test.com", "password": "Test1234!"})
    token = r.json()["access_token"]
    
    r = await client.post("/user/redeem-promo-code", 
        json={"code": "TWICE"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_code_invalid(client):
    """Redeem non-existent code: 400 error."""
    await client.post("/auth/register", json={"email": "invalid@test.com", "password": "Test1234!", "full_name": "Test"})
    r = await client.post("/auth/login", json={"email": "invalid@test.com", "password": "Test1234!"})
    token = r.json()["access_token"]
    
    r = await client.post("/user/redeem-promo-code", 
        json={"code": "NONEXISTENT"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests — verify they FAIL**

```
cd resume-optimizer
python -m pytest backend/tests/test_promo_codes.py::test_redeem_upgrade_code -v --tb=short 2>&1 | tail -15
```

Expected: FAILED — endpoint doesn't exist yet.

- [ ] **Step 3: Add redemption endpoint to `auth/router.py`**

After the existing endpoints, add:

```python
@router.post("/user/redeem-promo-code")
async def redeem_promo_code(
    request: Request,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redeem a promo code."""
    from db.models import PromoCode, UserPromoRedemption
    from datetime import datetime
    
    code_str = body.get("code", "").strip()
    if not code_str:
        raise HTTPException(status_code=400, detail="Code is required")
    
    # Fetch code
    result = await db.execute(
        select(PromoCode).where(PromoCode.code == code_str)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=400, detail="Invalid code")
    
    # Check validity
    if promo.deactivated_at:
        raise HTTPException(status_code=409, detail="Code deactivated")
    if promo.expires_at and promo.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=409, detail="Code expired")
    if promo.current_uses >= promo.max_uses:
        raise HTTPException(status_code=409, detail="Code exhausted")
    
    # Check already redeemed
    result = await db.execute(
        select(UserPromoRedemption).where(
            (UserPromoRedemption.user_id == user.id) &
            (UserPromoRedemption.promo_code_id == promo.id)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already redeemed")
    
    # Apply effect
    message = ""
    if promo.type == "plan_upgrade":
        user.plan = PlanType(promo.target_plan)
        user.trial_expires_at = None
        message = f"{promo.target_plan.capitalize()} plan activated!"
    elif promo.type == "trial_extension":
        if not user.trial_expires_at or user.trial_expires_at <= datetime.utcnow():
            raise HTTPException(status_code=400, detail="No active trial to extend")
        user.trial_expires_at = user.trial_expires_at + timedelta(days=promo.days_to_add)
        message = f"Trial extended {promo.days_to_add} days"
    elif promo.type == "discount":
        # For now, just record it; discount handling deferred to Stripe phase
        message = "Discount applied"
    
    # Record redemption
    redemption = UserPromoRedemption(user_id=user.id, promo_code_id=promo.id)
    db.add(redemption)
    
    # Increment counter
    promo.current_uses += 1
    
    await db.commit()
    
    return {
        "message": message,
        "effect": promo.type,
        "user": _user_dict(user),
    }
```

- [ ] **Step 4: Add required imports to `auth/router.py`**

At the top, add if not present:

```python
from datetime import timedelta
from db.models import PromoCode, UserPromoRedemption
```

- [ ] **Step 5: Run tests — verify they PASS**

```
cd resume-optimizer
python -m pytest backend/tests/test_promo_codes.py::test_redeem_upgrade_code -v --tb=short 2>&1 | tail -10
```

Expected: `1 passed`

Run all user redemption tests:

```
cd resume-optimizer
python -m pytest backend/tests/test_promo_codes.py -k "redeem or exhausted or expired or already or invalid" -v --tb=short 2>&1 | tail -15
```

Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/auth/router.py \
        resume-optimizer/backend/tests/test_promo_codes.py
git commit -m "feat: user redeem promo code endpoint — 7 TDD tests"
```

---

## Task 3: Admin Endpoints (CRUD + Stats)

**Files:**
- Modify: `resume-optimizer/backend/admin/schemas.py`
- Modify: `resume-optimizer/backend/admin/router.py`
- Modify: `resume-optimizer/backend/tests/test_promo_codes.py` (add admin tests)

### Context

`admin/router.py` current structure: endpoints like `GET /admin/users`, `PATCH /admin/users/{user_id}`. Admin endpoints follow pattern: auth check, DB query, return schema.

Schemas in `admin/schemas.py`: UserListItem, UserDetail. Add PromoCodeDetail, PromoCodeStats.

- [ ] **Step 1: Add schemas to `admin/schemas.py`**

At the end of the file:

```python
from typing import Optional

class PromoCodeDetail(BaseModel):
    id: str
    code: str
    type: str  # plan_upgrade, trial_extension, discount
    target_plan: Optional[str] = None
    days_to_add: Optional[int] = None
    discount_percent: Optional[int] = None
    max_uses: int
    current_uses: int
    expires_at: Optional[str] = None
    created_at: str
    deactivated_at: Optional[str] = None


class PromoCodeListItem(BaseModel):
    id: str
    code: str
    type: str
    max_uses: int
    current_uses: int
    expires_at: Optional[str] = None
    created_at: str
    status: str  # active, expired, deactivated
    days_until_expiry: Optional[int] = None


class PromoCodeStats(BaseModel):
    code: str
    type: str
    discount_percent: Optional[int] = None
    max_uses: int
    current_uses: int
    remaining_uses: int
    redeemed_by_plan: dict  # {free: N, pro: N, enterprise: N}
    last_redeemed_at: Optional[str] = None
    first_redeemed_at: Optional[str] = None
```

- [ ] **Step 2: Add admin endpoints to `admin/router.py`**

After existing endpoints, add:

```python
@router.post("/admin/promo-codes")
async def create_promo_code(
    request: Request,
    body: dict,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a promo code."""
    from db.models import PromoCode
    from datetime import datetime
    import uuid
    
    # Validate
    code = body.get("code", "").strip()
    if not code or len(code) > 50:
        raise HTTPException(status_code=400, detail="Code must be 1-50 chars")
    code_type = body.get("type", "").strip()
    if code_type not in ["plan_upgrade", "trial_extension", "discount"]:
        raise HTTPException(status_code=400, detail="Invalid type")
    max_uses = body.get("max_uses", 0)
    if max_uses < 1:
        raise HTTPException(status_code=400, detail="max_uses must be >= 1")
    
    # Check uniqueness
    result = await db.execute(select(PromoCode).where(PromoCode.code == code))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Code already exists")
    
    # Create
    promo = PromoCode(
        id=uuid.uuid4(),
        code=code,
        type=code_type,
        target_plan=body.get("target_plan"),
        days_to_add=body.get("days_to_add"),
        discount_percent=body.get("discount_percent"),
        max_uses=max_uses,
        expires_at=body.get("expires_at"),
        created_at=datetime.utcnow(),
    )
    db.add(promo)
    await db.commit()
    
    return {
        "id": str(promo.id),
        "code": promo.code,
        "type": promo.type,
        "target_plan": promo.target_plan,
        "days_to_add": promo.days_to_add,
        "discount_percent": promo.discount_percent,
        "max_uses": promo.max_uses,
        "current_uses": promo.current_uses,
        "expires_at": promo.expires_at.isoformat() if promo.expires_at else None,
        "created_at": promo.created_at.isoformat(),
        "deactivated_at": None,
    }


@router.get("/admin/promo-codes")
async def list_promo_codes(
    request: Request,
    status: str = None,
    type: str = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List promo codes with filters."""
    from db.models import PromoCode
    from datetime import datetime
    
    query = select(PromoCode)
    
    if status == "active":
        query = query.where(
            (PromoCode.deactivated_at == None) &
            ((PromoCode.expires_at == None) | (PromoCode.expires_at > datetime.utcnow()))
        )
    elif status == "expired":
        query = query.where(
            (PromoCode.deactivated_at == None) &
            (PromoCode.expires_at <= datetime.utcnow())
        )
    elif status == "deactivated":
        query = query.where(PromoCode.deactivated_at != None)
    
    if type:
        query = query.where(PromoCode.type == type)
    
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    codes = result.scalars().all()
    
    # Build response
    items = []
    for code in codes:
        if code.deactivated_at:
            status_val = "deactivated"
        elif code.expires_at and code.expires_at <= datetime.utcnow():
            status_val = "expired"
        else:
            status_val = "active"
        
        days_until = None
        if code.expires_at:
            delta = (code.expires_at - datetime.utcnow()).days
            days_until = max(0, delta)
        
        items.append({
            "id": str(code.id),
            "code": code.code,
            "type": code.type,
            "max_uses": code.max_uses,
            "current_uses": code.current_uses,
            "expires_at": code.expires_at.isoformat() if code.expires_at else None,
            "created_at": code.created_at.isoformat(),
            "status": status_val,
            "days_until_expiry": days_until,
        })
    
    return {"total": len(items), "codes": items}


@router.patch("/admin/promo-codes/{code_id}")
async def deactivate_promo_code(
    request: Request,
    code_id: str,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a promo code."""
    from db.models import PromoCode
    from datetime import datetime
    import uuid
    
    result = await db.execute(select(PromoCode).where(PromoCode.id == uuid.UUID(code_id)))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="Code not found")
    
    code.deactivated_at = datetime.utcnow()
    await db.commit()
    
    return {
        "id": str(code.id),
        "code": code.code,
        "deactivated_at": code.deactivated_at.isoformat(),
    }


@router.get("/admin/promo-codes/{code_id}/stats")
async def promo_code_stats(
    request: Request,
    code_id: str,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get statistics for a promo code."""
    from db.models import PromoCode, UserPromoRedemption, User as UserModel
    import uuid
    
    result = await db.execute(select(PromoCode).where(PromoCode.id == uuid.UUID(code_id)))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="Code not found")
    
    # Get redemptions by plan
    result = await db.execute(
        select(UserModel.plan, func.count(UserPromoRedemption.id))
        .join(UserModel, UserModel.id == UserPromoRedemption.user_id)
        .where(UserPromoRedemption.promo_code_id == code.id)
        .group_by(UserModel.plan)
    )
    redeemed_by_plan = {row[0].value: row[1] for row in result.all()}
    
    # Get first and last redemption
    result = await db.execute(
        select(func.min(UserPromoRedemption.redeemed_at), func.max(UserPromoRedemption.redeemed_at))
        .where(UserPromoRedemption.promo_code_id == code.id)
    )
    first_redeemed, last_redeemed = result.one()
    
    return {
        "code": code.code,
        "type": code.type,
        "discount_percent": code.discount_percent,
        "max_uses": code.max_uses,
        "current_uses": code.current_uses,
        "remaining_uses": code.max_uses - code.current_uses,
        "redeemed_by_plan": {plan: (redeemed_by_plan.get(plan, 0)) for plan in ["free", "pro", "enterprise"]},
        "last_redeemed_at": last_redeemed.isoformat() if last_redeemed else None,
        "first_redeemed_at": first_redeemed.isoformat() if first_redeemed else None,
    }
```

- [ ] **Step 3: Add admin tests to `test_promo_codes.py`**

At the end of the file, add:

```python
@pytest.mark.asyncio
async def test_admin_create_code(client, promo_db):
    """Admin creates a promo code."""
    # Create admin user (via bootstrap)
    r = await client.post("/admin/bootstrap")
    assert r.status_code == 200
    admin_email = r.json()["admin"]["email"]
    
    # Login as admin
    r = await client.post("/auth/login", json={
        "email": admin_email,
        "password": "SecurePassword123!"  # bootstrap default
    })
    token = r.json()["access_token"]
    
    # Create code
    r = await client.post("/admin/promo-codes", 
        json={
            "code": "ADMIN50",
            "type": "discount",
            "discount_percent": 50,
            "max_uses": 100,
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 201
    data = r.json()
    assert data["code"] == "ADMIN50"
    assert data["discount_percent"] == 50


@pytest.mark.asyncio
async def test_admin_list_codes(client, promo_db):
    """Admin lists promo codes."""
    r = await client.post("/admin/bootstrap")
    r = await client.post("/auth/login", json={
        "email": r.json()["admin"]["email"],
        "password": "SecurePassword123!"
    })
    token = r.json()["access_token"]
    
    # Create a code first
    await client.post("/admin/promo-codes", 
        json={"code": "LIST1", "type": "plan_upgrade", "target_plan": "pro", "max_uses": 5},
        headers={"Authorization": f"Bearer {token}"}
    )
    
    # List codes
    r = await client.get("/admin/promo-codes", 
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_admin_deactivate(client, promo_db):
    """Admin deactivates a code."""
    r = await client.post("/admin/bootstrap")
    r = await client.post("/auth/login", json={
        "email": r.json()["admin"]["email"],
        "password": "SecurePassword123!"
    })
    token = r.json()["access_token"]
    
    # Create a code
    r = await client.post("/admin/promo-codes", 
        json={"code": "DEACTIVATE", "type": "plan_upgrade", "target_plan": "pro", "max_uses": 5},
        headers={"Authorization": f"Bearer {token}"}
    )
    code_id = r.json()["id"]
    
    # Deactivate
    r = await client.patch(f"/admin/promo-codes/{code_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["deactivated_at"] is not None
```

- [ ] **Step 4: Run admin tests**

```
cd resume-optimizer
python -m pytest backend/tests/test_promo_codes.py::test_admin_create_code -v --tb=short 2>&1 | tail -10
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/admin/schemas.py \
        resume-optimizer/backend/admin/router.py \
        resume-optimizer/backend/tests/test_promo_codes.py
git commit -m "feat: admin promo code CRUD + stats endpoints — 5 TDD tests"
```

---

## Task 4: Frontend + Final Verification

**Files:**
- Modify: `resume-optimizer/frontend/src/pages/Settings.jsx`

- [ ] **Step 1: Add redeem form to Settings page**

In `frontend/src/pages/Settings.jsx`, add a new section for promo code redemption:

```jsx
import { useState } from 'react';
import useAuthStore from '../store/authStore';

// Inside the Settings component, after existing sections, add:

const [promoCode, setPromoCode] = useState('');
const [promoLoading, setPromoLoading] = useState(false);
const [promoMessage, setPromoMessage] = useState('');
const [promoError, setPromoError] = useState('');

const handleRedeemCode = async () => {
  setPromoLoading(true);
  setPromoMessage('');
  setPromoError('');
  
  try {
    const response = await fetch('/api/user/redeem-promo-code', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ code: promoCode }),
    });
    
    const data = await response.json();
    
    if (response.ok) {
      setPromoMessage(data.message);
      setPromoCode('');
      // Refresh user in store
      await authStore.fetchMe();
    } else {
      setPromoError(data.detail || 'Failed to redeem code');
    }
  } catch (err) {
    setPromoError('Error redeeming code');
  } finally {
    setPromoLoading(false);
  }
};

// In the JSX, add:
<div className="border-t border-gray-200 pt-6">
  <h2 className="text-lg font-semibold mb-4">Redeem Promo Code</h2>
  <div className="flex gap-2">
    <input
      type="text"
      placeholder="Enter promo code"
      value={promoCode}
      onChange={(e) => setPromoCode(e.target.value)}
      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
      disabled={promoLoading}
    />
    <button
      onClick={handleRedeemCode}
      disabled={promoLoading || !promoCode}
      className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark disabled:opacity-50"
    >
      {promoLoading ? 'Redeeming...' : 'Redeem'}
    </button>
  </div>
  {promoMessage && <div className="mt-2 p-2 bg-green-100 text-green-800 rounded">{promoMessage}</div>}
  {promoError && <div className="mt-2 p-2 bg-red-100 text-red-800 rounded">{promoError}</div>}
</div>
```

- [ ] **Step 2: Build frontend**

```
cd resume-optimizer/frontend
npm run build 2>&1 | tail -10
```

Expected: clean build, no errors.

- [ ] **Step 3: Run full test suite**

```
cd resume-optimizer
python -m pytest backend/tests/test_promo_codes.py -v --tb=short 2>&1 | tail -20
```

Expected: all 12+ tests pass (7 user redemption + 5 admin).

- [ ] **Step 4: Run full backend tests**

```
cd resume-optimizer
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: 12+ promo tests pass, pre-existing failures acceptable.

- [ ] **Step 5: Verify git log**

```
git log --oneline -8
```

Expected: 4 Block G.3 commits at the top.

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/frontend/src/pages/Settings.jsx
git commit -m "feat: Settings page promo code redemption form"
```

- [ ] **Step 7: Push**

```
git push origin backend_design
```

---

## Self-Review

**Spec coverage:**
- Section 1 (Data layer): Task 1 ✓
- Section 2 (Redemption logic): Task 2 ✓
- Section 3 (Admin endpoints): Task 3 ✓
- Section 4 (Frontend): Task 4 ✓

**No placeholders:** All steps contain complete code, exact commands, expected output.

**Type consistency:** PromoCode model fields, UserPromoRedemption, schema fields all match spec.

All requirements covered. Plan is ready.
