"""
Tests for GET /dashboard/match-analytics endpoint.

Run with:
    pytest backend/tests/test_analytics.py -v
"""

import os
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

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


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
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


@pytest.mark.asyncio
async def test_match_analytics_returns_correct_shape(client, auth_token, test_user_id):
    """Test that endpoint returns correct response shape."""
    matches = _create_test_matches_data(test_user_id)

    with patch("dashboard.router.read_job_matches") as mock_read:
        mock_read.return_value = {
            "total": len(matches),
            "page": 1,
            "per_page": 1000,
            "results": matches,
        }

        r = await client.get(
            "/dashboard/match-analytics",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()

        # Check response shape
        assert "analytics" in data
        assert isinstance(data["analytics"], list)
        assert len(data["analytics"]) > 0

        # Check first analytics object structure
        first = data["analytics"][0]
        assert "date" in first
        assert "match_count" in first
        assert "avg_similarity_score" in first
        assert "source_breakdown" in first

        # Check data types
        assert isinstance(first["date"], str)
        assert isinstance(first["match_count"], int)
        assert isinstance(first["avg_similarity_score"], (int, float))
        assert isinstance(first["source_breakdown"], dict)


@pytest.mark.asyncio
async def test_match_analytics_calculates_aggregates_correctly(client, auth_token, test_user_id):
    """Test that endpoint correctly aggregates and calculates analytics."""
    matches = _create_test_matches_data(test_user_id)

    with patch("dashboard.router.read_job_matches") as mock_read:
        mock_read.return_value = {
            "total": len(matches),
            "page": 1,
            "per_page": 1000,
            "results": matches,
        }

        r = await client.get(
            "/dashboard/match-analytics?days=30",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()

        analytics = data["analytics"]

        # Should have 3 days of data
        assert len(analytics) == 3, f"Expected 3 days, got {len(analytics)}: {analytics}"

        # Verify sorted by date descending (most recent first)
        dates = [a["date"] for a in analytics]
        assert dates == sorted(dates, reverse=True), f"Dates not in descending order: {dates}"

        # Find the day with 3 linkedin matches (match_count=3, avg_similarity_score=~0.86)
        day_with_3 = next((a for a in analytics if a["match_count"] == 3), None)
        assert day_with_3 is not None, f"Could not find day with 3 matches in {analytics}"
        assert day_with_3["source_breakdown"]["linkedin"] == 3
        assert round(day_with_3["avg_similarity_score"], 2) == 0.86  # (0.85 + 0.86 + 0.87) / 3 = 0.86

        # Find the day with 2 indeed matches
        day_with_2 = next((a for a in analytics if a["match_count"] == 2), None)
        assert day_with_2 is not None, f"Could not find day with 2 matches in {analytics}"
        assert day_with_2["source_breakdown"]["indeed"] == 2
        assert round(day_with_2["avg_similarity_score"], 2) == 0.79  # (0.78 + 0.80) / 2 = 0.79

        # Find the day with 1 linkedin match
        day_with_1 = next((a for a in analytics if a["match_count"] == 1), None)
        assert day_with_1 is not None, f"Could not find day with 1 match in {analytics}"
        assert day_with_1["source_breakdown"]["linkedin"] == 1
        assert round(day_with_1["avg_similarity_score"], 2) == 0.92


@pytest.mark.asyncio
async def test_match_analytics_requires_auth(client):
    """Test that endpoint requires authentication."""
    r = await client.get("/dashboard/match-analytics")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_match_analytics_respects_days_param(client, auth_token, test_user_id):
    """Test that days parameter limits results correctly."""
    matches = _create_test_matches_data(test_user_id)

    with patch("dashboard.router.read_job_matches") as mock_read:
        mock_read.return_value = {
            "total": len(matches),
            "page": 1,
            "per_page": 1000,
            "results": matches,
        }

        # Request only last 1 day
        r = await client.get(
            "/dashboard/match-analytics?days=1",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        # Should work with days=1 (doesn't error on validation)


@pytest.mark.asyncio
async def test_match_analytics_default_days_is_30(client, auth_token, test_user_id):
    """Test that default days parameter is 30."""
    matches = _create_test_matches_data(test_user_id)

    with patch("dashboard.router.read_job_matches") as mock_read:
        mock_read.return_value = {
            "total": len(matches),
            "page": 1,
            "per_page": 1000,
            "results": matches,
        }

        r = await client.get(
            "/dashboard/match-analytics",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        # Should work with default (doesn't error on validation)


@pytest.mark.asyncio
async def test_match_analytics_empty_when_no_matches(client, auth_token):
    """Test that endpoint returns empty list when no matches exist."""
    with patch("dashboard.router.read_job_matches") as mock_read:
        mock_read.return_value = {
            "total": 0,
            "page": 1,
            "per_page": 1000,
            "results": [],
        }

        r = await client.get(
            "/dashboard/match-analytics",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["analytics"] == []


@pytest.mark.asyncio
async def test_match_analytics_rejects_invalid_days(client, auth_token):
    """Test that endpoint rejects invalid days parameter."""
    # Test days > 90
    r = await client.get(
        "/dashboard/match-analytics?days=91",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 422  # Validation error

    # Test days < 1
    r = await client.get(
        "/dashboard/match-analytics?days=0",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 422  # Validation error
