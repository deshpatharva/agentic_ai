"""Unit tests for deterministic agents: extract_claims and fabrication_guard.

No LLM calls, no DB, no async — both agents are pure Python + spaCy.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.fact_extractor import ClaimsLedger, extract_claims
from agents.fabrication_guard import fabrication_guard


# ── extract_claims ────────────────────────────────────────────────────────────

def test_extract_claims_finds_metrics():
    """Percent, dollar-magnitude, and multiplier metrics are captured."""
    text = "Increased revenue by 30% and saved $1.2M over two years via 3x improvement."
    ledger = extract_claims(text)
    assert "30%" in ledger.metrics
    assert "$1.2M" in ledger.metrics
    assert "3x" in ledger.metrics


def test_extract_claims_ignores_plain_integers():
    """Bare integers with no unit (%, $, K/M/B, x) are not captured as metrics."""
    text = "Managed 5 engineers across 2 teams with consistently strong results."
    ledger = extract_claims(text)
    assert ledger.metrics == frozenset()


def test_extract_claims_extracts_bullets():
    """Bullet lines (• or -) longer than 15 chars are included in raw_bullets."""
    text = (
        "• Led a team of engineers to deliver a new product feature on time\n"
        "- Managed stakeholder relationships across multiple departments\n"
    )
    ledger = extract_claims(text)
    assert any("Led a team of engineers" in b for b in ledger.raw_bullets)
    assert any("Managed stakeholder relationships" in b for b in ledger.raw_bullets)


def test_extract_claims_excludes_short_lines():
    """Lines of 15 chars or fewer after stripping bullet prefix are excluded."""
    text = (
        "• Short line\n"
        "• This line is long enough to be included in the raw bullets output\n"
    )
    ledger = extract_claims(text)
    assert not any("Short line" in b for b in ledger.raw_bullets)
    assert any("This line is long enough" in b for b in ledger.raw_bullets)


def test_extract_claims_excludes_header_lines():
    """Lines ending with ':' (section headers) are excluded from raw_bullets."""
    text = (
        "Work Experience:\n"
        "• Led engineering teams to deliver high-impact product features on schedule\n"
    )
    ledger = extract_claims(text)
    assert not any("Work Experience" in b for b in ledger.raw_bullets)
    assert any("Led engineering teams" in b for b in ledger.raw_bullets)


def test_extract_claims_empty_input():
    """Empty string produces an entirely empty ClaimsLedger."""
    ledger = extract_claims("")
    assert ledger.companies == frozenset()
    assert ledger.metrics == frozenset()
    assert ledger.raw_bullets == ()


def test_extract_claims_returns_correct_types():
    """ClaimsLedger fields have the documented types."""
    ledger = extract_claims("Software engineer with 30% efficiency improvement.")
    assert isinstance(ledger.companies, frozenset)
    assert isinstance(ledger.metrics, frozenset)
    assert isinstance(ledger.raw_bullets, tuple)


def test_extract_claims_prompt_block():
    """prompt_block() summarises metrics; falls back when ledger is empty."""
    text = "Achieved 30% reduction in operational costs for the engineering team."
    ledger = extract_claims(text)
    block = ledger.prompt_block()
    assert block.startswith("CLAIMS LEDGER")
    assert "30%" in block

    empty_ledger = extract_claims("")
    assert "no explicit metrics" in empty_ledger.prompt_block()


# ── fabrication_guard ─────────────────────────────────────────────────────────

def test_guard_clean_text_passes_through():
    """Text whose metrics are all attested in the source is returned unchanged."""
    source = "Improved system performance by 30%."
    ledger = ClaimsLedger(
        companies=frozenset(),
        metrics=frozenset({"30%"}),
        raw_bullets=("Improved system performance by 30% in production environment",),
    )
    result = fabrication_guard("Improved performance by 30%.", ledger, source)
    assert result.stripped == []
    assert "30%" in result.text


def test_guard_strips_fabricated_metric():
    """A metric absent from the source is added to stripped."""
    source = "Achieved 30% efficiency gain in legacy systems."
    ledger = ClaimsLedger(
        companies=frozenset(),
        metrics=frozenset({"30%"}),
        raw_bullets=tuple(),
    )
    result = fabrication_guard(
        "Achieved 99% efficiency gain across all systems.", ledger, source
    )
    assert "99%" in result.stripped


def test_guard_allows_metric_within_tolerance():
    """30.5% vs 30% is a 1.67% delta — within the ±2% tolerance, so not stripped."""
    source = "Increased efficiency by 30%."
    ledger = ClaimsLedger(
        companies=frozenset(),
        metrics=frozenset({"30%"}),
        raw_bullets=tuple(),
    )
    result = fabrication_guard("Increased efficiency by 30.5%.", ledger, source)
    assert result.stripped == []


def test_guard_strips_metric_outside_tolerance():
    """60% vs 30% is a 100% delta — outside tolerance, stripped."""
    source = "Achieved 30% improvement in system efficiency."
    ledger = ClaimsLedger(
        companies=frozenset(),
        metrics=frozenset({"30%"}),
        raw_bullets=tuple(),
    )
    result = fabrication_guard(
        "Achieved 60% improvement in system efficiency.", ledger, source
    )
    assert "60%" in result.stripped


def test_guard_substitutes_with_closest_original():
    """When a line is stripped and a close original exists, it substitutes."""
    source = "Led team of engineers to reduce operational costs by 30%."
    original_bullet = "Led team of engineers to reduce operational costs by 30%"
    ledger = ClaimsLedger(
        companies=frozenset(),
        metrics=frozenset({"30%"}),
        raw_bullets=(original_bullet,),
    )
    result = fabrication_guard(
        "Led team of engineers to reduce operational costs by 99%.",
        ledger,
        source,
    )
    assert "99%" in result.stripped
    assert original_bullet in result.text


def test_guard_adds_to_gaps_when_no_match():
    """When no original bullet is close enough, the line goes to gaps."""
    source = "Built API in Python."
    ledger = ClaimsLedger(
        companies=frozenset(),
        metrics=frozenset(),
        raw_bullets=tuple(),
    )
    result = fabrication_guard(
        "Reduced server costs by 75% through infrastructure optimization.",
        ledger,
        source,
    )
    assert "75%" in result.stripped
    assert len(result.gaps) > 0


def test_guard_non_metric_lines_preserved():
    """Lines with no metrics and no ORG entities pass through verbatim."""
    source = "Senior software engineer with strong Python skills."
    ledger = ClaimsLedger(
        companies=frozenset(),
        metrics=frozenset(),
        raw_bullets=tuple(),
    )
    clean_line = "Strong communication and leadership skills."
    result = fabrication_guard(clean_line, ledger, source)
    assert clean_line in result.text
    assert result.stripped == []


def test_guard_stripped_list_is_deduplicated():
    """The same fabricated metric on two lines appears only once in stripped."""
    source = "Achieved 30% efficiency gain overall."
    ledger = ClaimsLedger(
        companies=frozenset(),
        metrics=frozenset({"30%"}),
        raw_bullets=tuple(),
    )
    generated = (
        "Achieved 99% efficiency in frontend systems.\n"
        "Achieved 99% efficiency in backend systems."
    )
    result = fabrication_guard(generated, ledger, source)
    assert result.stripped.count("99%") == 1
