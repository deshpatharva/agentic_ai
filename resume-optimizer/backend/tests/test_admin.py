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
