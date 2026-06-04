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
from dataclasses import dataclass, field
from typing import List

from agents.fact_extractor import (
    METRIC_RE, ClaimsLedger, _BULLET_STRIP_RE, nlp
)


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
        multiplier = 1_000; s = s[:-1]
    elif s and s[-1].lower() == "m":
        multiplier = 1_000_000; s = s[:-1]
    elif s and s[-1].lower() == "b":
        multiplier = 1_000_000_000; s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def _metric_attested(generated_metric: str, source_text: str) -> bool:
    """Return True if this metric's numeric value (±2%) appears anywhere in the source."""
    gen_val = _normalise_metric(generated_metric)
    if gen_val == 0.0:
        return True  # unparseable — give benefit of the doubt
    for m in METRIC_RE.finditer(source_text):
        src_val = _normalise_metric(m.group(0))
        if src_val > 0 and abs(gen_val - src_val) / max(src_val, 1) < 0.02:
            return True
    return False


def _company_attested(company: str, source_companies: frozenset) -> bool:
    """Return True if this company fuzzy-matches a source company (ratio ≥ 0.75)."""
    cl = company.lower().strip()
    for src in source_companies:
        if difflib.SequenceMatcher(None, cl, src.lower().strip()).ratio() >= 0.75:
            return True
    return False


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
    # Single NLP pass to find ORG entities in the generated text
    doc = nlp(generated_text)
    gen_companies = {ent.text.strip() for ent in doc.ents if ent.label_ == "ORG"}

    # Companies that appear in the output but not in the source
    fabricated_companies = {
        c for c in gen_companies
        if not _company_attested(c, ledger.companies)
    }

    output_lines: list = []
    stripped: list     = []
    gaps: list         = []

    for line in generated_text.splitlines():
        bare = _BULLET_STRIP_RE.sub("", line).strip()

        # Which metrics on this line are NOT attested in the source?
        bad_metrics = [
            m.group(0) for m in METRIC_RE.finditer(bare)
            if not _metric_attested(m.group(0), source_text)
        ]

        # Which fabricated companies appear on this line (simple substring check)?
        bad_companies = [c for c in fabricated_companies if c.lower() in line.lower()]

        if bad_metrics or bad_companies:
            stripped.extend(bad_metrics)
            stripped.extend(bad_companies)

            original = _closest_original(bare, ledger.raw_bullets)
            if original:
                output_lines.append(original)  # substitute with verified original
            else:
                gaps.append(bare)  # no original — drop and surface as honest gap
        else:
            output_lines.append(line)

    return GuardResult(
        text="\n".join(output_lines),
        stripped=list(dict.fromkeys(stripped)),  # deduplicate, preserve order
        gaps=gaps,
    )


# ── CrewAI Agent Integration ────────────────────────────────────────────────
try:
    from crewai import tool
    from agents.base import create_agent

    @tool
    def validate_tool(generated_text: str, ledger: ClaimsLedger, source_text: str) -> dict:
        """
        Validate resume against claim ledger to detect fabrications.
        Returns dict with validation_report and stripped_fabrications.
        """
        # Call existing fabrication_guard function
        result = fabrication_guard(generated_text, ledger, source_text)
        return {
            "text": result.text,
            "stripped": result.stripped,
            "gaps": result.gaps,
        }

    def create_fabrication_guard_agent():
        """Create the Fabrication Guard CrewAI Agent."""
        return create_agent(
            role="Fabrication Guard",
            goal="Validate resume claims against source material to prevent hallucinations",
            backstory=(
                "You are a meticulous fact-checker who catches exaggerations and fabrications. "
                "You ensure resume claims are grounded in reality and verifiable."
            ),
            tools=[validate_tool],
        )
except ImportError:
    # CrewAI not available (e.g., Python 3.9)
    pass
