"""A failed or vanished pipeline run must un-brick the chat session at read time
(deep-review finding 3): clear _optimizer_launched, offer a retry, and only claim
'still running' when the job row says so."""

import os
import sys
import types
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-for-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_chat_recovery.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest_asyncio

PROFILES = [{"id": "", "label": "Data Engineer"}]  # id filled per-test


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_job(status_name: str, profile_id=None):
    from db.models import PipelineJob, JobStatus
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        job = PipelineJob(
            user_id=None,
            profile_id=profile_id,
            resume_text="resume body",
            status=getattr(JobStatus, status_name),
            error_message="boom" if status_name == "error" else None,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def test_running_job_returns_none(db_tables):
    from chat.router import _check_optimizer_job
    from db.session import AsyncSessionLocal
    job_id = await _make_job("running")
    ctx = {"_optimizer_launched": True, "jd_text": "some jd"}
    async with AsyncSessionLocal() as db:
        out = await _check_optimizer_job(types.SimpleNamespace(job_id=job_id), ctx, PROFILES, db)
    assert out is None
    assert ctx.get("_optimizer_launched") is True  # untouched


async def test_error_job_recovers_and_offers_retry(db_tables):
    from chat.router import _check_optimizer_job
    from db.session import AsyncSessionLocal
    prof_id = uuid.uuid4()
    profiles = [{"id": str(prof_id), "label": "Data Engineer"}]
    job_id = await _make_job("error", profile_id=prof_id)
    ctx = {"_optimizer_launched": True, "jd_text": "some jd"}
    async with AsyncSessionLocal() as db:
        out = await _check_optimizer_job(types.SimpleNamespace(job_id=job_id), ctx, profiles, db)
    assert out["action"] == "respond"
    assert "failed" in out["response"]
    assert "_optimizer_launched" not in ctx
    assert ctx["_pending_confirm"] == {"action": "launch", "profile_id": str(prof_id)}
    assert ctx["last_error"] == "boom"


async def test_missing_job_recovers(db_tables):
    from chat.router import _check_optimizer_job
    from db.session import AsyncSessionLocal
    ctx = {"_optimizer_launched": True, "jd_text": "some jd"}
    async with AsyncSessionLocal() as db:
        out = await _check_optimizer_job(types.SimpleNamespace(job_id=None), ctx, [], db)
    assert out["action"] == "respond"
    assert "_optimizer_launched" not in ctx


async def test_done_job_points_to_dashboard(db_tables):
    from chat.router import _check_optimizer_job
    from db.session import AsyncSessionLocal
    job_id = await _make_job("done")
    ctx = {"_optimizer_launched": True, "jd_text": "some jd"}
    async with AsyncSessionLocal() as db:
        out = await _check_optimizer_job(types.SimpleNamespace(job_id=job_id), ctx, [], db)
    assert out["action"] == "respond"
    assert "dashboard" in out["response"].lower()
    assert "_optimizer_launched" not in ctx
    assert "_pending_confirm" not in ctx
