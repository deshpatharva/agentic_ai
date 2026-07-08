"""
JD Analyzer Agent
Extracts structured metadata from a job description using an LLM
(configured via MODEL_JD_ANALYZER in config.py).

Returns a rich schema with required vs preferred skills, seniority level,
industry, tech stack, and ATS-critical keywords.
"""

from llm import complete
from config import MODEL_JD_ANALYZER
from utils import cache as result_cache
from utils.llm_json import parse_llm_json


async def _llm_complete(prompt: str, system: str = None, response_format: dict = None) -> tuple:
    """
    Thin wrapper around llm.complete that accepts system/response_format kwargs.
    Returns (parsed_dict, cost_usd, input_tokens, output_tokens).
    """
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    response = await complete(full_prompt, MODEL_JD_ANALYZER, response_format=response_format)
    cost_usd = response.get("cost_usd", 0.0)
    input_tokens = response.get("input_tokens", 0)
    output_tokens = response.get("output_tokens", 0)
    raw = response["text"]
    try:
        return parse_llm_json(raw), cost_usd, input_tokens, output_tokens
    except ValueError:
        import logging
        logging.getLogger(__name__).error(
            "jd_analyzer JSON parse failed — retrying once. raw (first 500): %s", raw[:500]
        )
        response2 = await complete(full_prompt, MODEL_JD_ANALYZER, response_format=response_format)
        parsed2 = parse_llm_json(response2["text"])
        return parsed2, response2.get("cost_usd", 0.0), response2.get("input_tokens", 0), response2.get("output_tokens", 0)


async def analyze_jd(jd_text: str) -> dict:
    """Extract structured metadata from a job description."""
    cached = result_cache.get("jd_analysis", jd_text)
    if cached is not None:
        return {"text": cached, "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

    system = """You are an expert technical recruiter. Extract structured data from job descriptions.

job_title: the concise ROLE TITLE only (e.g. "Senior Data Engineer", "Backend Software Engineer").
2-5 words. NOT a requirement sentence, NOT "5+ years of experience", NOT the company name.
If no explicit title, infer the most likely role from the responsibilities.

Seniority levels: entry (0-2 yrs), mid (3-6 yrs), senior (7+ yrs), lead (10+ yrs, manages teams).
Industry examples: fintech, healthtech, e-commerce, saas, gaming, enterprise-software, consulting.

Distinguish required vs preferred:
- required_hard_skills: explicitly required technical skills ("must have", "required", "X+ years of")
- preferred_soft_skills: "nice to have", "preferred", or behavioural traits
- critical_keywords: 3-8 ATS-critical terms that MUST appear on a resume to pass screening
required_hard_skills entries must be 1-3 word technologies or competencies, not
requirement sentences ("Kubernetes", not "5+ years of Kubernetes experience").

Return ONLY valid JSON. No prose."""

    prompt = f"""Extract structured metadata from this job description:

{jd_text[:4000]}

Return JSON with all fields. For seniority_level use: entry | mid | senior | lead."""

    schema = {
        "type": "object",
        "properties": {
            "job_title":               {"type": "string"},
            "required_hard_skills":    {"type": "array", "items": {"type": "string"}},
            "preferred_soft_skills":   {"type": "array", "items": {"type": "string"}},
            "critical_keywords":       {"type": "array", "items": {"type": "string"}},
            "tech_stack":              {"type": "array", "items": {"type": "string"}},
            "seniority_level":         {"type": "string", "enum": ["entry", "mid", "senior", "lead"]},
            "industry":                {"type": "string"},
            "required_certifications": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "job_title",
            "required_hard_skills", "preferred_soft_skills", "critical_keywords",
            "tech_stack", "seniority_level", "industry", "required_certifications",
        ],
    }

    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "jd_analysis", "schema": schema, "strict": True},
    }

    result, cost_usd, input_tokens, output_tokens = await _llm_complete(
        prompt, system=system, response_format=response_format
    )

    result.setdefault("job_title", "")
    result.setdefault("required_hard_skills", [])
    result.setdefault("preferred_soft_skills", [])
    result.setdefault("critical_keywords", [])
    result.setdefault("tech_stack", [])
    result.setdefault("seniority_level", "mid")
    result.setdefault("industry", "")
    result.setdefault("required_certifications", [])
    # Backward-compat alias consumed by main.py pipeline — derived from critical_keywords
    result.setdefault("keywords", result.get("critical_keywords", [])[:20])

    result_cache.set("jd_analysis", jd_text, value=result)
    return {
        "text": result,
        "tokens": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "cost_usd": cost_usd,
    }
