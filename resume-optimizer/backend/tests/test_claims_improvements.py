"""Tests for ClaimsLedger extension and fabrication guard improvements."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


def test_claims_ledger_has_new_fields():
    """ClaimsLedger must have job_titles, degrees, and date_ranges fields."""
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(["Acme Corp"]),
        metrics=frozenset(["50%"]),
        raw_bullets=("Built the thing",),
        job_titles=frozenset(["Senior Engineer"]),
        degrees=frozenset(["BS Computer Science"]),
        date_ranges=frozenset(["2018-2022"]),
    )
    assert ledger.job_titles == frozenset(["Senior Engineer"])
    assert ledger.degrees == frozenset(["BS Computer Science"])
    assert ledger.date_ranges == frozenset(["2018-2022"])


def test_claims_ledger_backward_compat():
    """ClaimsLedger must construct without new fields (backward compat via defaults)."""
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(["Acme"]),
        metrics=frozenset(["40%"]),
        raw_bullets=("Did stuff",),
    )
    assert hasattr(ledger, "job_titles")
    assert hasattr(ledger, "degrees")
    assert hasattr(ledger, "date_ranges")
    assert ledger.job_titles == frozenset()
    assert ledger.degrees == frozenset()
    assert ledger.date_ranges == frozenset()


def test_fabrication_guard_tolerance_is_ten_percent():
    """Metric tolerance in fabrication_guard must be 0.10, not 0.02."""
    import inspect
    from agents import fabrication_guard as fg_module
    source = inspect.getsource(fg_module)
    assert "0.02" not in source, \
        "Metric tolerance is still 0.02 — raise to 0.10"
    assert "0.10" in source or "0.1 " in source or "0.1)" in source, \
        "Metric tolerance 0.10 not found in fabrication_guard"


def test_fabrication_guard_never_emits_verify_marker():
    """Guard must never tag uncertain lines with [VERIFY]; it substitutes the
    closest original bullet or drops the line entirely (spec 4b)."""
    import inspect
    from agents import fabrication_guard as fg_module
    source = inspect.getsource(fg_module)
    assert "[VERIFY]" not in source, \
        "Guard must not tag lines with [VERIFY] -- substitute or drop instead"
    assert "_closest_original" in source, \
        "Guard must substitute fabricated lines via the closest-original-bullet path"
