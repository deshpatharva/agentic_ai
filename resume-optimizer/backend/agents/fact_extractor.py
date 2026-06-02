"""
Fact extractor — builds a ClaimsLedger from raw resume text.
Pure-Python + spaCy NER; no LLM calls. Deterministic.

The ledger is the anti-hallucination ground truth:
  1. Passed to the rewriter so it knows which numbers/companies exist.
  2. Used by fabrication_guard to verify post-generation output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    raise RuntimeError(
        "spaCy model 'en_core_web_sm' not found. "
        "Run: python -m spacy download en_core_web_sm"
    )

# Explicit quantitative metrics — the highest-risk fabrication targets.
# Only matches units that carry real semantic weight (%, $, K/M/B, x-multiplier).
# Plain integers ("5 engineers") are not checked — too many false positives.
METRIC_RE = re.compile(
    r"""
    (?:
        \$[\d,]+(?:\.\d+)?[KMBkmb]?   # dollar: $2M, $500K, $1,000
      | \d+(?:\.\d+)?%                 # percent: 30%, 99.9%
      | \d+(?:\.\d+)?[KMBkmb]\b        # magnitude: 50K, 2M, 3B
      | \d+(?:\.\d+)?x\b               # multiplier: 3x, 10x
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_BULLET_STRIP_RE = re.compile(r"^[\s•\-–—*·►▸]+")


@dataclass(frozen=True)
class ClaimsLedger:
    companies:   frozenset  # ORG entities extracted from the original resume
    metrics:     frozenset  # explicit quantitative metrics found in the original text
    raw_bullets: tuple      # every non-header line verbatim (provenance for guard)

    def prompt_block(self) -> str:
        """Compact string injected into the rewriter prompt."""
        parts = ["CLAIMS LEDGER — only use facts from the original resume:"]
        if self.metrics:
            parts.append(f"  Permitted metrics: {', '.join(sorted(self.metrics))}")
        if self.companies:
            parts.append(f"  Permitted companies/orgs: {', '.join(sorted(self.companies))}")
        if not self.metrics and not self.companies:
            parts.append("  (no explicit metrics or organisations detected)")
        return "\n".join(parts)


def extract_claims(resume_text: str) -> ClaimsLedger:
    """
    Parse resume text into a ClaimsLedger.
    Same input always produces the same ledger.
    """
    doc = nlp(resume_text)

    companies = frozenset(
        ent.text.strip()
        for ent in doc.ents
        if ent.label_ == "ORG" and ent.text.strip()
    )

    metrics = frozenset(m.group(0) for m in METRIC_RE.finditer(resume_text))

    bullets = [
        _BULLET_STRIP_RE.sub("", line).strip()
        for line in resume_text.splitlines()
        if _BULLET_STRIP_RE.sub("", line).strip()
        and len(_BULLET_STRIP_RE.sub("", line).strip()) > 15
        and not _BULLET_STRIP_RE.sub("", line).strip().endswith(":")
    ]

    return ClaimsLedger(
        companies=companies,
        metrics=metrics,
        raw_bullets=tuple(bullets),
    )
