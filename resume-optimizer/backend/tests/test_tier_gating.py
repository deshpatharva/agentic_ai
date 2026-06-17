"""Tests for tier gating — plan selects agent_loop vs debate_loop (T4.3)."""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DELTA_STORAGE_PATH", "./test_delta_store")

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_SCORES = {
    "ats":         {"score": 70, "missing_keywords": ["python"], "matched_keywords": []},
    "impact":      {"score": 80, "weak_bullets": [],             "strong_bullets": []},
    "skills_gap":  {"score": 75, "missing_skills": [],           "matched_skills": []},
    "readability": {"score": 80, "issues": [],                   "worst_section": "experience"},
    "overall": 76,
}

SAMPLE_RESUME = "John Doe\nSoftware Engineer\n\nEXPERIENCE\nDid things at a company."
SAMPLE_JD     = "We need a Python developer with experience in cloud computing."


def _make_ledger():
    from agents.fact_extractor import ClaimsLedger
    return ClaimsLedger(companies=frozenset(), metrics=frozenset(), raw_bullets=tuple())


def _driver_result(text="Optimized resume text."):
    """Return a fake driver result dict."""
    return {
        "text":          text,
        "input_tokens":  100,
        "output_tokens": 50,
        "cost_usd":      0.01,
        "iterations":    1,
    }


def _verifier_result(text="Optimized resume text."):
    """Return a fake VerifierResult."""
    from agents.verifier import VerifierResult
    return VerifierResult(
        text=text,
        flagged=[],
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
    )


# ---------------------------------------------------------------------------
# Test 1: standard plan routes to agent_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standard_plan_uses_agent_loop():
    """plan='standard' (default) must call run_agent and never call run_debate."""
    from orchestration import optimizer

    mock_run_agent  = AsyncMock(return_value=_driver_result())
    mock_run_debate = AsyncMock(return_value=_driver_result())
    mock_verify     = AsyncMock(return_value=_verifier_result())

    with patch.object(optimizer, "run_agent",          mock_run_agent), \
         patch.object(optimizer, "run_debate",         mock_run_debate), \
         patch.object(optimizer, "verify_final_draft", mock_verify):
        await optimizer.run_optimization_async(
            job_id="test-job-1",
            resume_text=SAMPLE_RESUME,
            jd_text=SAMPLE_JD,
            jd_keywords=["python"],
            claims_ledger=_make_ledger(),
            scores=SAMPLE_SCORES,
            plan="standard",
        )

    mock_run_agent.assert_called_once()
    mock_run_debate.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: pro plan with flag enabled routes to debate_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pro_plan_uses_debate_loop():
    """plan='pro' with PRO_DEBATE_ENABLED=True must call run_debate and never call run_agent."""
    import config
    from orchestration import optimizer

    mock_run_agent  = AsyncMock(return_value=_driver_result())
    mock_run_debate = AsyncMock(return_value=_driver_result())
    mock_verify     = AsyncMock(return_value=_verifier_result())

    with patch.object(optimizer, "run_agent",          mock_run_agent), \
         patch.object(optimizer, "run_debate",         mock_run_debate), \
         patch.object(optimizer, "verify_final_draft", mock_verify), \
         patch.object(config, "PRO_DEBATE_ENABLED", True):
        await optimizer.run_optimization_async(
            job_id="test-job-2",
            resume_text=SAMPLE_RESUME,
            jd_text=SAMPLE_JD,
            jd_keywords=["python"],
            claims_ledger=_make_ledger(),
            scores=SAMPLE_SCORES,
            plan="pro",
        )

    mock_run_debate.assert_called_once()
    mock_run_agent.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: pro plan with flag disabled falls back to agent_loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pro_plan_with_flag_disabled_falls_back_to_agent_loop():
    """plan='pro' but PRO_DEBATE_ENABLED=False must call run_agent (flag is the gate)."""
    import config
    from orchestration import optimizer

    mock_run_agent  = AsyncMock(return_value=_driver_result())
    mock_run_debate = AsyncMock(return_value=_driver_result())
    mock_verify     = AsyncMock(return_value=_verifier_result())

    with patch.object(optimizer, "run_agent",          mock_run_agent), \
         patch.object(optimizer, "run_debate",         mock_run_debate), \
         patch.object(optimizer, "verify_final_draft", mock_verify), \
         patch.object(config, "PRO_DEBATE_ENABLED", False):
        await optimizer.run_optimization_async(
            job_id="test-job-3",
            resume_text=SAMPLE_RESUME,
            jd_text=SAMPLE_JD,
            jd_keywords=["python"],
            claims_ledger=_make_ledger(),
            scores=SAMPLE_SCORES,
            plan="pro",
        )

    mock_run_agent.assert_called_once()
    mock_run_debate.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: verifier runs regardless of plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_runs_regardless_of_plan():
    """verify_final_draft must be called exactly once for both standard and pro paths."""
    import config
    from orchestration import optimizer

    # -- Standard path --
    mock_run_agent  = AsyncMock(return_value=_driver_result())
    mock_run_debate = AsyncMock(return_value=_driver_result())
    mock_verify     = AsyncMock(return_value=_verifier_result())

    with patch.object(optimizer, "run_agent",          mock_run_agent), \
         patch.object(optimizer, "run_debate",         mock_run_debate), \
         patch.object(optimizer, "verify_final_draft", mock_verify):
        await optimizer.run_optimization_async(
            job_id="test-job-4a",
            resume_text=SAMPLE_RESUME,
            jd_text=SAMPLE_JD,
            jd_keywords=["python"],
            claims_ledger=_make_ledger(),
            scores=SAMPLE_SCORES,
            plan="standard",
        )

    mock_verify.assert_called_once(), "verify_final_draft must run on standard path"

    # -- Pro path --
    mock_run_agent  = AsyncMock(return_value=_driver_result())
    mock_run_debate = AsyncMock(return_value=_driver_result())
    mock_verify     = AsyncMock(return_value=_verifier_result())

    with patch.object(optimizer, "run_agent",          mock_run_agent), \
         patch.object(optimizer, "run_debate",         mock_run_debate), \
         patch.object(optimizer, "verify_final_draft", mock_verify), \
         patch.object(config, "PRO_DEBATE_ENABLED", True):
        await optimizer.run_optimization_async(
            job_id="test-job-4b",
            resume_text=SAMPLE_RESUME,
            jd_text=SAMPLE_JD,
            jd_keywords=["python"],
            claims_ledger=_make_ledger(),
            scores=SAMPLE_SCORES,
            plan="pro",
        )

    mock_verify.assert_called_once(), "verify_final_draft must run on pro path"


# ---------------------------------------------------------------------------
# Test 5: fabrication_guard is present in both drivers (structural check)
# ---------------------------------------------------------------------------


def test_guard_cannot_be_disabled_by_plan():
    """fabrication_guard must be imported (and thus present) in both driver files.

    This is a structural test — it reads the source of both modules and checks
    that 'fabrication_guard' appears as an import, confirming neither driver
    can be silently stripped of the guard by a future refactor.
    """
    backend_dir = Path(__file__).parent.parent

    for module_rel in (
        "orchestration/agent_loop.py",
        "orchestration/debate_loop.py",
    ):
        src = (backend_dir / module_rel).read_text(encoding="utf-8")
        assert "fabrication_guard" in src, (
            f"fabrication_guard import missing from {module_rel} — "
            "guard must be present in BOTH Standard and Pro drivers"
        )
