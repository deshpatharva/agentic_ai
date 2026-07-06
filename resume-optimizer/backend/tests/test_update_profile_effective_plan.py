"""Regression: PUT /user/me must report the *enforced* plan limits.

login and GET /me were switched to _effective_plan (pro during an active trial),
but update_profile still used user.plan.value, so a trialing user who edited
their name/email saw their limits snap from pro-trial back to free.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_updateprofile.db")
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


@pytest.mark.asyncio
async def test_update_profile_reports_trial_pro_limits(db_tables):
    from auth.router import update_profile, UpdateProfileRequest
    from db.models import PlanLimit, PlanType, User
    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        db.add(PlanLimit(plan="free", daily_uploads=3, daily_edits=5,
                         max_stored_resumes=1, job_scraping_enabled=False, price_cents=0))
        db.add(PlanLimit(plan="pro", daily_uploads=20, daily_edits=100,
                         max_stored_resumes=10, job_scraping_enabled=True, price_cents=900))
        user = User(
            id=uuid.uuid4(), email="trial@test.com", password_hash="x",
            full_name="Trial User", plan=PlanType.free,
            trial_expires_at=datetime.now(timezone.utc) + timedelta(days=5),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        req = UpdateProfileRequest(full_name="Trial User Edited", email="trial@test.com")
        result = await update_profile(req, user, db)

    # Trialing free user is effectively pro -> pro's 20/day, not free's 3.
    assert result["limits"]["daily_uploads"] == 20, result["limits"]
