"""
Tests for atomic run-quota reservation (reserve_run_quota / refund_run_quota).

These lock in the fix for the concurrency race where many parallel pipeline
submissions each passed a read-only limit check at used<limit and every one
burned real LLM spend. Reservation is atomic and up-front; failed runs refund.

Uses SQLite via db.session.engine. pytest-asyncio runs in auto mode (pytest.ini).
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_quota.db")
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


async def _make_user(daily_uploads: int = 2):
    from db.models import User, PlanType, PlanLimit
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"quota-{uuid.uuid4().hex[:8]}@test.com",
            password_hash="x",
            plan=PlanType.free,
        )
        db.add(user)
        # Seed the free plan limit if not already present.
        existing = await db.get(PlanLimit, "free")
        if not existing:
            db.add(PlanLimit(
                plan="free", daily_uploads=daily_uploads, daily_edits=5,
                max_stored_resumes=1, job_scraping_enabled=False, price_cents=0,
            ))
        await db.commit()
        await db.refresh(user)
        return user


async def _runs(user_id) -> int:
    from db.models import DailyUsageCounter
    from db.session import AsyncSessionLocal
    from datetime import date
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(DailyUsageCounter.runs).where(
                DailyUsageCounter.user_id == user_id,
                DailyUsageCounter.date == date.today().isoformat(),
            )
        ) or 0


@pytest.mark.asyncio
async def test_reserve_enforces_limit_and_refund_restores(db_tables):
    from auth.dependencies import reserve_run_quota, refund_run_quota
    from db.session import AsyncSessionLocal

    user = await _make_user(daily_uploads=2)

    results = []
    for _ in range(4):
        async with AsyncSessionLocal() as db:
            results.append(await reserve_run_quota(user, db))

    assert results == [True, True, False, False], results
    assert await _runs(user.id) == 2  # never exceeds the limit

    # A failed run refunds its slot, freeing capacity again.
    async with AsyncSessionLocal() as db:
        await refund_run_quota(user.id, db)
    assert await _runs(user.id) == 1
    async with AsyncSessionLocal() as db:
        assert await reserve_run_quota(user, db) is True
    assert await _runs(user.id) == 2


@pytest.mark.asyncio
async def test_concurrent_reserves_do_not_exceed_limit(db_tables):
    """The whole point of the fix: parallel submissions can't all slip through."""
    from auth.dependencies import reserve_run_quota
    from db.session import AsyncSessionLocal

    user = await _make_user(daily_uploads=3)

    async def _one():
        async with AsyncSessionLocal() as db:
            return await reserve_run_quota(user, db)

    results = await asyncio.gather(*[_one() for _ in range(10)])
    assert sum(1 for r in results if r) == 3, results
    assert await _runs(user.id) == 3


@pytest.mark.asyncio
async def test_refund_floors_at_zero(db_tables):
    from auth.dependencies import refund_run_quota
    from db.session import AsyncSessionLocal

    user = await _make_user()
    # Refund with no prior reservation must not drive the counter negative.
    async with AsyncSessionLocal() as db:
        await refund_run_quota(user.id, db)
    assert await _runs(user.id) == 0
