"""Refunds must decrement the daily counter row the reservation incremented.

Locks in the two refund fixes: (a) reserve_run_quota(on_date=...) + the
quota_reserved_on stamp keep reservation and refund on the same calendar row
even across midnight / prepare-then-run-later flows; (b) resetting
quota_refunded=False when a job is re-reserved re-arms the refund for retries.
"""

import os
import sys
import uuid
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_quota_date.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest_asyncio
from sqlalchemy import text


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_user(daily_uploads: int = 5):
    from db.models import User, PlanType, PlanLimit
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"qdate-{uuid.uuid4().hex[:8]}@test.com",
            password_hash="x",
            plan=PlanType.free,
        )
        db.add(user)
        existing = await db.get(PlanLimit, "free")
        if not existing:
            db.add(PlanLimit(
                plan="free", daily_uploads=daily_uploads, daily_edits=5,
                max_stored_resumes=1, job_scraping_enabled=False, price_cents=0,
            ))
        await db.commit()
        await db.refresh(user)
        return user


async def _runs_on(user_id, day: date) -> int:
    from db.session import AsyncSessionLocal
    uid_hex = uuid.UUID(str(user_id)).hex
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT runs FROM daily_usage_counters WHERE user_id = :uid AND date = :d"),
            {"uid": uid_hex, "d": day.isoformat()},
        )
        got = row.scalar()
        return int(got) if got is not None else 0


async def _seed_counter(user_id, day: date, runs: int) -> None:
    from db.session import AsyncSessionLocal
    uid_hex = uuid.UUID(str(user_id)).hex
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("INSERT INTO daily_usage_counters (user_id, date, runs, edits) "
                 "VALUES (:uid, :d, :runs, 0)"),
            {"uid": uid_hex, "d": day.isoformat(), "runs": runs},
        )
        await db.commit()


async def _make_job(user_id, reserved_on, refunded: bool):
    from db.models import PipelineJob, JobStatus
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        job = PipelineJob(
            user_id=user_id,
            resume_text="resume body",
            status=JobStatus.error,
            quota_reserved_on=reserved_on,
            quota_refunded=refunded,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id, job.created_at


async def test_reserve_on_date_targets_that_day(db_tables):
    from auth.dependencies import reserve_run_quota
    from db.session import AsyncSessionLocal
    user = await _make_user()
    yesterday = date.today() - timedelta(days=1)
    async with AsyncSessionLocal() as db:
        assert await reserve_run_quota(user, db, on_date=yesterday) is True
    assert await _runs_on(user.id, yesterday) == 1
    assert await _runs_on(user.id, date.today()) == 0


async def test_refund_targets_reserved_on_row(db_tables):
    from main import _refund_job_quota
    from db.session import AsyncSessionLocal
    user = await _make_user()
    yesterday = date.today() - timedelta(days=1)
    await _seed_counter(user.id, yesterday, runs=1)
    job_id, created_at = await _make_job(user.id, reserved_on=yesterday, refunded=False)
    async with AsyncSessionLocal() as db:
        await _refund_job_quota(job_id, user.id, yesterday, created_at, db)
    assert await _runs_on(user.id, yesterday) == 0


async def test_refund_is_idempotent(db_tables):
    from main import _refund_job_quota
    from db.session import AsyncSessionLocal
    user = await _make_user()
    yesterday = date.today() - timedelta(days=1)
    await _seed_counter(user.id, yesterday, runs=1)
    job_id, created_at = await _make_job(user.id, reserved_on=yesterday, refunded=False)
    async with AsyncSessionLocal() as db:
        await _refund_job_quota(job_id, user.id, yesterday, created_at, db)
        await _refund_job_quota(job_id, user.id, yesterday, created_at, db)
    assert await _runs_on(user.id, yesterday) == 0  # not -1: second call no-ops


async def test_reset_flag_rearms_refund_for_retry(db_tables):
    """A job already refunded once (quota_refunded=True) must be refundable again
    after re-reservation resets the flag — the finding-6 retry hole."""
    from main import _refund_job_quota
    from db.models import PipelineJob
    from db.session import AsyncSessionLocal
    from sqlalchemy import update
    user = await _make_user()
    today = date.today()
    await _seed_counter(user.id, today, runs=1)
    job_id, created_at = await _make_job(user.id, reserved_on=None, refunded=True)
    async with AsyncSessionLocal() as db:
        # What run_pipeline now does after every successful reservation:
        await db.execute(
            update(PipelineJob).where(PipelineJob.id == job_id)
            .values(quota_reserved_on=today, quota_refunded=False)
        )
        await db.commit()
        await _refund_job_quota(job_id, user.id, today, created_at, db)
    assert await _runs_on(user.id, today) == 0


async def test_legacy_job_falls_back_to_created_at(db_tables):
    from main import _refund_job_quota
    from db.session import AsyncSessionLocal
    user = await _make_user()
    job_id, created_at = await _make_job(user.id, reserved_on=None, refunded=False)
    # created_at is one day old (see _make_job) — seed that local calendar day.
    from auth.dependencies import _counter_date_for
    legacy_day = date.fromisoformat(_counter_date_for(created_at))
    await _seed_counter(user.id, legacy_day, runs=1)
    async with AsyncSessionLocal() as db:
        await _refund_job_quota(job_id, user.id, None, created_at, db)
    assert await _runs_on(user.id, legacy_day) == 0
