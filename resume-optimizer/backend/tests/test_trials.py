"""Tests for G.2 free trials — registration, effective plan logic, auth responses."""
import os
import sys
from datetime import datetime, timedelta, timezone

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
    expected = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=TRIAL_DAYS)
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
    user = User()
    user.trial_expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    user.plan = PlanType.free
    assert _effective_plan(user) == "pro"


def test_expired_trial_gives_actual_plan():
    """User with past trial_expires_at gets their actual plan."""
    user = User()
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    user.plan = PlanType.free
    assert _effective_plan(user) == "free"


def test_no_trial_gives_actual_plan():
    """User with trial_expires_at=None gets their actual plan."""
    user = User()
    user.trial_expires_at = None
    user.plan = PlanType.free
    assert _effective_plan(user) == "free"


def test_trial_expiry_boundary():
    """Trial is inactive the moment trial_expires_at passes (1 second ago)."""
    user = User()
    user.trial_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    user.plan = PlanType.free
    assert _effective_plan(user) == "free"
