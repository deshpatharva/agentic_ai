"""
Tests for /api/optimize endpoint with SSE streaming.

Run with:
    pytest backend/tests/test_optimize_endpoint.py -v
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Set required env vars before importing app modules
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_optimize.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from db.models import Base
from db.session import get_db
from main import app

# ── In-memory test DB ────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///./test_optimize.db"

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
    import os as _os
    try:
        _os.remove("./test_optimize.db")
    except FileNotFoundError:
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_optimize_endpoint_exists(client):
    """Verify endpoint exists (status != 404)."""
    # Register a user first
    r = await client.post("/auth/register", json={
        "email": "optimize@test.com",
        "password": "Test1234!",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]

    # POST to /api/optimize endpoint
    r = await client.post(
        "/api/optimize",
        json={
            "resume_text": "Sample resume text",
            "jd_text": "Sample job description",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # Should NOT be 404 (endpoint exists)
    assert r.status_code != 404, f"Endpoint not found: {r.status_code} {r.text}"


@pytest.mark.asyncio
async def test_optimize_requires_resume_and_jd(client):
    """Verify validation (expects 422 for empty json)."""
    # Register a user first
    r = await client.post("/auth/register", json={
        "email": "validate@test.com",
        "password": "Test1234!",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]

    # POST to /api/optimize with empty json (missing required fields)
    r = await client.post(
        "/api/optimize",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Should be 422 (Unprocessable Entity) for validation error
    assert r.status_code == 422, f"Expected 422 validation error, got {r.status_code}: {r.text}"
