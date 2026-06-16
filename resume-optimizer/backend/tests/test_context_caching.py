"""Tests for T3.1: context caching (cached_prefix) and result caching in scorer."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest
from unittest.mock import AsyncMock, patch, call


# ---------------------------------------------------------------------------
# Shared fake LLM response payload
# ---------------------------------------------------------------------------

_FAKE_PAYLOAD = (
    '{"ats":{"score":80,"missing_keywords":[],"matched_keywords":[],"keyword_coverage_pct":80.0},'
    '"impact":{"score":75,"weak_bullets":[],"strong_bullets":[],"has_quantified_achievements":true},'
    '"skills_gap":{"score":70,"missing_skills":[],"matched_skills":[],"critical_missing":[]},'
    '"readability":{"score":85,"issues":[],"worst_section":"experience","has_summary":true,"tense_consistent":true},'
    '"overall":78}'
)

_FAKE_RESPONSE = {
    "text": _FAKE_PAYLOAD,
    "input_tokens": 100,
    "output_tokens": 50,
    "cost_usd": 0.001,
}


# ---------------------------------------------------------------------------
# Test 1: scorer passes cached_prefix (the rubric) to complete()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scorer_passes_cached_prefix():
    """score_combined must call complete() with cached_prefix set to the rubric text."""
    from agents import scorer
    from utils import cache as result_cache

    result_cache.clear()

    async def fake_complete(prompt, model, cached_prefix=None, response_format=None):
        fake_complete.last_cached_prefix = cached_prefix
        return _FAKE_RESPONSE

    with patch.object(scorer, "complete", new=fake_complete):
        await scorer.score_combined(
            resume_text="Software engineer with 5 years Python experience",
            jd_text="Looking for senior Python developer",
            seniority_level="senior",
        )

    assert fake_complete.last_cached_prefix is not None, "cached_prefix must not be None"
    assert len(fake_complete.last_cached_prefix) > 0, "cached_prefix must not be empty"
    # The rubric should contain key scoring terms
    assert "ATS" in fake_complete.last_cached_prefix or "rubric" in fake_complete.last_cached_prefix.lower() or "score" in fake_complete.last_cached_prefix.lower()


# ---------------------------------------------------------------------------
# Test 2: result cache hit returns 0 tokens on second call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_combined_result_cache_hit_returns_zero_tokens():
    """Second call with identical inputs must return input_tokens=0, output_tokens=0 (cache hit)."""
    from agents import scorer
    from utils import cache as result_cache

    result_cache.clear()

    call_count = 0

    async def fake_complete(prompt, model, cached_prefix=None, response_format=None):
        nonlocal call_count
        call_count += 1
        return _FAKE_RESPONSE

    resume = "Experienced engineer with Python and Go skills"
    jd = "Seeking Python/Go backend developer"

    with patch.object(scorer, "complete", new=fake_complete):
        result1 = await scorer.score_combined(resume_text=resume, jd_text=jd, seniority_level="mid")
        result2 = await scorer.score_combined(resume_text=resume, jd_text=jd, seniority_level="mid")

    # First call should hit the LLM; second should be a cache hit
    assert call_count == 1, f"Expected 1 LLM call, got {call_count} (second call should be cached)"

    # Cache hit must return zero tokens
    assert result2["tokens"]["input_tokens"] == 0, "Cache hit must return input_tokens=0"
    assert result2["tokens"]["output_tokens"] == 0, "Cache hit must return output_tokens=0"
    assert result2["cost_usd"] == 0.0, "Cache hit must return cost_usd=0.0"

    # But the result data itself must still be present
    assert result2["text"] is not None
    assert result2["text"]["overall"] == 78


# ---------------------------------------------------------------------------
# Test 3: different resumes = different cache keys = LLM called twice
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_combined_result_cache_different_resume_calls_llm():
    """Calls with different resume texts must each hit the LLM (different cache keys)."""
    from agents import scorer
    from utils import cache as result_cache

    result_cache.clear()

    call_count = 0

    async def fake_complete(prompt, model, cached_prefix=None, response_format=None):
        nonlocal call_count
        call_count += 1
        return _FAKE_RESPONSE

    resume_a = "Resume A: Data scientist specializing in ML and Python"
    resume_b = "Resume B: Frontend developer with React and TypeScript"
    jd = "Seeking full-stack developer"

    with patch.object(scorer, "complete", new=fake_complete):
        await scorer.score_combined(resume_text=resume_a, jd_text=jd, seniority_level="mid")
        await scorer.score_combined(resume_text=resume_b, jd_text=jd, seniority_level="mid")

    assert call_count == 2, (
        f"Expected 2 LLM calls (one per unique resume), got {call_count}"
    )


# ---------------------------------------------------------------------------
# Note: Part C (humanizer cached_prefix) was NOT implemented.
# Reason: In humanizer.py, the stable text (step1_system instructions) is
# only ~80 tokens — well below any useful caching threshold. The large input
# (resume_text) is the VARIABLE part, not a stable prefix. Step 2 and Step 3
# both use humanized_v1 which changes every run. No call pattern lends itself
# to prefix caching, so test_humanizer_passes_cached_prefix is omitted.
# ---------------------------------------------------------------------------
