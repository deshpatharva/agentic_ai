"""Tests for G.3 promo codes — redemption and admin management."""
import os
import sys
from datetime import datetime, timedelta
import uuid as uuid_module

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
    # Register user first, then set trial state via DB
    await client.post("/auth/register", json={"email": "test_upgrade@test.com", "password": "Test1234!", "full_name": "Test"})

    # Set trial_expires_at directly on the registered user
    from sqlalchemy import update as sa_update
    await promo_db.execute(
        sa_update(User).where(User.email == "test_upgrade@test.com")
        .values(trial_expires_at=datetime.utcnow() + timedelta(days=1))
    )

    code = PromoCode(code="UPGRADE50", type="plan_upgrade", target_plan="pro", max_uses=10, created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()

    r = await client.post("/auth/login", json={"email": "test_upgrade@test.com", "password": "Test1234!"})
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
    trial_end = datetime.utcnow() + timedelta(days=3)

    await client.post("/auth/register", json={"email": "ext@test.com", "password": "Test1234!", "full_name": "Test"})

    from sqlalchemy import update as sa_update
    await promo_db.execute(
        sa_update(User).where(User.email == "ext@test.com")
        .values(trial_expires_at=trial_end)
    )

    code = PromoCode(code="EXTEND7", type="trial_extension", days_to_add=7, max_uses=10, created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()

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
    await client.post("/auth/register", json={"email": "noext@test.com", "password": "Test1234!", "full_name": "Test"})

    # Clear trial_expires_at so the user has no active trial
    from sqlalchemy import update as sa_update
    await promo_db.execute(
        sa_update(User).where(User.email == "noext@test.com")
        .values(trial_expires_at=None)
    )

    # Note: EXTEND7 code was already inserted by test_redeem_extension_code above
    await promo_db.commit()

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
    await client.post("/auth/register", json={"email": "exhaust@test.com", "password": "Test1234!", "full_name": "Test"})

    code = PromoCode(code="USED", type="plan_upgrade", target_plan="pro", max_uses=1, current_uses=1, created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()

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
    await client.post("/auth/register", json={"email": "expired@test.com", "password": "Test1234!", "full_name": "Test"})

    code = PromoCode(code="EXPIRED", type="plan_upgrade", target_plan="pro", max_uses=10,
                    expires_at=datetime.utcnow() - timedelta(days=1), created_at=datetime.utcnow())
    promo_db.add(code)
    await promo_db.commit()

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
    await client.post("/auth/register", json={"email": "twice@test.com", "password": "Test1234!", "full_name": "Test"})

    # Look up the registered user's ID
    from sqlalchemy import select as sa_select
    result = await promo_db.execute(sa_select(User).where(User.email == "twice@test.com"))
    registered_user = result.scalar_one()

    code_id = uuid_module.uuid4()
    code = PromoCode(id=code_id, code="TWICE", type="plan_upgrade", target_plan="pro", max_uses=10, created_at=datetime.utcnow())
    promo_db.add(code)

    # Add redemption record for the registered user
    redemption = UserPromoRedemption(user_id=registered_user.id, promo_code_id=code_id, redeemed_at=datetime.utcnow())
    promo_db.add(redemption)
    await promo_db.commit()

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
