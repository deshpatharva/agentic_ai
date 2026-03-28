"""
Async SQLAlchemy session factory and database initialization.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from config import DATABASE_URL
from db.models import Base, PlanLimit


engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables and seed plan_limits on first run."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # Seed plan_limits only if empty
        result = await session.execute(text("SELECT COUNT(*) FROM plan_limits"))
        count = result.scalar()
        if count == 0:
            plans = [
                PlanLimit(plan="free",       daily_uploads=2,   max_stored_resumes=1,   job_scraping_enabled=False, price_cents=0),
                PlanLimit(plan="pro",        daily_uploads=20,  max_stored_resumes=10,  job_scraping_enabled=True,  price_cents=900),
                PlanLimit(plan="enterprise", daily_uploads=999, max_stored_resumes=999, job_scraping_enabled=True,  price_cents=2900),
            ]
            session.add_all(plans)
            await session.commit()
