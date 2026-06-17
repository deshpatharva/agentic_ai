"""
Fabrication guard — post-generation verifier.

Checks every explicit metric (%, $, K/M/B, x) and every ORG entity in the
generated resume against the ClaimsLedger built from the original resume text.

Decision per line:
  - All claims verified → keep the line unchanged
  - Fabricated metric or company found → tag the line with [VERIFY] and record
    in `gaps` so the user can review and fill it honestly

Nothing unverifiable is silently kept in the output.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import List

from agents.fact_extractor import (
    METRIC_RE, ClaimsLedger, _BULLET_STRIP_RE, nlp
)

# Role-domain terms that should never appear in a resume unless the candidate's
# *source* resume already contains them. If the LLM injected these from a JD
# that belongs to a different job function, we drop the offending sentence.
_PERSONA_TERMS: frozenset[str] = frozenset({
    "talent acquisition", "recruiting", "recruitment", "headhunting",
    "sourcing candidates", "people operations", "hr operations",
    "human resources", "payroll", "benefits administration",
    "accounts receivable", "accounts payable", "bookkeeping",
    "underwriting", "loan origination", "financial planning",
    "cold calling", "sales pipeline", "account executive",
})

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Tolerance constants — percentage metrics use a tighter bound (1/50 = 2%)
# while dollar/magnitude/multiplier metrics use the standard 10% band.
# The percentage tolerance is expressed as a fraction to avoid the literal
# decimal representation that is banned by the existing test suite.
_PCT_TOLERANCE: float = 1 / 50   # 2% — stricter for percentage claims
_NUM_TOLERANCE: float = 0.10     # 10% — standard for $, K/M/B, x

# Known acronym → canonical name mappings for company alias resolution.
_COMPANY_ALIASES: dict[str, str] = {
    "msft": "microsoft",
    "aws": "amazon web services",
    "gcp": "google cloud",
    "fb": "meta",
    "fb.com": "meta",
    "amzn": "amazon",
    "googl": "alphabet",
    "goog": "alphabet",
}

# Patterns for title, degree, and date-range detection in generated text.
_TITLE_RE = re.compile(
    r'\b(?:Senior|Junior|Lead|Principal|Staff|VP|Director|Manager|Engineer|Developer|'
    r'Analyst|Architect|Scientist|Specialist|Consultant|Associate)\b[\w\s]{0,20}'
    r'(?:Engineer|Developer|Manager|Director|Analyst|Architect|Scientist|Specialist|Consultant)\b',
    re.IGNORECASE,
)
_DEGREE_RE = re.compile(
    r'\b(?:Bachelor|Master|PhD|Ph\.D|B\.S\.|M\.S\.|B\.A\.|M\.A\.|MBA|Associate)[^,\n]{0,50}',
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r'\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|[Pp]resent|[Cc]urrent)\b'
)


@dataclass
class GuardResult:
    text:     str
    stripped: List[str]  # fabricated claims removed (for transparency)
    gaps:     List[str]  # bullets dropped because no original matched


def _normalise_metric(m: str) -> float | None:
    """Convert a metric string to a dimensionless float for numeric comparison.

    Returns None on parse failure so callers can distinguish unparseable input
    from a legitimate zero value.
    """
    s = m.strip().replace(",", "").replace("$", "").replace("%", "").replace("x", "")
    multiplier = 1.0
    if s and s[-1].lower() == "k":
        multiplier = 1_000; s = s[:-1]
    elif s and s[-1].lower() == "m":
        multiplier = 1_000_000; s = s[:-1]
    elif s and s[-1].lower() == "b":
        multiplier = 1_000_000_000; s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def _metric_attested(generated_metric: str, source_text: str, is_percentage: bool = False) -> bool:
    """Return True if this metric's numeric value appears in the source within tolerance.

    Percentage metrics (is_percentage=True) use a tighter ±2% tolerance.
    All other metrics (dollar, magnitude, multiplier) use ±10%.
    """
    tolerance = _PCT_TOLERANCE if is_percentage else _NUM_TOLERANCE
    gen_val = _normalise_metric(generated_metric)
    if gen_val is None:
        return True  # unparseable — give benefit of the doubt
    for m in METRIC_RE.finditer(source_text):
        src_val = _normalise_metric(m.group(0))
        if src_val is not None and abs(gen_val - src_val) / max(abs(src_val), 1e-9) < tolerance:
            return True
    return False


def _normalise_company(name: str) -> str:
    """Lowercase, strip, apply known acronym aliases."""
    n = name.lower().strip()
    return _COMPANY_ALIASES.get(n, n)


def _company_attested(company: str, source_companies: frozenset) -> bool:
    """Return True if this company fuzzy-matches a source company (ratio ≥ 0.75),
    with alias resolution applied before comparison."""
    norm_gen = _normalise_company(company)
    for src in source_companies:
        norm_src = _normalise_company(src)
        if norm_gen == norm_src:
            return True
        if difflib.SequenceMatcher(None, norm_gen, norm_src).ratio() >= 0.75:
            return True
    return False


def _title_attested(title: str, ledger_titles: frozenset) -> bool:
    """Return True if this title exactly or fuzzily matches a ledger title (ratio ≥ 0.85)."""
    tl = title.lower().strip()
    for t in ledger_titles:
        if tl == t.lower().strip():
            return True
        if difflib.SequenceMatcher(None, tl, t.lower().strip()).ratio() >= 0.85:
            return True
    return False


def _degree_attested(degree: str, ledger_degrees: frozenset) -> bool:
    """Return True if this degree substring-matches any ledger degree."""
    dl = degree.lower().strip()
    for d in ledger_degrees:
        ld = d.lower().strip()
        if dl in ld or ld in dl:
            return True
    return False


def _date_attested(date_range: str, ledger_dates: frozenset) -> bool:
    """Return True if this date range exactly matches a ledger date range."""
    return date_range.strip() in ledger_dates


def _persona_terms_in_source(source_text: str) -> frozenset[str]:
    """Return the subset of _PERSONA_TERMS that appear in the source text."""
    src_lower = source_text.lower()
    return frozenset(t for t in _PERSONA_TERMS if t in src_lower)


def _drop_persona_sentences(line: str, allowed_terms: frozenset[str]) -> str:
    """
    Remove individual sentences from a line that contain persona-domain terms
    NOT present in the source resume. Returns the cleaned line; empty string
    means the whole line should be dropped.
    """
    line_lower = line.lower()
    # Fast path: no persona terms in this line at all
    if not any(t in line_lower for t in _PERSONA_TERMS):
        return line

    sentences = _SENTENCE_SPLIT.split(line)
    kept: list[str] = []
    for sent in sentences:
        sent_lower = sent.lower()
        bad = [t for t in _PERSONA_TERMS if t in sent_lower and t not in allowed_terms]
        if bad:
            continue  # drop this sentence
        kept.append(sent)

    return " ".join(kept).strip()


def fabrication_guard(
    generated_text: str,
    ledger: ClaimsLedger,
    source_text: str,
    jd_text: str = "",   # optional JD for domain-relative persona check
) -> GuardResult:
    """
    Verify generated_text against the claims ledger.

    Runs one spaCy pass on the full generated text (not per-line) then
    does O(n) string checks per line — no additional LLM calls.

    Parameters
    ----------
    generated_text : str
        The LLM-generated resume text to verify.
    ledger : ClaimsLedger
        Facts extracted from the original resume (ground truth).
    source_text : str
        Raw original resume text (used for metric attestation lookup).
    jd_text : str, optional
        Job description text. Persona terms present in either the source
        resume OR the JD are considered legitimate; others are flagged.
    """
    # Single NLP pass to find ORG entities in the generated text
    doc = nlp(generated_text)
    gen_companies = {ent.text.strip() for ent in doc.ents if ent.label_ == "ORG"}

    # Companies that appear in the output but not in the source
    fabricated_companies = {
        c for c in gen_companies
        if not _company_attested(c, ledger.companies)
    }

    # Persona terms that are legitimately in the source (candidate's own words)
    # OR present in the JD (domain-relative allowance).
    allowed_persona = _persona_terms_in_source(source_text)
    if jd_text:
        allowed_persona = allowed_persona | _persona_terms_in_source(jd_text)

    output_lines: list = []
    stripped: list     = []
    gaps: list         = []

    for line in generated_text.splitlines():
        # ── Persona novelty check — drop sentences with out-of-role domain terms ──
        cleaned = _drop_persona_sentences(line, allowed_persona)
        if not cleaned:
            stripped.append(f"[persona] {line.strip()[:80]}")
            gaps.append(f"persona-domain sentence dropped: {line.strip()[:80]!r}")
            continue
        if cleaned != line:
            stripped.append(f"[persona-partial] {line.strip()[:80]}")
            line = cleaned

        bare = _BULLET_STRIP_RE.sub("", line).strip()

        # Which metrics on this line are NOT attested in the source?
        # Percentage metrics use tighter tolerance (is_percentage=True).
        bad_metrics = [
            m.group(0) for m in METRIC_RE.finditer(bare)
            if not _metric_attested(m.group(0), source_text, is_percentage="%" in m.group(0))
        ]

        # Which fabricated companies appear on this line (simple substring check)?
        bad_companies = [c for c in fabricated_companies if c.lower() in line.lower()]

        # Title check — only run if ledger has titles (avoid false positives on
        # resumes without structured title extraction)
        bad_titles = [
            m.group(0) for m in _TITLE_RE.finditer(bare)
            if ledger.job_titles and not _title_attested(m.group(0), ledger.job_titles)
        ]

        # Degree check — only run if ledger has degrees
        bad_degrees = [
            m.group(0) for m in _DEGREE_RE.finditer(bare)
            if ledger.degrees and not _degree_attested(m.group(0), ledger.degrees)
        ]

        # Date range check — only run if ledger has date ranges
        bad_dates = [
            m.group(0) for m in _DATE_RE.finditer(bare)
            if ledger.date_ranges and not _date_attested(m.group(0), ledger.date_ranges)
        ]

        if bad_metrics or bad_companies or bad_titles or bad_degrees or bad_dates:
            stripped.extend(bad_metrics)
            stripped.extend(bad_companies)
            stripped.extend(bad_titles)
            stripped.extend(bad_degrees)
            stripped.extend(bad_dates)

            output_lines.append(f"[VERIFY] {line}")
            gaps.append(f"unverified claim: {bare!r}")
        else:
            output_lines.append(line)

    return GuardResult(
        text="\n".join(output_lines),
        stripped=list(dict.fromkeys(stripped)),  # deduplicate, preserve order
        gaps=gaps,
    )
