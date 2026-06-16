"""Tests for scorer calibration rubric and extended fields."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_scorer_returns_extended_fields(monkeypatch):
    """score_combined must return keyword_coverage_pct, worst_section, critical_missing."""
    from agents.scorer import score_combined

    fake_response = {
        "ats": {
            "score": 82,
            "missing_keywords": ["kubernetes", "terraform"],
            "matched_keywords": ["python", "docker"],
            "keyword_coverage_pct": 67.0,
        },
        "impact": {
            "score": 71,
            "weak_bullets": ["Helped with stuff"],
            "strong_bullets": ["Reduced latency by 40%"],
            "has_quantified_achievements": True,
        },
        "skills_gap": {
            "score": 78,
            "missing_skills": ["Go", "Rust"],
            "matched_skills": ["Python", "SQL"],
            "critical_missing": ["kubernetes"],
        },
        "readability": {
            "score": 85,
            "issues": [],
            "worst_section": "skills",
            "has_summary": True,
            "tense_consistent": True,
        },
        "overall": 79,
    }

    async def mock_complete(prompt, system=None, **kwargs):
        # real _llm_complete returns (parsed_dict, cost_usd, input_tokens, output_tokens)
        return fake_response, 0.0, 100, 50

    monkeypatch.setattr("agents.scorer._llm_complete", mock_complete)

    result = await score_combined(
        resume_text="Software engineer with Python experience",
        jd_text="Looking for Python/K8s engineer",
        seniority_level="senior",
        required_hard_skills=["kubernetes"],
    )
    scores = result["text"]
    assert "keyword_coverage_pct" in scores["ats"]
    assert "worst_section" in scores["readability"]
    assert "critical_missing" in scores["skills_gap"]
    assert "strong_bullets" in scores["impact"]
    assert "has_summary" in scores["readability"]
    assert "tense_consistent" in scores["readability"]


def test_scorer_no_max_3_in_prompt():
    """Scorer source must not contain a 'Max 3 items' cap."""
    import inspect
    from agents import scorer
    source = inspect.getsource(scorer)
    assert "Max 3" not in source, "Remove 'Max 3 items' cap from scorer prompt"


@pytest.mark.asyncio
async def test_scorer_passes_response_format():
    """score_combined must pass response_format to complete()."""
    from agents import scorer

    payload = ('{"ats":{"score":80,"missing_keywords":[],"matched_keywords":[],"keyword_coverage_pct":0.0},'
               '"impact":{"score":75,"weak_bullets":[],"strong_bullets":[],"has_quantified_achievements":true},'
               '"skills_gap":{"score":70,"missing_skills":[],"matched_skills":[],"critical_missing":[]},'
               '"readability":{"score":85,"issues":[],"worst_section":"experience","has_summary":true,"tense_consistent":true},'
               '"overall":78}')

    async def fake(prompt, model, **kw):
        fake.kw = kw
        return {"text": payload, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    with patch.object(scorer, "complete", new=fake):
        out = await scorer.score_combined("résumé", "jd")

    assert "response_format" in fake.kw
    assert out["text"]["ats"]["score"] == 80
