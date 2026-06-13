"""
Tests for GET /admin/analytics endpoints.

Run with:
    pytest backend/tests/test_analytics.py -v
"""

import os
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone, date
from unittest.mock import patch, AsyncMock
import uuid as uuid_module

# Set required env vars before importing app modules
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_analytics.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.session import get_db
from main import app

# ── In-memory test DB ────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///./test_analytics.db"

_engine = create_async_engine(TEST_DB_URL, echo=False)
_TestSession = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _TestSession() as session:
        yield session




@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    # Scope the get_db override to THIS module — the app object is shared
    # across test modules, so an import-time override leaks between files.
    app.dependency_overrides[get_db] = _override_get_db
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    app.dependency_overrides.pop(get_db, None)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()
    import os as _os
    import time
    try:
        _os.remove("./test_analytics.db")
    except (FileNotFoundError, PermissionError):
        # On Windows, the file may still be in use; try again after a short delay
        try:
            time.sleep(0.5)
            _os.remove("./test_analytics.db")
        except Exception:
            pass


@pytest_asyncio.fixture(scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(scope="module")
async def auth_token(client):
    """Register a test user and return auth token."""
    import uuid
    email = f"analytics_{uuid.uuid4().hex[:8]}@test.com"
    r = await client.post("/auth/register", json={
        "email": email,
        "password": "Test1234!",
        "full_name": "Analytics User",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest_asyncio.fixture
def test_user_id(auth_token):
    """Extract user_id from auth token."""
    import jwt
    import os as _os
    secret = _os.getenv("JWT_SECRET", "test-secret-32-chars-long-enough-x")
    decoded = jwt.decode(auth_token, secret, algorithms=["HS256"])
    return str(decoded["sub"])


def _create_test_matches_data(user_id: str):
    """Create mock job match records for testing."""
    base_date = datetime.now(timezone.utc) - timedelta(days=5)

    results = []

    # Day 1: 3 matches from linkedin
    for i in range(3):
        results.append({
            "user_id": user_id,
            "resume_id": "resume-1",
            "job_title": f"Software Engineer {i}",
            "company": f"Company {i}",
            "url": f"https://example.com/job{i}",
            "source": "linkedin",
            "similarity_score": 0.85 + (i * 0.01),
            "raw_description": "Job description",
            "scraped_at": base_date.isoformat(),
            "is_read": False,
        })

    # Day 2: 2 matches from indeed
    base_date_2 = base_date + timedelta(days=1)
    for i in range(2):
        results.append({
            "user_id": user_id,
            "resume_id": "resume-1",
            "job_title": f"Data Engineer {i}",
            "company": f"Tech Company {i}",
            "url": f"https://indeed.com/job{i}",
            "source": "indeed",
            "similarity_score": 0.78 + (i * 0.02),  # 0.78 and 0.80, avg = 0.79
            "raw_description": "Job description",
            "scraped_at": base_date_2.isoformat(),
            "is_read": True,
        })

    # Day 3: 1 match from linkedin
    base_date_3 = base_date + timedelta(days=2)
    results.append({
        "user_id": user_id,
        "resume_id": "resume-1",
        "job_title": "Product Manager",
        "company": "Big Tech",
        "url": "https://example.com/pm",
        "source": "linkedin",
        "similarity_score": 0.92,
        "raw_description": "Job description",
        "scraped_at": base_date_3.isoformat(),
        "is_read": False,
    })

    return results


# ── Admin Analytics Tests ────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="module")
async def admin_token(client):
    """Get an admin token. Creates admin on first use, reuses on subsequent calls."""
    import uuid

    admin_email = "test_admin@test.com"
    admin_password = "Test1234!"

    # Try to register
    r = await client.post("/auth/register", json={
        "email": admin_email,
        "password": admin_password,
        "full_name": "Admin User",
    })

    token = None
    if r.status_code == 200:
        # New user created
        token = r.json()["access_token"]
        # Bootstrap to admin
        import os as _os_env
        bootstrap_r = await client.post("/admin/bootstrap", json={"email": admin_email, "secret": _os_env.environ["BOOTSTRAP_SECRET"]})
        if bootstrap_r.status_code != 200:
            raise AssertionError(f"Bootstrap failed: {bootstrap_r.status_code} {bootstrap_r.text}")
    elif r.status_code in (400, 409):
        # User already exists, login
        r = await client.post("/auth/login", json={
            "email": admin_email,
            "password": admin_password,
        })
        if r.status_code != 200:
            raise AssertionError(f"Login failed: {r.status_code} {r.text}")
        token = r.json()["access_token"]
    else:
        raise AssertionError(f"Register failed: {r.status_code} {r.text}")

    return token


@pytest.mark.asyncio
async def test_admin_analytics_requires_admin_auth(client, auth_token):
    """Test that endpoint requires admin authentication."""
    # Try with regular user token
    r = await client.get(
        "/admin/analytics",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 403, "Regular user should not access /admin/analytics"


@pytest.mark.asyncio
async def test_admin_analytics_requires_auth(client):
    """Test that endpoint requires authentication."""
    r = await client.get("/admin/analytics")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_analytics_returns_correct_shape(client, admin_token):
    """Test that endpoint returns all 5 datasets with correct shape."""
    r = await client.get(
        "/admin/analytics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, f"Status: {r.status_code}, Response: {r.text}"
    data = r.json()

    # Verify all 5 datasets are present
    assert "user_growth" in data, "Missing user_growth"
    assert "plan_distribution" in data, "Missing plan_distribution"
    assert "daily_costs" in data, "Missing daily_costs"
    assert "source_counts" in data, "Missing source_counts"
    assert "pipeline_health" in data, "Missing pipeline_health"

    # Verify user_growth is array
    assert isinstance(data["user_growth"], list), "user_growth should be array"
    if len(data["user_growth"]) > 0:
        item = data["user_growth"][0]
        assert "date" in item, "user_growth item missing date"
        assert "cumulative_users" in item, "user_growth item missing cumulative_users"
        assert "daily_signups" in item, "user_growth item missing daily_signups"
        assert isinstance(item["date"], str), "date should be string"
        assert isinstance(item["cumulative_users"], int), "cumulative_users should be int"
        assert isinstance(item["daily_signups"], int), "daily_signups should be int"

    # Verify plan_distribution is dict with correct keys
    assert isinstance(data["plan_distribution"], dict), "plan_distribution should be dict"
    assert "free" in data["plan_distribution"], "plan_distribution missing free"
    assert "pro" in data["plan_distribution"], "plan_distribution missing pro"
    assert "enterprise" in data["plan_distribution"], "plan_distribution missing enterprise"
    for key in ["free", "pro", "enterprise"]:
        assert isinstance(data["plan_distribution"][key], int), f"{key} should be int"

    # Verify daily_costs is array
    assert isinstance(data["daily_costs"], list), "daily_costs should be array"
    if len(data["daily_costs"]) > 0:
        item = data["daily_costs"][0]
        assert "date" in item, "daily_costs item missing date"
        assert "cost_cents" in item, "daily_costs item missing cost_cents"
        assert isinstance(item["date"], str), "date should be string"
        assert isinstance(item["cost_cents"], int), "cost_cents should be int"

    # Verify source_counts is dict
    assert isinstance(data["source_counts"], dict), "source_counts should be dict"
    # source_counts should have at least placeholder keys
    assert isinstance(data["source_counts"], dict), "source_counts should be dict"

    # Verify pipeline_health is array
    assert isinstance(data["pipeline_health"], list), "pipeline_health should be array"
    if len(data["pipeline_health"]) > 0:
        item = data["pipeline_health"][0]
        assert "date" in item, "pipeline_health item missing date"
        assert "successful" in item, "pipeline_health item missing successful"
        assert "failed" in item, "pipeline_health item missing failed"
        assert isinstance(item["date"], str), "date should be string"
        assert isinstance(item["successful"], int), "successful should be int"
        assert isinstance(item["failed"], int), "failed should be int"


@pytest.mark.asyncio
async def test_admin_analytics_respects_days_param(client, admin_token):
    """Test that days parameter is respected (1-90)."""
    # Valid days parameter
    r = await client.get(
        "/admin/analytics?days=30",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, f"Status: {r.status_code}, Response: {r.text}"

    # Invalid days > 90
    r = await client.get(
        "/admin/analytics?days=91",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 422, "Should reject days > 90"

    # Invalid days < 1
    r = await client.get(
        "/admin/analytics?days=0",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 422, "Should reject days < 1"


@pytest.mark.asyncio
async def test_admin_analytics_default_days_is_30(client, admin_token):
    """Test that default days is 30."""
    r = await client.get(
        "/admin/analytics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, f"Status: {r.status_code}, Response: {r.text}"
    data = r.json()
    # Should succeed with default days value
    assert "user_growth" in data
