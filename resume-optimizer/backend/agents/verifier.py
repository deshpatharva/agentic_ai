"""LLM-based verifier: checks final draft against claims ledger for unsupported claims.

Runs as a single LLM call after the agent loop (or deterministic fallback) completes.
It only flags — it never modifies the draft text.
Runs in EVERY tier (Standard and Pro alike).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from agents.fact_extractor import ClaimsLedger
from config import MODEL_VERIFIER
from llm import complete

_logger = logging.getLogger(__name__)


@dataclass
class VerifierResult:
    text: str                               # draft unchanged — verifier only flags, never modifies
    flagged: List[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


async def verify_final_draft(draft: str, ledger: ClaimsLedger) -> VerifierResult:
    """Single LLM call that checks draft against the claims ledger.

    Args:
        draft:  The final optimized resume text produced by the pipeline.
        ledger: The ClaimsLedger built from the original (unmodified) resume.

    Returns:
        VerifierResult with:
            - text:    the draft, unchanged
            - flagged: list of unsupported-claim strings (empty if clean)
    """
    if not draft.strip():
        return VerifierResult(text=draft)

    companies_str = ", ".join(sorted(ledger.companies)) or "none"
    metrics_str   = ", ".join(sorted(ledger.metrics))   or "none"
    titles_str    = ", ".join(sorted(ledger.job_titles)) or "none"
    degrees_str   = ", ".join(sorted(ledger.degrees))   or "none"

    prompt = f"""You are a resume verification assistant. Check this resume draft for unsupported claims.

VERIFIED FACTS FROM ORIGINAL RESUME:
- Companies: {companies_str}
- Metrics: {metrics_str}
- Job Titles: {titles_str}
- Degrees: {degrees_str}

RESUME DRAFT:
{draft[:3000]}

List any claims in the draft that are NOT supported by the verified facts above.
Focus on: invented metrics/numbers, company names not in the list, job titles not earned, degrees not held.
If the draft is clean, output exactly: VERIFIED

Output format: one unsupported claim per line, or "VERIFIED" if clean. No prose."""

    try:
        llm_result = await complete(prompt, MODEL_VERIFIER)
        text = llm_result["text"].strip()
    except Exception as exc:
        _logger.warning("verifier LLM call failed (%s) — skipping verification", exc)
        return VerifierResult(text=draft)

    if text.upper() == "VERIFIED" or not text:
        flagged = []
    else:
        flagged = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and line.strip().upper() != "VERIFIED"
        ]

    if flagged:
        _logger.info("verifier flagged %d unsupported claim(s)", len(flagged))

    return VerifierResult(
        text=draft,
        flagged=flagged,
        input_tokens=llm_result.get("input_tokens", 0),
        output_tokens=llm_result.get("output_tokens", 0),
        cost_usd=llm_result.get("cost_usd", 0.0),
    )
