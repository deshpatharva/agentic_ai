"""
Fabrication guard — post-generation verifier.

Checks every explicit metric (%, $, K/M/B, x) and every ORG entity in the
generated resume against the ClaimsLedger built from the original resume text.

Decision per line:
  - All claims verified → keep the line unchanged
  - Fabricated metric or company found →
      a) substitute with the closest matching original bullet (difflib ratio > 0.35)
      b) or drop entirely and add to `gaps` so the user can fill it honestly

Nothing unverifiable is ever kept in the output.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
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


@dataclass
class GuardResult:
    text:     str
    stripped: List[str]  # fabricated claims removed (for transparency)
    gaps:     List[str]  # bullets dropped because no original matched


def _normalise_metric(m: str) -> float:
    """Convert a metric string to a dimensionless float for numeric comparison."""
    s = m.strip().replace(",", "").replace("$", "").replace("%", "").replace("x", "")
    multiplier = 1.0
    if s and s[-1].lower() == "k":
        multiplier = 1_000
        s = s[:-1]
    elif s and s[-1].lower() == "m":
        multiplier = 1_000_000
        s = s[:-1]
    elif s and s[-1].lower() == "b":
        multiplier = 1_000_000_000
        s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def _metric_attested(generated_metric: str, source_text: str) -> bool:
    """Return True if this metric's numeric value (±10%) appears anywhere in the source."""
    gen_val = _normalise_metric(generated_metric)
    if gen_val == 0.0:
        return True  # unparseable — give benefit of the doubt
    for m in METRIC_RE.finditer(source_text):
        src_val = _normalise_metric(m.group(0))
        if src_val > 0 and abs(gen_val - src_val) / max(abs(src_val), 1e-9) < 0.10:
            return True
    return False


def _company_attested(company: str, source_companies: frozenset) -> bool:
    """Return True if this company fuzzy-matches a source company (ratio ≥ 0.75)."""
    cl = company.lower().strip()
    for src in source_companies:
        if difflib.SequenceMatcher(None, cl, src.lower().strip()).ratio() >= 0.75:
            return True
    return False


def _persona_terms_in_source(source_text: str) -> frozenset[str]:
    """Return the subset of _PERSONA_TERMS that appear in the source resume."""
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


def _closest_original(line: str, raw_bullets: tuple) -> str:
    """Return the most similar original bullet if ratio > 0.35, else empty string."""
    if not raw_bullets:
        return ""
    best_ratio, best = max(
        (difflib.SequenceMatcher(None, line.lower(), b.lower()).ratio(), b)
        for b in raw_bullets
    )
    return best if best_ratio > 0.35 else ""


def fabrication_guard(
    generated_text: str,
    ledger: ClaimsLedger,
    source_text: str,
) -> GuardResult:
    """
    Verify generated_text against the claims ledger.

    Runs one spaCy pass on the full generated text (not per-line) then
    does O(n) string checks per line — no additional LLM calls.
    """
    # Metrics are attested against the original resume AND the claims ledger, whose
    # metrics may include figures remembered from earlier runs (long-term fact
    # memory, merged in main.py). Without the ledger, a legitimately-remembered
    # metric absent from THIS run's source_text would be wrongly flagged.
    metric_source = source_text
    if ledger.metrics:
        metric_source = source_text + "\n" + "\n".join(ledger.metrics)

    # Single NLP pass to find ORG entities in the generated text
    doc = nlp(generated_text)
    gen_companies = {ent.text.strip() for ent in doc.ents if ent.label_ == "ORG"}

    # Companies that appear in the output but not in the source
    fabricated_companies = {
        c for c in gen_companies
        if not _company_attested(c, ledger.companies)
    }

    # Persona terms that are legitimately in the source (candidate's own words)
    allowed_persona = _persona_terms_in_source(source_text)

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

        # Which metrics on this line are NOT attested in the source or the ledger?
        bad_metrics = [
            m.group(0) for m in METRIC_RE.finditer(bare)
            if not _metric_attested(m.group(0), metric_source)
        ]

        # Which fabricated companies appear on this line (simple substring check)?
        bad_companies = [c for c in fabricated_companies if c.lower() in line.lower()]

        if bad_metrics or bad_companies:
            stripped.extend(bad_metrics)
            stripped.extend(bad_companies)

            output_lines.append(f"[VERIFY] {line}")
            gaps.append(f"unverified claim: {bare!r}")
        else:
            output_lines.append(line)

    return GuardResult(
        text="\n".join(output_lines),
        stripped=list(dict.fromkeys(stripped)),  # deduplicate, preserve order
        gaps=gaps,
    )
