"""Migration 0025 corrects legacy (per-1K-scale) provider_costs rows without
overwriting operator-customized rates or historical (inactive) rows.
"""

import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_costmag.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest
import pytest_asyncio


def _load_migration():
    path = (Path(__file__).parent.parent / "alembic" / "versions"
            / "0025_correct_legacy_provider_cost_magnitudes.py")
    spec = importlib.util.spec_from_file_location("mig0025", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def test_migration_corrections_are_frozen():
    # 0025's _LEGACY_CORRECTIONS fixes historical (per-1K-scale) provider_costs
    # rows using the rates that were current when the migration was authored
    # (2026-07-06). utils.cost.DEFAULT_PROVIDER_RATES is a *live* fallback
    # table that is expected to drift as pricing changes -- e.g. commit
    # f373762 refreshed google/deepseek from LiteLLM's live pricing map.
    # So "migration corrections == live defaults" is not a real invariant;
    # pin against the migration's own frozen literals instead.
    mig = _load_migration()
    expected = {
        "anthropic": (3.0, 15.0),
        "google": (0.10, 0.40),
        "groq": (0.05, 0.08),
    }
    corrections = {
        provider: (new_in, new_out)
        for provider, _oi, _oo, new_in, new_out in mig._LEGACY_CORRECTIONS
    }
    assert corrections == expected


@pytest.mark.asyncio
async def test_corrects_legacy_leaves_operator_and_inactive(db_tables):
    from sqlalchemy import select
    from db.models import ProviderCost
    from db.session import AsyncSessionLocal
    mig = _load_migration()

    async with AsyncSessionLocal() as db:
        # untouched legacy seed -> should be corrected
        db.add(ProviderCost(provider="anthropic", input_cost_per_1m_tokens=0.003,
                            output_cost_per_1m_tokens=0.009, active=True))
        # operator-customized -> must be left alone
        db.add(ProviderCost(provider="google", input_cost_per_1m_tokens=0.99,
                            output_cost_per_1m_tokens=1.99, active=True))
        # historical (inactive) legacy row -> must be left alone (active filter)
        db.add(ProviderCost(provider="groq", input_cost_per_1m_tokens=0.0001,
                            output_cost_per_1m_tokens=0.0001, active=False))
        await db.commit()

    # Apply the migration's UPDATE statements (mirrors upgrade()).
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        for provider, old_in, old_out, new_in, new_out in mig._LEGACY_CORRECTIONS:
            await db.execute(mig._UPDATE, {
                "provider": provider, "old_in": old_in, "old_out": old_out,
                "new_in": new_in, "new_out": new_out, "now": now,
            })
        await db.commit()

    async with AsyncSessionLocal() as db:
        rows = {r.provider + ("" if r.active else "_inactive"): r for r in
                (await db.execute(select(ProviderCost))).scalars().all()}

    assert (rows["anthropic"].input_cost_per_1m_tokens,
            rows["anthropic"].output_cost_per_1m_tokens) == (3.0, 15.0)   # corrected
    assert (rows["google"].input_cost_per_1m_tokens,
            rows["google"].output_cost_per_1m_tokens) == (0.99, 1.99)     # operator untouched
    assert (rows["groq_inactive"].input_cost_per_1m_tokens,
            rows["groq_inactive"].output_cost_per_1m_tokens) == (0.0001, 0.0001)  # inactive untouched
