"""Tests for per-user long-term fact memory (T3.2)."""
import os, sys, json, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_memory.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("BOOTSTRAP_SECRET", "test")
os.environ.setdefault("DELTA_STORAGE_PATH", "./test_delta_store")

from agents.fact_extractor import ClaimsLedger
from agents.memory import merge_ledgers, _ledger_to_dict, _dict_to_ledger


def test_merge_ledgers_unions_facts():
    a = ClaimsLedger(companies=frozenset(["Acme"]), metrics=frozenset(["30%"]),
                     raw_bullets=tuple(["Led team"]))
    b = ClaimsLedger(companies=frozenset(["BigCo"]), metrics=frozenset(["50K"]),
                     raw_bullets=tuple(["Built platform"]))
    merged = merge_ledgers(a, b)
    assert "Acme" in merged.companies and "BigCo" in merged.companies
    assert "30%" in merged.metrics and "50K" in merged.metrics
    assert "Led team" in merged.raw_bullets and "Built platform" in merged.raw_bullets


def test_ledger_roundtrip():
    ledger = ClaimsLedger(
        companies=frozenset(["Google"]), metrics=frozenset(["99.9%"]),
        raw_bullets=tuple(["Reduced latency by 30%"]),
        job_titles=frozenset(["Senior Engineer"]),
        degrees=frozenset(["B.Sc. Computer Science"]),
        date_ranges=frozenset(["2020-2023"]),
    )
    d = _ledger_to_dict(ledger)
    restored = _dict_to_ledger(d)
    assert restored.companies == ledger.companies
    assert restored.metrics == ledger.metrics
    assert set(restored.raw_bullets) == set(ledger.raw_bullets)
    assert restored.job_titles == ledger.job_titles
    assert restored.degrees == ledger.degrees
    assert restored.date_ranges == ledger.date_ranges


def test_merge_ledgers_deduplicates():
    a = ClaimsLedger(companies=frozenset(["Google"]), metrics=frozenset(["30%"]),
                     raw_bullets=tuple(["Same bullet"]))
    b = ClaimsLedger(companies=frozenset(["Google"]), metrics=frozenset(["30%"]),
                     raw_bullets=tuple(["Same bullet"]))
    merged = merge_ledgers(a, b)
    assert len(merged.companies) == 1
    assert len(merged.metrics) == 1


@pytest.mark.asyncio
async def test_load_claims_ledger_returns_none_for_missing_profile():
    """load_claims_ledger returns None when profile not found."""
    import uuid
    from agents.memory import load_claims_ledger
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///./test_memory.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        result = await load_claims_ledger(db, uuid.uuid4())
    assert result is None
    await engine.dispose()
