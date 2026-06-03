"""Tests for _reap_once reaper helper and GET /health endpoint."""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_health.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base, JobStatus, PipelineJob
from db.session import get_db
from main import app, _reap_once

TEST_DB_URL = "sqlite+aiosqlite:///./test_health.db"
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
        os.remove("./test_health.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Reaper tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reap_once_marks_stuck_job_as_error():
    """A job stuck in running for > timeout minutes is transitioned to error."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.running,
            updated_at=old_time,
            created_at=old_time,
        ))
        await db.commit()

    async with _TestSession() as db:
        reaped = await _reap_once(db)

    assert str(job_id) in reaped

    async with _TestSession() as db:
        result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_id))
        job = result.scalar_one()
        assert job.status == JobStatus.error
        assert "timed out" in job.error_message


@pytest.mark.asyncio
async def test_reap_once_ignores_recent_running_job():
    """A job that started recently is NOT reaped."""
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.running,
            updated_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    async with _TestSession() as db:
        reaped = await _reap_once(db)

    assert str(job_id) not in reaped

    async with _TestSession() as db:
        result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_id))
        job = result.scalar_one()
        assert job.status == JobStatus.running


@pytest.mark.asyncio
async def test_reap_once_ignores_done_job():
    """A done job is never touched, even if updated_at is old."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=3)
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.done,
            updated_at=old_time,
            created_at=old_time,
        ))
        await db.commit()

    async with _TestSession() as db:
        reaped = await _reap_once(db)

    assert str(job_id) not in reaped

    async with _TestSession() as db:
        result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_id))
        job = result.scalar_one()
        assert job.status == JobStatus.done


# ── Health endpoint tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_200_with_expected_shape(client):
    """GET /health returns 200 with db/storage/job count fields."""
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["db"] == "ok"
    assert data["storage"] == "skipped"   # AZURE_STORAGE_ACCOUNT_NAME not set in tests
    assert "stuck_jobs" in data
    assert "pending_jobs" in data
    assert data["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_health_counts_stuck_jobs(client):
    """stuck_jobs count reflects running jobs older than the timeout."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.running,
            updated_at=old_time,
            created_at=old_time,
        ))
        await db.commit()

    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["stuck_jobs"] >= 1


@pytest.mark.asyncio
async def test_health_counts_pending_jobs(client):
    """pending_jobs count reflects jobs with status=pending."""
    job_id = uuid.uuid4()
    async with _TestSession() as db:
        db.add(PipelineJob(
            id=job_id,
            resume_text="r",
            original_filename="test.pdf",
            status=JobStatus.pending,
            updated_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["pending_jobs"] >= 1
