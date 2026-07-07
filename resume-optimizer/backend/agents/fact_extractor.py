"""
Fact extractor — builds a ClaimsLedger from raw resume text.
Pure-Python + spaCy NER; no LLM calls. Deterministic.

The ledger is the anti-hallucination ground truth:
  1. Passed to the rewriter so it knows which numbers/companies exist.
  2. Used by fabrication_guard to verify post-generation output.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

import spacy

from utils.section_parser import detect_sections
from utils.skills_normalizer import _parse_skills, taxonomy_terms

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    raise RuntimeError(
        "spaCy model 'en_core_web_sm' not found. "
        "Run: python -m spacy download en_core_web_sm"
    )

# A spaCy Language object is a single shared module global and is NOT safe for
# concurrent __call__. Guard/claim extraction now runs inside asyncio.to_thread
# from several pipelines at once (agent_loop, debate_loop, main), so every call
# into the pipeline must go through this lock.
_nlp_lock = threading.Lock()


def nlp_process(text: str):
    """Thread-safe entry point to the shared spaCy pipeline."""
    with _nlp_lock:
        return nlp(text)

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
    job_titles:  frozenset = field(default_factory=frozenset)  # job titles found in the resume
    degrees:     frozenset = field(default_factory=frozenset)  # academic degrees found in the resume
    date_ranges: frozenset = field(default_factory=frozenset)  # date ranges found in the resume
    capabilities: frozenset = field(default_factory=frozenset)  # evidenced skills/tools (lowercased)

    def prompt_block(self) -> str:
        """Compact string injected into the rewriter prompt."""
        parts = ["CLAIMS LEDGER — only use facts from the original resume:"]
        if self.metrics:
            parts.append(f"  Permitted metrics: {', '.join(sorted(self.metrics))}")
        if self.companies:
            parts.append(f"  Permitted companies/orgs: {', '.join(sorted(self.companies))}")
        if self.capabilities:
            parts.append(f"  Verified capabilities: {', '.join(sorted(self.capabilities))}")
        if not self.metrics and not self.companies and not self.capabilities:
            parts.append("  (no explicit metrics or organisations detected)")
        return "\n".join(parts)


# Custom boundaries so "c++", "c#", "ci/cd" match whole terms and "go" never
# matches inside "Django". Compiled once at import.
_TAXONOMY_PATTERNS: dict = {
    t: re.compile(r"(?<![\w+#])" + re.escape(t) + r"(?![\w+#])")
    for t in taxonomy_terms()
}


def _extract_capabilities(resume_text: str) -> frozenset:
    caps: set = set()
    skills_text = detect_sections(resume_text).get("skills", "")
    if skills_text.strip():
        for tok in _parse_skills(skills_text):
            tok_lower = tok.lower()
            # Keep the whole comma-delimited token (so multi-word tool names
            # like "SnowConvert Custom Tool" survive intact) and also add its
            # individual words (so single-word skills listed without commas,
            # e.g. "Django only", still surface "django" on its own).
            caps.add(tok_lower)
            caps.update(tok_lower.split())
    text_lower = resume_text.lower()
    for term, pattern in _TAXONOMY_PATTERNS.items():
        if pattern.search(text_lower):
            caps.add(term)
    return frozenset(caps)


def extract_claims(resume_text: str) -> ClaimsLedger:
    """
    Parse resume text into a ClaimsLedger.
    Same input always produces the same ledger.
    """
    doc = nlp_process(resume_text)

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

    # Job titles — pattern matching on common title words
    _TITLE_PAT = re.compile(
        r'\b(?:Senior|Junior|Lead|Principal|Staff|VP|Director|Manager|Engineer|Developer|'
        r'Analyst|Architect|Scientist|Specialist|Consultant|Associate)\b[\w\s]{0,20}'
        r'(?:Engineer|Developer|Manager|Director|Analyst|Architect|Scientist|Specialist|Consultant)\b',
        re.IGNORECASE,
    )
    job_titles = frozenset(m.group().strip() for m in _TITLE_PAT.finditer(resume_text))

    # Degrees
    _DEGREE_PAT = re.compile(
        r'\b(?:Bachelor|Master|PhD|Ph\.D|B\.S\.|M\.S\.|B\.A\.|M\.A\.|MBA|Associate)[^,\n]{0,50}',
        re.IGNORECASE,
    )
    degrees = frozenset(m.group().strip() for m in _DEGREE_PAT.finditer(resume_text))

    # Date ranges
    _DATE_PAT = re.compile(
        r'\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|[Pp]resent|[Cc]urrent)\b'
    )
    date_ranges = frozenset(m.group() for m in _DATE_PAT.finditer(resume_text))

    return ClaimsLedger(
        companies=companies,
        metrics=metrics,
        raw_bullets=tuple(bullets),
        job_titles=job_titles,
        degrees=degrees,
        date_ranges=date_ranges,
        capabilities=_extract_capabilities(resume_text),
    )
