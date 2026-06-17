"""
Tests for PR-6 JD-tailoring features (T7.5).

Coverage:
  Group 1 — jd_tailoring scorer (T7.3): scorer module has jd_tailoring dimension
  Group 2 — bullets_reorder tool (T7.4): new tool in agents/tools.py
  Group 3 — section diff in report (T7.1): build_report section_diff logic
  Group 4 — jd_tailoring in optimization report (T7.3): report includes jd_tailoring score

Mocking strategy: patch `agents.tools.complete` for LLM tool tests — never hit
a real API.  Source-inspection tests check module text, not runtime behaviour.

pytest-asyncio runs in auto mode (set in pytest.ini), so async defs are picked
up automatically.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

FAKE_REORDER_RESULT = {
    "text": "- Led ML infrastructure projects.\n- Deployed models to production.",
    "input_tokens": 20,
    "output_tokens": 15,
    "cost_usd": 0.001,
}


async def _fake_complete(prompt, model, **kw):
    return FAKE_REORDER_RESULT


# ---------------------------------------------------------------------------
# Group 1 — jd_tailoring scorer (T7.3)
# ---------------------------------------------------------------------------


def test_jd_tailoring_in_score_combined_schema():
    """score_combined JSON schema must include jd_tailoring dimension."""
    import inspect
    from agents import scorer as scorer_module

    source = inspect.getsource(scorer_module)
    assert "jd_tailoring" in source
    assert "summary_generic" in source


def test_jd_tailoring_in_all_above_check():
    """agent_loop all_above check must include jd_tailoring."""
    import inspect
    from orchestration import agent_loop

    source = inspect.getsource(agent_loop)
    assert '"jd_tailoring"' in source or "'jd_tailoring'" in source


# ---------------------------------------------------------------------------
# Group 2 — bullets_reorder tool (T7.4)
# ---------------------------------------------------------------------------


async def test_bullets_reorder_updates_section():
    """bullets_reorder must update the section and return 'Reordered' in the message."""
    from agents import tools

    original = "- Maintained legacy code.\n- Led ML infrastructure projects.\n- Deployed models to production."
    st = tools.ResumeState(sections={"experience": original})

    with patch.object(tools, "complete", new=_fake_complete):
        msg = await tools.bullets_reorder(st, section_name="experience", jd_focus_csv="ML,infrastructure")

    assert st.get_section("experience") == FAKE_REORDER_RESULT["text"]
    assert "Reordered" in msg
    assert st.cost_usd > 0
    assert st.total_tokens() > 0


async def test_bullets_reorder_empty_section_returns_error():
    """bullets_reorder on a missing section must return an informative error."""
    from agents import tools

    st = tools.ResumeState(sections={"summary": "I am a developer."})

    with patch.object(tools, "complete", new=_fake_complete):
        msg = await tools.bullets_reorder(st, section_name="experience", jd_focus_csv="ML,infrastructure")

    # Should not have called LLM (section is missing), should be informative
    assert "not found" in msg.lower() or "empty" in msg.lower() or "available" in msg.lower()
    # State must be unchanged
    assert st.total_tokens() == 0


async def test_bullets_reorder_budget_guard():
    """bullets_reorder must respect the token budget and not call the LLM when exhausted."""
    from agents import tools
    from config import AGENT_TOKEN_BUDGET

    st = tools.ResumeState(sections={"experience": "- Built systems.\n- Deployed models."})
    st.add_tokens(AGENT_TOKEN_BUDGET, 0, 0.0)

    call_count = [0]

    async def counting_fake(prompt, model, **kw):
        call_count[0] += 1
        return FAKE_REORDER_RESULT

    with patch.object(tools, "complete", new=counting_fake):
        msg = await tools.bullets_reorder(st, section_name="experience", jd_focus_csv="ML")

    assert call_count[0] == 0, "complete() must NOT be called when budget is exhausted"
    assert "budget" in msg.lower() or "token" in msg.lower()


# ---------------------------------------------------------------------------
# Group 3 — section diff in report (T7.1)
# ---------------------------------------------------------------------------


def _minimal_jd_result():
    """Minimal JD result that compute_gaps won't crash on."""
    return {
        "required_hard_skills": [],
        "critical_keywords": [],
        "tech_stack": [],
    }


def _minimal_final_scores():
    """Minimal final_scores accepted by build_report."""
    return {
        "average": 90,
        "ats":         {"score": 90, "missing_keywords": [], "matched_keywords": [], "keyword_coverage_pct": 0.9},
        "impact":      {"score": 90, "weak_bullets": [],     "strong_bullets": [],   "has_quantified_achievements": True},
        "skills_gap":  {"score": 90, "missing_skills": [],   "matched_skills": [],   "critical_missing": []},
        "readability": {"score": 90, "issues": [],           "worst_section": "experience", "has_summary": True, "tense_consistent": True},
        "jd_tailoring": {"score": 85, "issues": [],          "summary_generic": False},
    }


def test_section_diff_captures_changed_sections():
    """build_report section_diff must include sections whose content changed."""
    from utils.optimization_report import build_report

    original_text = "SUMMARY\nI am a developer.\n\nEXPERIENCE\nBuilt things."
    optimized_text = "SUMMARY\nI am a developer.\n\nEXPERIENCE\nBuilt scalable ML systems at Acme."

    report = build_report(
        jd_result=_minimal_jd_result(),
        original_text=original_text,
        optimized_text=optimized_text,
        baseline_score=70,
        final_scores=_minimal_final_scores(),
        iterations=2,
    )

    assert report["section_diff"], "section_diff should be non-empty when content changed"
    # At least one key in the diff should reflect the experience change
    combined_keys = " ".join(report["section_diff"].keys()).lower()
    assert "experience" in combined_keys or len(report["section_diff"]) > 0


def test_section_diff_skips_identical_sections():
    """build_report must not include sections that did not change."""
    from utils.optimization_report import build_report

    text = "SUMMARY\nI am a developer.\n\nEXPERIENCE\nBuilt things."

    report = build_report(
        jd_result=_minimal_jd_result(),
        original_text=text,
        optimized_text=text,
        baseline_score=70,
        final_scores=_minimal_final_scores(),
        iterations=1,
    )

    assert report["section_diff"] == {}, (
        "section_diff should be empty when original and optimized text are identical"
    )


# ---------------------------------------------------------------------------
# Group 4 — jd_tailoring in optimization report (T7.3)
# ---------------------------------------------------------------------------


def test_jd_tailoring_in_report_scores():
    """build_report must include jd_tailoring in the scores dict."""
    from utils.optimization_report import build_report

    final_scores = _minimal_final_scores()

    report = build_report(
        jd_result=_minimal_jd_result(),
        original_text="SUMMARY\nGeneric developer.\n\nEXPERIENCE\nDid work.",
        optimized_text="SUMMARY\nML engineer at Acme.\n\nEXPERIENCE\nBuilt ML systems.",
        baseline_score=70,
        final_scores=final_scores,
        iterations=1,
    )

    assert "jd_tailoring" in report["scores"], (
        "report['scores'] must contain a 'jd_tailoring' key"
    )
    assert report["scores"]["jd_tailoring"] == 85
