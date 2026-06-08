"""
Async SQLAlchemy session factory and database initialization via Alembic.
"""
import asyncio
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from db.models import PlanLimit, ProviderCost

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=3,       # B1 has 1.75GB; keep idle connections low to avoid OOM
    max_overflow=7,    # burst up to 10 total when needed
    pool_timeout=30,
)
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


def _run_migrations() -> None:
    """
    Run pending Alembic migrations synchronously.
    Called via asyncio.to_thread from init_db() so it does not block the event loop.
    Any exception propagates and prevents the app from starting.
    """
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """Run pending migrations then seed plan_limits and provider_costs on first run."""
    await asyncio.to_thread(_run_migrations)

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM plan_limits"))
        count = result.scalar()
        if count == 0:
            plans = [
                PlanLimit(
                    plan="free",
                    daily_uploads=2,
                    max_stored_resumes=1,
                    job_scraping_enabled=False,
                    price_cents=0,
                ),
                PlanLimit(
                    plan="pro",
                    daily_uploads=20,
                    max_stored_resumes=10,
                    job_scraping_enabled=True,
                    price_cents=900,
                ),
                PlanLimit(
                    plan="enterprise",
                    daily_uploads=999,
                    max_stored_resumes=999,
                    job_scraping_enabled=True,
                    price_cents=2900,
                ),
            ]
            session.add_all(plans)
            await session.commit()

        result = await session.execute(text("SELECT COUNT(*) FROM provider_costs WHERE active = true"))
        count = result.scalar()
        if count == 0:
            provider_costs = [
                ProviderCost(
                    provider="anthropic",
                    input_cost_per_1m_tokens=0.003,
                    output_cost_per_1m_tokens=0.009,
                    active=True,
                ),
                ProviderCost(
                    provider="google",
                    input_cost_per_1m_tokens=0.0005,
                    output_cost_per_1m_tokens=0.0015,
                    active=True,
                ),
                ProviderCost(
                    provider="groq",
                    input_cost_per_1m_tokens=0.0001,
                    output_cost_per_1m_tokens=0.0001,
                    active=True,
                ),
            ]
            session.add_all(provider_costs)
            await session.commit()
