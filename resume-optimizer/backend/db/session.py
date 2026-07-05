"""
Async SQLAlchemy session factory and database initialization via Alembic.
"""
import asyncio
import datetime
import os
import sys
import traceback
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from db.models import PlanLimit, ProviderCost


def _dbg(msg: str) -> None:
    """Write a timestamped checkpoint to /home/debug_init.log (persistent) and stderr."""
    ts = datetime.datetime.utcnow().isoformat()
    line = f"{ts}: {msg}\n"
    try:
        with open("/home/debug_init.log", "a") as _f:
            _f.write(line)
            _f.flush()
            os.fsync(_f.fileno())
    except Exception:
        pass
    print(line, end="", file=sys.stderr, flush=True)

# SQLite (dev/tests) uses StaticPool/NullPool which reject QueuePool kwargs.
_pool_kwargs = {} if DATABASE_URL.startswith("sqlite") else {
    "pool_size": 3,     # B1 has 1.75GB; keep idle connections low to avoid OOM
    "max_overflow": 7,  # burst up to 10 total when needed
    "pool_timeout": 30,
}

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    **_pool_kwargs,
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

    _dbg("migrations: starting alembic command.upgrade")
    backend_dir = Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")
    _dbg("migrations: complete")


async def init_db() -> None:
    """Run pending migrations then seed plan_limits and provider_costs on first run."""
    _dbg("init_db: start")
    try:
        await asyncio.to_thread(_run_migrations)
    except Exception as exc:
        _dbg(f"init_db: migrations FAILED — {exc}\n{traceback.format_exc()}")
        raise
    _dbg("init_db: migrations done — opening session for seeding")

    try:
        async with AsyncSessionLocal() as session:
            _dbg("init_db: session opened")
            result = await session.execute(text("SELECT COUNT(*) FROM plan_limits"))
            count = result.scalar()
            _dbg(f"init_db: plan_limits count={count}")
            if count == 0:
                _dbg("init_db: inserting plan_limits")
                plans = [
                    PlanLimit(
                        plan="free",
                        daily_uploads=2,
                        daily_edits=5,
                        max_stored_resumes=1,
                        job_scraping_enabled=False,
                        price_cents=0,
                    ),
                    PlanLimit(
                        plan="pro",
                        daily_uploads=20,
                        daily_edits=20,
                        max_stored_resumes=10,
                        job_scraping_enabled=True,
                        price_cents=900,
                    ),
                    PlanLimit(
                        plan="enterprise",
                        daily_uploads=999,
                        daily_edits=999,
                        max_stored_resumes=999,
                        job_scraping_enabled=True,
                        price_cents=2900,
                    ),
                ]
                session.add_all(plans)
                await session.commit()
                _dbg("init_db: plan_limits committed")

            result = await session.execute(text("SELECT COUNT(*) FROM provider_costs WHERE active = true"))
            count = result.scalar()
            _dbg(f"init_db: provider_costs count={count}")
            if count == 0:
                _dbg("init_db: inserting provider_costs")
                # These are ONLY a fallback: resolve_cost() prefers LiteLLM's
                # native per-call cost (response._hidden_params.response_cost, then
                # completion_cost()) and reaches this table only when LiteLLM can't
                # price a call — most notably deepseek/deepseek-v4-pro, whose custom
                # model name LiteLLM may not map, which would otherwise record $0.
                # Values are USD per 1,000,000 tokens (the column name), not per 1K.
                provider_costs = [
                    ProviderCost(
                        provider="anthropic",
                        input_cost_per_1m_tokens=3.0,
                        output_cost_per_1m_tokens=15.0,
                        active=True,
                    ),
                    ProviderCost(
                        provider="google",
                        input_cost_per_1m_tokens=0.10,
                        output_cost_per_1m_tokens=0.40,
                        active=True,
                    ),
                    ProviderCost(
                        provider="groq",
                        input_cost_per_1m_tokens=0.05,
                        output_cost_per_1m_tokens=0.08,
                        active=True,
                    ),
                    ProviderCost(
                        provider="deepseek",
                        input_cost_per_1m_tokens=0.28,
                        output_cost_per_1m_tokens=1.10,
                        active=True,
                    ),
                ]
                session.add_all(provider_costs)
                await session.commit()
                _dbg("init_db: provider_costs committed")
    except Exception as exc:
        _dbg(f"init_db: seeding FAILED — {exc}\n{traceback.format_exc()}")
        raise
    _dbg("init_db: complete")
