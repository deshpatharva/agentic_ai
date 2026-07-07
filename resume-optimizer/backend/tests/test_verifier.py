"""
Tests for agents/verifier.py — LLM-based final draft verifier (T4.1).

Mocking strategy:
  - `complete` is patched on the verifier module so no real LLM calls are made.
  - `run_agent` is patched to simulate the agent path returning a result.
  - `run_optimization_async` is tested end-to-end with mocked LLM layer.

All tests are async; pytest-asyncio is configured in auto mode via pytest.ini.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make backend/ importable
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-for-tests")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-must-be-32-chars-min!!")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_ledger(companies=None, metrics=None, job_titles=None, degrees=None):
    from agents.fact_extractor import ClaimsLedger
    return ClaimsLedger(
        companies=frozenset(companies or ["Acme Corp", "Beta Inc"]),
        metrics=frozenset(metrics or ["30%", "$2M"]),
        raw_bullets=tuple(),
        job_titles=frozenset(job_titles or ["Senior Software Engineer"]),
        degrees=frozenset(degrees or ["Bachelor of Science"]),
    )


def _mock_complete(text: str) -> AsyncMock:
    """Return a mock for `complete` that yields the given text."""
    mock = AsyncMock(return_value={
        "text": text,
        "input_tokens": 50,
        "output_tokens": 20,
        "cost_usd": 0.0001,
    })
    return mock


SAMPLE_DRAFT = (
    "Increased revenue by 500% at FakeCo while holding the title "
    "Chief Galactic Officer with a PhD in Wizardry."
)

CLEAN_DRAFT = (
    "Improved system reliability by 30% at Acme Corp as a Senior Software Engineer."
)


# ---------------------------------------------------------------------------
# Test 1 — verifier flags an unsupported claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verifier_flags_unsupported_metric():
    """Mock complete to return an unsupported-claim line; result.flagged must be non-empty."""
    from agents.verifier import verify_final_draft

    ledger = _make_ledger()
    flagged_response = "unsupported claim: increased revenue by 500%"

    with patch("agents.verifier.complete", _mock_complete(flagged_response)):
        result = await verify_final_draft(SAMPLE_DRAFT, ledger, original_resume=SAMPLE_DRAFT)

    assert result.flagged, "Expected non-empty flagged list when LLM returns unsupported claims"
    assert any("500%" in f or "revenue" in f.lower() for f in result.flagged)


# ---------------------------------------------------------------------------
# Test 2 — clean draft returns empty flagged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verifier_clean_draft_returns_empty_flagged():
    """Mock complete to return 'VERIFIED'; result.flagged must be []."""
    from agents.verifier import verify_final_draft

    ledger = _make_ledger()

    with patch("agents.verifier.complete", _mock_complete("VERIFIED")):
        result = await verify_final_draft(CLEAN_DRAFT, ledger, original_resume=CLEAN_DRAFT)

    assert result.flagged == [], f"Expected empty flagged list, got: {result.flagged}"


# ---------------------------------------------------------------------------
# Test 3 — verifier preserves draft text unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verifier_result_preserves_draft_text():
    """The verifier must never modify the draft text — only flags."""
    from agents.verifier import verify_final_draft

    ledger = _make_ledger()

    with patch("agents.verifier.complete", _mock_complete("VERIFIED")):
        result = await verify_final_draft(CLEAN_DRAFT, ledger, original_resume=CLEAN_DRAFT)

    assert result.text == CLEAN_DRAFT, (
        f"Expected result.text == original_draft, got: {result.text!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — verifier runs in standard tier via run_optimization_async
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verifier_runs_in_standard_tier():
    """
    Mock run_agent to return an over-claimed draft, mock complete (verifier) to flag it.
    Call run_optimization_async and assert result["verifier_flagged"] is non-empty.
    """
    from orchestration.optimizer import run_optimization_async

    ledger = _make_ledger()
    resume = "Worked at Acme Corp as a Senior Software Engineer."
    jd = "We need a Python engineer."
    keywords = ["python"]
    scores = {
        "ats":         {"score": 70, "missing_keywords": ["python"], "matched_keywords": []},
        "impact":      {"score": 70, "weak_bullets": [],             "strong_bullets": []},
        "skills_gap":  {"score": 70, "missing_skills": [],           "matched_skills": []},
        "readability": {"score": 70, "issues": [],                   "worst_section": "experience"},
        "overall": 70,
    }

    # Agent returns a modified draft with an invented metric
    over_claimed = "Boosted revenue 500% at Acme Corp as a Senior Software Engineer."
    agent_return = {
        "text":          over_claimed,
        "input_tokens":  100,
        "output_tokens": 50,
        "cost_usd":      0.01,
        "iterations":    1,
    }

    # Verifier LLM flags the invented metric
    flagged_line = "unsupported claim: 500% revenue boost not in original resume"

    with (
        patch("orchestration.optimizer.run_agent", AsyncMock(return_value=agent_return)),
        patch("agents.verifier.complete", _mock_complete(flagged_line)),
        patch("orchestration.optimizer.detect_sections", return_value={
            "experience": "Worked at Acme Corp as a Senior Software Engineer."
        }),
    ):
        result = await run_optimization_async(
            job_id="test-job-123",
            resume_text=resume,
            jd_text=jd,
            jd_keywords=keywords,
            claims_ledger=ledger,
            scores=scores,
        )

    assert "verifier_flagged" in result, "run_optimization_async must include 'verifier_flagged' in return dict"
    assert result["verifier_flagged"], (
        f"Expected non-empty verifier_flagged; got: {result['verifier_flagged']}"
    )


# ---------------------------------------------------------------------------
# Test 5 — verifier prompt contains ledger companies and metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verifier_uses_ledger_companies_and_metrics():
    """The prompt sent to complete must contain the ledger's companies and metrics."""
    from agents.verifier import verify_final_draft

    ledger = _make_ledger(
        companies=["Zeta Corp", "Omega Ltd"],
        metrics=["99%", "$5M"],
    )

    captured_prompt: list[str] = []

    async def capture_complete(prompt, model, **kwargs):
        captured_prompt.append(prompt)
        return {"text": "VERIFIED", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0}

    with patch("agents.verifier.complete", capture_complete):
        await verify_final_draft(CLEAN_DRAFT, ledger, original_resume=CLEAN_DRAFT)

    assert captured_prompt, "complete was never called"
    prompt = captured_prompt[0]

    assert "Zeta Corp" in prompt or "Omega Ltd" in prompt, (
        "Ledger companies must appear in the verifier prompt"
    )
    assert "99%" in prompt or "$5M" in prompt, (
        "Ledger metrics must appear in the verifier prompt"
    )


# ---------------------------------------------------------------------------
# Test 6 -- verifier prompt includes original resume text and flag rules
# ---------------------------------------------------------------------------

async def test_verifier_prompt_includes_original_and_flag_rules(monkeypatch):
    import agents.verifier as verifier
    from agents.fact_extractor import ClaimsLedger

    captured = {}

    async def fake_complete(prompt, model, **kw):
        captured["prompt"] = prompt
        return {"text": "VERIFIED", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    monkeypatch.setattr(verifier, "complete", fake_complete)
    ledger = ClaimsLedger(companies=frozenset({"Acme"}), metrics=frozenset({"40%"}),
                          raw_bullets=())
    result = await verifier.verify_final_draft(
        "Reduced load time by 40% at Acme.", ledger,
        original_resume="Original: reduced page load time by 40% at Acme.",
    )
    p = captured["prompt"]
    assert "ORIGINAL RESUME (ground truth):" in p
    assert "reduced page load time by 40%" in p
    assert "Do not flag rephrasings of supported claims" in p
    assert "At most 10 flags" in p
    assert result.flagged == []
