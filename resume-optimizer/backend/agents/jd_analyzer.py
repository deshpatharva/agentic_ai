"""
JD Analyzer Agent
Extracts structured metadata from a job description using an LLM
(configured via MODEL_JD_ANALYZER in config.py).

Returns a rich schema with required vs preferred skills, seniority level,
industry, tech stack, and ATS-critical keywords — plus legacy keys
(keywords, requirements, skills) for backward compatibility.
"""

from llm import complete
from config import MODEL_JD_ANALYZER
from utils import cache as result_cache
from utils.llm_json import parse_llm_json


async def _llm_complete(prompt: str, system: str = None, schema: dict = None) -> tuple:
    """
    Thin wrapper around llm.complete that accepts system/schema kwargs.
    Returns (parsed_dict, cost_usd, input_tokens, output_tokens).
    """
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    response = await complete(full_prompt, MODEL_JD_ANALYZER)
    cost_usd = response.get("cost_usd", 0.0)
    input_tokens = response.get("input_tokens", 0)
    output_tokens = response.get("output_tokens", 0)
    raw = response["text"]
    try:
        return parse_llm_json(raw), cost_usd, input_tokens, output_tokens
    except ValueError:
        return {}, cost_usd, input_tokens, output_tokens


async def analyze_jd(jd_text: str) -> dict:
    """Extract structured metadata from a job description."""
    cached = result_cache.get("jd_analysis", jd_text)
    if cached is not None:
        return {"text": cached, "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

    system = """You are an expert technical recruiter. Extract structured data from job descriptions.

Seniority levels: entry (0-2 yrs), mid (3-6 yrs), senior (7+ yrs), lead (10+ yrs, manages teams).
Industry examples: fintech, healthtech, e-commerce, saas, gaming, enterprise-software, consulting.

Distinguish required vs preferred:
- required_hard_skills: explicitly required technical skills ("must have", "required", "X+ years of")
- preferred_soft_skills: "nice to have", "preferred", or behavioural traits
- critical_keywords: 3-8 ATS-critical terms that MUST appear on a resume to pass screening

Return ONLY valid JSON. No prose."""

    prompt = f"""Extract structured metadata from this job description:

{jd_text[:4000]}

Return JSON with all fields. For seniority_level use: entry | mid | senior | lead."""

    schema = {
        "type": "object",
        "properties": {
            "required_hard_skills":    {"type": "array", "items": {"type": "string"}},
            "preferred_soft_skills":   {"type": "array", "items": {"type": "string"}},
            "critical_keywords":       {"type": "array", "items": {"type": "string"}},
            "tech_stack":              {"type": "array", "items": {"type": "string"}},
            "seniority_level":         {"type": "string", "enum": ["entry", "mid", "senior", "lead"]},
            "industry":                {"type": "string"},
            "required_certifications": {"type": "array", "items": {"type": "string"}},
            "keywords":                {"type": "array", "items": {"type": "string"}},
            "requirements":            {"type": "array", "items": {"type": "string"}},
            "skills":                  {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "required_hard_skills", "preferred_soft_skills", "critical_keywords",
            "tech_stack", "seniority_level", "industry", "required_certifications",
            "keywords", "requirements", "skills",
        ],
    }

    result, cost_usd, input_tokens, output_tokens = await _llm_complete(prompt, system=system, schema=schema)

    result.setdefault("required_hard_skills", [])
    result.setdefault("preferred_soft_skills", [])
    result.setdefault("critical_keywords", [])
    result.setdefault("tech_stack", [])
    result.setdefault("seniority_level", "mid")
    result.setdefault("industry", "")
    result.setdefault("required_certifications", [])
    result.setdefault("keywords", result.get("required_hard_skills", [])[:20])
    result.setdefault("requirements", [])
    result.setdefault("skills", result.get("required_hard_skills", []))

    result_cache.set("jd_analysis", jd_text, value=result)
    return {
        "text": result,
        "tokens": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "cost_usd": cost_usd,
    }
