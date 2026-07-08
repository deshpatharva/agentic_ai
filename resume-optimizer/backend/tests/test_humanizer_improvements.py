"""Tests for humanizer prompt improvements."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


def test_humanizer_accepts_industry_and_seniority_params():
    """humanize_resume must accept industry and seniority_level keyword args."""
    import inspect
    from agents.humanizer import humanize_resume
    sig = inspect.signature(humanize_resume)
    assert "industry" in sig.parameters, \
        "humanize_resume must accept 'industry' parameter"
    assert "seniority_level" in sig.parameters, \
        "humanize_resume must accept 'seniority_level' parameter"


def test_humanizer_has_three_objectives_not_seven():
    """Humanizer Step 1 prompt must NOT contain '7.' (old 7-objective list)."""
    import inspect
    from agents import humanizer as hum_module
    source = inspect.getsource(hum_module)
    assert "7." not in source, \
        "Humanizer still has 7 objectives — reduce to 3 focused objectives"


def test_humanizer_no_max_3_cap_in_critic():
    """Humanizer critic prompt must not contain 'max 3' or 'Max 3' cap."""
    import inspect
    from agents import humanizer as hum_module
    source = inspect.getsource(hum_module)
    assert "max 3" not in source.lower() or "max_iter" in source, \
        "Humanizer critic still has 'max 3' items cap — remove it"


async def test_humanizer_prompts_are_readability_only_no_inflation(monkeypatch):
    """The humanizer must polish language WITHOUT strengthening claims. Live QA on
    real models showed the old 'replace hedges with direct ownership' framing drove
    scope inflation ('assisted' -> 'spearheaded') and invented outcomes; the prompts
    are now scoped to readability only. Guards against a regression to that framing."""
    import agents.humanizer as humanizer

    prompts, kwargs_seen = [], []

    async def fake_complete(prompt, model, **kw):
        prompts.append(prompt)
        kwargs_seen.append(kw)
        if len(prompts) == 2:  # critic step
            return {"text": '{"robotic_phrases": ["responsible for"]}',
                    "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}
        return {"text": "polished resume", "input_tokens": 1, "output_tokens": 1,
                "cost_usd": 0.0}

    monkeypatch.setattr(humanizer, "complete", fake_complete)
    await humanizer.humanize_resume("Some resume text.", industry="saas",
                                    seniority_level="mid")

    step1, critic, step3 = prompts[0], prompts[1], prompts[2]

    # Step 1: line-editor framing, forbids upgrading scope verbs and inventing outcomes,
    # preserves bullets, and does not reintroduce the old ownership-strengthening rule.
    assert "You are a resume line editor." in step1
    assert "editing language, not" in step1 and "strengthening the resume" in step1
    assert "spearheaded" in step1  # named in the forbidden-verb list
    assert "Add NO outcome, result, or impact the source doesn't state" in step1
    assert "Do NOT add any new skill, tool, technology, metric, or achievement" in step1
    assert "Do NOT drop, merge, or collapse bullets" in step1
    assert "direct ownership" not in step1  # the old inflation-driving instruction is gone

    # Step 2 critic: readability problems only, must not push strengthening.
    assert "Look ONLY for language and readability problems" in critic
    assert kwargs_seen[1].get("response_format") == {"type": "json_object"}

    # Step 3: applies edits without upgrading verbs or adding outcomes.
    assert "Do NOT upgrade verbs" in step3
    assert "Add NO outcome, result, metric, skill, tool, or achievement" in step3
