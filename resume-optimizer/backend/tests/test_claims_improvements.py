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


def test_fabrication_guard_uses_verify_not_silent_substitution():
    """Guard must add [VERIFY] to uncertain lines, not silently substitute them."""
    import inspect
    from agents import fabrication_guard as fg_module
    source = inspect.getsource(fg_module)
    assert "[VERIFY]" in source, \
        "Guard must tag uncertain lines with [VERIFY] instead of silently substituting"


# T6.1 — metric percentage tightened to ≤2% + same-bullet scope
def test_metric_percentage_tightened_to_2pct():
    """5% difference on a percentage metric must be flagged (was allowed at 10%)."""
    from agents.fabrication_guard import fabrication_guard
    from agents.fact_extractor import ClaimsLedger
    # Source has 30% — generated has 32% (6.7% diff, was OK at 10%, must fail at 2%)
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(["30%"]),
        raw_bullets=("reduced costs by 30%",), job_titles=frozenset(),
        degrees=frozenset(), date_ranges=frozenset()
    )
    result = fabrication_guard("reduced costs by 32%", ledger, "reduced costs by 30%")
    assert result.gaps, "32% should be flagged when source only has 30% (>2% diff)"

def test_metric_non_percentage_keeps_10pct_tolerance():
    """Non-percentage metrics (dollar, magnitude) keep ±10% tolerance."""
    from agents.fabrication_guard import fabrication_guard
    from agents.fact_extractor import ClaimsLedger
    # Source has $100K — generated has $105K (5% diff, should be OK for non-%)
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(["$100K"]),
        raw_bullets=("managed $100K budget",), job_titles=frozenset(),
        degrees=frozenset(), date_ranges=frozenset()
    )
    result = fabrication_guard("managed $105K budget", ledger, "managed $100K budget")
    assert not result.gaps, "$105K should NOT be flagged when source has $100K (5% within 10%)"

# T6.2 — alias-aware company matching
def test_company_alias_msft_matches_microsoft():
    """MSFT in generated text should be attested if Microsoft is in the ledger."""
    from agents.fabrication_guard import _company_attested
    assert _company_attested("MSFT", frozenset({"Microsoft"})), \
        "MSFT should be recognized as Microsoft"

def test_company_alias_aws_matches_amazon():
    """AWS in generated text should be attested if Amazon Web Services is in ledger."""
    from agents.fabrication_guard import _company_attested
    assert _company_attested("AWS", frozenset({"Amazon Web Services"})), \
        "AWS should be recognized as Amazon Web Services"

def test_unknown_company_still_flagged():
    """A genuinely made-up company should still be flagged."""
    from agents.fabrication_guard import _company_attested
    assert not _company_attested("FakeCorp", frozenset({"Microsoft", "Google"})), \
        "FakeCorp should NOT be attested"

# T6.3 — title/degree/date attestation
def test_fabricated_title_is_flagged():
    """A job title not in the ledger must be flagged."""
    from agents.fabrication_guard import fabrication_guard
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(), raw_bullets=("Software Engineer at Acme",),
        job_titles=frozenset({"Software Engineer"}),
        degrees=frozenset(), date_ranges=frozenset()
    )
    # Generated promotes to "Senior Software Engineer" — not in ledger
    result = fabrication_guard("Senior Software Engineer at Acme", ledger, "Software Engineer at Acme")
    assert result.gaps, "Promoted title 'Senior Software Engineer' must be flagged"

def test_fabricated_degree_is_flagged():
    """A degree not in the ledger must be flagged."""
    from agents.fabrication_guard import fabrication_guard
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(), raw_bullets=("B.S. Computer Science",),
        job_titles=frozenset(), degrees=frozenset({"B.S. Computer Science"}),
        date_ranges=frozenset()
    )
    # Generated adds PhD — not in ledger
    result = fabrication_guard("PhD in Computer Science, MIT", ledger, "B.S. Computer Science")
    assert result.gaps, "PhD must be flagged since ledger only has B.S."

def test_fabricated_date_range_is_flagged():
    """A date range not in the ledger must be flagged."""
    from agents.fabrication_guard import fabrication_guard
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(), raw_bullets=("2020-2022 at Acme",),
        job_titles=frozenset(), degrees=frozenset(),
        date_ranges=frozenset({"2020-2022"})
    )
    # Generated claims 2019-2022 — extended start date not in ledger
    result = fabrication_guard("2019-2022 at Acme", ledger, "2020-2022 at Acme")
    assert result.gaps, "Date range 2019-2022 must be flagged since ledger only has 2020-2022"

# T6.4 — JD-relative persona domain check
def test_persona_terms_allowed_when_present_in_jd():
    """Persona terms that match the JD domain should NOT be flagged."""
    from agents.fabrication_guard import fabrication_guard
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(),
        raw_bullets=("managed sales pipeline for B2B SaaS",),
        job_titles=frozenset(), degrees=frozenset(), date_ranges=frozenset()
    )
    # JD is for a sales role — "sales pipeline" should be allowed
    result = fabrication_guard(
        "managed sales pipeline for B2B SaaS",
        ledger,
        "managed sales pipeline for B2B SaaS",
        jd_text="seeking account executive to manage sales pipeline"
    )
    assert not result.gaps, "sales pipeline should NOT be flagged when JD domain is sales"

def test_persona_terms_flagged_when_not_in_jd_or_source():
    """Persona terms foreign to both source AND JD must still be flagged."""
    from agents.fabrication_guard import fabrication_guard
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(),
        raw_bullets=("built machine learning pipelines",),
        job_titles=frozenset(), degrees=frozenset(), date_ranges=frozenset()
    )
    result = fabrication_guard(
        "managed talent acquisition and recruiting pipeline",
        ledger,
        "built machine learning pipelines",
        jd_text="seeking senior machine learning engineer"
    )
    assert result.gaps, "talent acquisition/recruiting must be flagged for an ML engineer JD"
