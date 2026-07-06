"""Quota-cluster fixes:
  #7 refund targets the run's reservation date (not today at refund time)
  #9 edit quota reserved atomically up-front (mirrors runs), refunded on failure
  #6 per-job refund is idempotent across the failing task and the reaper
  #4 job -> running transition is an atomic claim (one concurrent submission wins)
"""

import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_quota_cluster.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_user(daily_uploads=2, daily_edits=2):
    from db.models import PlanLimit, PlanType, User
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        user = User(id=uuid.uuid4(), email=f"q-{uuid.uuid4().hex[:8]}@t.com",
                    password_hash="x", plan=PlanType.free)
        db.add(user)
        if not await db.get(PlanLimit, "free"):
            db.add(PlanLimit(plan="free", daily_uploads=daily_uploads, daily_edits=daily_edits,
                             max_stored_resumes=1, job_scraping_enabled=False, price_cents=0))
        await db.commit()
        await db.refresh(user)
        return user


async def _runs_on(user_id, date_str) -> int:
    from sqlalchemy import select
    from db.models import DailyUsageCounter
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(DailyUsageCounter.runs).where(
            DailyUsageCounter.user_id == user_id, DailyUsageCounter.date == date_str)) or 0


async def _edits_today(user_id) -> int:
    from sqlalchemy import select
    from db.models import DailyUsageCounter
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(DailyUsageCounter.edits).where(
            DailyUsageCounter.user_id == user_id,
            DailyUsageCounter.date == date.today().isoformat())) or 0


# ── #7 refund honours the reservation date ────────────────────────────────────
@pytest.mark.asyncio
async def test_refund_targets_given_date_not_today(db_tables):
    from auth.dependencies import refund_run_quota, reserve_run_quota
    from db.session import AsyncSessionLocal
    today = date.today().isoformat()
    user = await _make_user(daily_uploads=3)
    async with AsyncSessionLocal() as db:
        assert await reserve_run_quota(user, db)
    assert await _runs_on(user.id, today) == 1

    # Refund attributed to a DIFFERENT day must not touch today's counter.
    other = (date.today() - timedelta(days=1)).isoformat()
    async with AsyncSessionLocal() as db:
        await refund_run_quota(user.id, db, run_date=other)
    assert await _runs_on(user.id, today) == 1

    # Refund for today's reservation returns the slot.
    async with AsyncSessionLocal() as db:
        await refund_run_quota(user.id, db, run_date=today)
    assert await _runs_on(user.id, today) == 0


# ── #9 edit quota reserved up-front, refunded on failure ──────────────────────
@pytest.mark.asyncio
async def test_reserve_edit_enforces_limit_and_refund_restores(db_tables):
    from auth.dependencies import refund_edit_quota, reserve_edit_quota
    from db.session import AsyncSessionLocal
    user = await _make_user(daily_edits=2)

    results = []
    for _ in range(4):
        async with AsyncSessionLocal() as db:
            results.append(await reserve_edit_quota(user, db))
    assert results == [True, True, False, False], results
    assert await _edits_today(user.id) == 2

    async with AsyncSessionLocal() as db:
        await refund_edit_quota(user.id, db)
    assert await _edits_today(user.id) == 1
    async with AsyncSessionLocal() as db:
        assert await reserve_edit_quota(user, db) is True


async def _make_job(user_id, status):
    from db.models import PipelineJob
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        job = PipelineJob(user_id=user_id, status=status,
                          original_filename="r", resume_text="x", jd_text="y")
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id, job.user_id, job.created_at


# ── #6 per-job refund is idempotent (task + reaper can't both refund) ──────────
@pytest.mark.asyncio
async def test_job_refund_is_idempotent(db_tables):
    from auth.dependencies import reserve_run_quota
    from db.models import JobStatus
    from db.session import AsyncSessionLocal
    from main import _refund_job_quota
    today = date.today().isoformat()
    user = await _make_user(daily_uploads=3)
    async with AsyncSessionLocal() as db:
        assert await reserve_run_quota(user, db)
    jid, uid, created = await _make_job(user.id, JobStatus.running)
    assert await _runs_on(user.id, today) == 1

    async with AsyncSessionLocal() as db:
        await _refund_job_quota(jid, uid, None, created, db)
    async with AsyncSessionLocal() as db:
        await _refund_job_quota(jid, uid, None, created, db)   # reaper's turn — must no-op
    assert await _runs_on(user.id, today) == 0


# ── #4 job -> running is an atomic claim ──────────────────────────────────────
@pytest.mark.asyncio
async def test_claim_job_for_run_is_exclusive(db_tables):
    from db.models import JobStatus
    from db.session import AsyncSessionLocal
    from main import _claim_job_for_run
    user = await _make_user()
    jid, _, _ = await _make_job(user.id, JobStatus.pending)

    async with AsyncSessionLocal() as db:
        assert await _claim_job_for_run(jid, "jd", None, None, db) is True
    async with AsyncSessionLocal() as db:
        assert await _claim_job_for_run(jid, "jd", None, None, db) is False  # already running


@pytest.mark.asyncio
async def test_claim_allows_error_retry_rejects_done(db_tables):
    from db.models import JobStatus
    from db.session import AsyncSessionLocal
    from main import _claim_job_for_run
    user = await _make_user()

    jid_err, _, _ = await _make_job(user.id, JobStatus.error)
    async with AsyncSessionLocal() as db:
        assert await _claim_job_for_run(jid_err, "jd", None, None, db) is True   # retry allowed

    jid_done, _, _ = await _make_job(user.id, JobStatus.done)
    async with AsyncSessionLocal() as db:
        assert await _claim_job_for_run(jid_done, "jd", None, None, db) is False  # done rejected
