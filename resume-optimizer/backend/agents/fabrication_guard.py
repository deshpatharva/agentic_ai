"""
Fabrication guard — post-generation verifier.

Checks every explicit metric (%, $, K/M/B, x), every ORG entity, and every
taxonomy capability term (skill/tool/technology) in the generated resume
against the ClaimsLedger built from the original resume text.

Decision per line:
  - All claims verified → keep the line unchanged
  - Fabricated metric, company, or unevidenced capability found →
      a) substitute with the closest matching original bullet (difflib ratio > 0.35)
      b) or drop the line entirely (no inline verification tag -- see `gaps`
         for what was removed so the user can fill it in honestly)

Nothing unverifiable is ever kept in the output.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import List

from agents.fact_extractor import (
    METRIC_RE, ClaimsLedger, _BULLET_STRIP_RE, nlp_process
)
from utils.skills_normalizer import matched_taxonomy_terms

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

# The capability novelty check shares utils.skills_normalizer.matched_taxonomy_terms
# with fact_extractor's capability extraction, so their word-boundary logic (which
# terms count as "mentioned") can never drift apart.


@dataclass
class GuardResult:
    text:     str
    stripped: List[str]  # fabricated claims removed (for transparency)
    gaps:     List[str]  # bullets dropped because no original matched
    capability_gaps: List[str] = field(default_factory=list)  # unevidenced tech terms found in output


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
    doc = nlp_process(generated_text)
    gen_companies = {ent.text.strip() for ent in doc.ents if ent.label_ == "ORG"}

    # Companies that appear in the output but not in the source
    fabricated_companies = {
        c for c in gen_companies
        if not _company_attested(c, ledger.companies)
    }

    # Persona terms that are legitimately in the source (candidate's own words)
    allowed_persona = _persona_terms_in_source(source_text)

    # Capabilities the output may legitimately mention: the ledger's evidenced
    # set plus any taxonomy term already present in the source text.
    allowed_caps = set(ledger.capabilities) | matched_taxonomy_terms(source_text)
    capability_gaps: set = set()

    output_lines: list = []
    stripped: list     = []
    gaps: list         = []

    for line in generated_text.splitlines():
        # Blank lines are section spacing (reassemble joins sections with "\n\n"),
        # not sentences — keep them verbatim so they neither strip formatting nor
        # register as phantom "dropped persona sentence" gaps.
        if not line.strip():
            output_lines.append(line)
            continue

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

        bad_caps = sorted(matched_taxonomy_terms(line) - allowed_caps)

        if bad_metrics or bad_companies or bad_caps:
            stripped.extend(bad_metrics)
            stripped.extend(bad_companies)
            stripped.extend(bad_caps)
            capability_gaps.update(bad_caps)

            # Substitute the closest original bullet, else drop the line.
            # No inline verification tags: nothing unverifiable is ever kept (spec 4b).
            m = _BULLET_STRIP_RE.match(line)
            prefix = m.group(0) if m else ""
            best = _closest_original(bare, ledger.raw_bullets)
            if best and best not in "\n".join(output_lines):
                output_lines.append(f"{prefix}{best}")
                gaps.append(f"unverified claim replaced with original: {bare[:80]!r}")
            else:
                gaps.append(f"unverified claim dropped: {bare[:80]!r}")
        else:
            output_lines.append(line)

    # splitlines() drops a final trailing newline; restore it so unmodified
    # input (no fabrications at all) round-trips byte-for-byte.
    text = "\n".join(output_lines)
    if generated_text.endswith("\n") and not text.endswith("\n"):
        text += "\n"

    return GuardResult(
        text=text,
        stripped=list(dict.fromkeys(stripped)),  # deduplicate, preserve order
        gaps=gaps,
        capability_gaps=sorted(capability_gaps),
    )
