"""Rate limit tests for /auth/login and /auth/register."""
import os
import sys

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_ratelimit.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.session import get_db
from main import app

TEST_DB_URL = "sqlite+aiosqlite:///./test_ratelimit.db"
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
        os.remove("./test_ratelimit.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_rate_limit(client):
    """6th login attempt within a minute returns 429."""
    payload = {"email": "noone@test.com", "password": "wrongpass"}
    for i in range(5):
        r = await client.post("/auth/login", json=payload)
        assert r.status_code == 401, f"Expected 401 on attempt {i + 1}, got {r.status_code}"
    r = await client.post("/auth/login", json=payload)
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_register_rate_limit(client):
    """6th register attempt within a minute returns 429."""
    for i in range(5):
        r = await client.post("/auth/register", json={
            "email": f"ratelimit_spam{i}@test.com",
            "password": "Test1234!",
            "full_name": "Spam",
        })
        assert r.status_code in (200, 400), f"Expected 200/400 on attempt {i + 1}, got {r.status_code}"
    r = await client.post("/auth/register", json={
        "email": "ratelimit_spam5@test.com",
        "password": "Test1234!",
        "full_name": "Spam",
    })
    assert r.status_code == 429
