"""Tests for JD analyzer structured schema."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


@pytest.mark.asyncio
async def test_jd_analyzer_returns_structured_schema(monkeypatch):
    """analyze_jd must return required_hard_skills, seniority_level, industry, tech_stack."""
    from agents.jd_analyzer import analyze_jd

    fake_response = {
        "required_hard_skills": ["Python", "Kubernetes"],
        "preferred_soft_skills": ["communication", "ownership"],
        "critical_keywords": ["distributed systems", "microservices"],
        "tech_stack": ["Python", "Go", "Kubernetes", "AWS"],
        "seniority_level": "senior",
        "industry": "fintech",
        "required_certifications": [],
        "keywords": ["python", "kubernetes", "aws"],
        "requirements": ["5+ years Python", "K8s experience"],
        "skills": ["Python", "Kubernetes"],
    }

    async def mock_complete(prompt, system=None, schema=None):
        # real _llm_complete returns (parsed_dict, cost_usd, input_tokens, output_tokens)
        return fake_response, 0.0, 100, 50

    monkeypatch.setattr("agents.jd_analyzer._llm_complete", mock_complete)

    result = await analyze_jd("Senior Python engineer at fintech, K8s required")
    payload = result["text"]
    assert "required_hard_skills" in payload
    assert "seniority_level" in payload
    assert "industry" in payload
    assert "tech_stack" in payload
    assert "preferred_soft_skills" in payload
    assert "critical_keywords" in payload
    assert payload["seniority_level"] in ("entry", "mid", "senior", "lead")
