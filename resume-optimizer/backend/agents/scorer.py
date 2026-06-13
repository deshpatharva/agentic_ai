"""
Resume Scorers
All 4 scores returned from a single LLM call via MODEL_SCORER.
  1. ATS Match     — keyword coverage (moved from local to LLM prompt)
  2. Impact Score  — quantified achievements, action verbs
  3. Skills Gap    — JD skills vs resume skills
  4. Readability   — structure, tone, formatting
"""

import logging
from typing import List, Optional
from llm import complete
from config import MODEL_SCORER
from utils.llm_json import parse_llm_json

_logger = logging.getLogger(__name__)


async def _llm_complete(prompt: str, system: str = None, schema: dict = None) -> tuple:
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    response = await complete(full_prompt, MODEL_SCORER)
    cost_usd = response.get("cost_usd", 0.0)
    input_tokens = response.get("input_tokens", 0)
    output_tokens = response.get("output_tokens", 0)
    raw = response["text"]
    try:
        return parse_llm_json(raw), cost_usd, input_tokens, output_tokens
    except ValueError:
        _logger.error("scorer JSON parse failed. raw response (first 500 chars): %s", raw[:500])
        return {}, cost_usd, input_tokens, output_tokens


# ── All 4 scores in one LLM call ─────────────────────────────────────────────

async def score_combined(
    resume_text: str,
    jd_text: str,
    jd_keywords: Optional[List[str]] = None,
    seniority_level: str = "mid",
    required_hard_skills: Optional[List[str]] = None,
) -> dict:
    """Return structured scoring across 4 dimensions with calibration rubric."""
    required_block = ""
    if required_hard_skills:
        required_block = (
            f"\nRequired hard skills for this role: {', '.join(required_hard_skills[:20])}."
            " If any of these are missing from the resume, they MUST appear in critical_missing."
        )

    seniority_map = {
        "entry":  "0-2 years experience expected; penalise missing summary heavily",
        "mid":    "3-6 years; expects quantified bullets and clear progression",
        "senior": "7+ years; expects leadership indicators, architecture mentions, metrics at scale",
        "lead":   "10+ years; expects team-building language, org-level impact",
    }
    seniority_note = seniority_map.get(seniority_level, seniority_map["mid"])

    system = f"""You are an expert ATS and resume evaluator. Score strictly using this rubric:

ATS score (0-100):
  90-100 = >90% of JD keywords present, all critical skills matched
  70-89  = 70-89% keyword match, minor gaps only
  50-69  = 50-69% match, several important keywords missing
  <50    = <50% match, fundamental misalignment

Impact score (0-100):
  90-100 = Every bullet has a metric (%, $, count, time-saved); strong action verbs
  70-89  = >70% bullets quantified; some passive voice
  50-69  = Mixed; many bullets describe duties not achievements
  <50    = Mostly duty-description, few/no metrics

Skills gap (0-100):
  90-100 = All required and preferred skills present
  70-89  = All required present, some preferred missing
  50-69  = 1-2 required skills missing
  <50    = Multiple required skills absent

Readability (0-100):
  90-100 = Consistent past tense, clear sections, concise bullets, strong summary
  70-89  = Minor inconsistencies; summary present but weak
  50-69  = Tense mixing, dense paragraphs, weak/missing summary
  <50    = Major formatting issues; no clear summary

Seniority context: {seniority_note}
{required_block}

Return ONLY a raw JSON object — no markdown, no code fences, no prose before or after.
Use EXACTLY these top-level keys: "ats", "impact", "skills_gap", "readability", "overall".

Required JSON shape:
{{
  "ats": {{"score": <int 0-100>, "missing_keywords": [...], "matched_keywords": [...], "keyword_coverage_pct": <float>}},
  "impact": {{"score": <int 0-100>, "weak_bullets": [...], "strong_bullets": [...], "has_quantified_achievements": <bool>}},
  "skills_gap": {{"score": <int 0-100>, "missing_skills": [...], "matched_skills": [...], "critical_missing": [...]}},
  "readability": {{"score": <int 0-100>, "issues": [...], "worst_section": "<string>", "has_summary": <bool>, "tense_consistent": <bool>}},
  "overall": <int 0-100>
}}"""

    kw_hint = f"\nKnown JD keywords: {', '.join(jd_keywords[:30])}" if jd_keywords else ""

    prompt = f"""Evaluate this resume against the job description.{kw_hint}

--- RESUME ---
{resume_text[:6000]}

--- JOB DESCRIPTION ---
{jd_text[:3000]}

Return the JSON object with ALL fields populated using the exact keys specified. No prose, no markdown."""

    schema = {
        "type": "object",
        "properties": {
            "ats": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "missing_keywords": {"type": "array", "items": {"type": "string"}},
                    "matched_keywords": {"type": "array", "items": {"type": "string"}},
                    "keyword_coverage_pct": {"type": "number"},
                },
                "required": ["score", "missing_keywords", "matched_keywords", "keyword_coverage_pct"],
            },
            "impact": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "weak_bullets": {"type": "array", "items": {"type": "string"}},
                    "strong_bullets": {"type": "array", "items": {"type": "string"}},
                    "has_quantified_achievements": {"type": "boolean"},
                },
                "required": ["score", "weak_bullets", "strong_bullets", "has_quantified_achievements"],
            },
            "skills_gap": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "missing_skills": {"type": "array", "items": {"type": "string"}},
                    "matched_skills": {"type": "array", "items": {"type": "string"}},
                    "critical_missing": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["score", "missing_skills", "matched_skills", "critical_missing"],
            },
            "readability": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "issues": {"type": "array", "items": {"type": "string"}},
                    "worst_section": {"type": "string"},
                    "has_summary": {"type": "boolean"},
                    "tense_consistent": {"type": "boolean"},
                },
                "required": ["score", "issues", "worst_section", "has_summary", "tense_consistent"],
            },
            "overall": {"type": "integer"},
        },
        "required": ["ats", "impact", "skills_gap", "readability", "overall"],
    }

    result, cost_usd, input_tokens, output_tokens = await _llm_complete(prompt, system=system, schema=schema)

    # Normalise common key aliases the LLM may use instead of the canonical names
    _aliases = {
        "ats": ("ats_score", "ats_match", "ats_keyword_score"),
        "impact": ("impact_score", "impact_analysis"),
        "skills_gap": ("skills", "skill_gap", "skills_gap_score", "skillsgap"),
        "readability": ("readability_score", "read_score"),
    }
    for canonical, alts in _aliases.items():
        if canonical not in result:
            for alt in alts:
                if alt in result:
                    result[canonical] = result.pop(alt)
                    break

    defaults = {
        "ats":         {"score": 0, "missing_keywords": [], "matched_keywords": [], "keyword_coverage_pct": 0.0},
        "impact":      {"score": 0, "weak_bullets": [], "strong_bullets": [], "has_quantified_achievements": False},
        "skills_gap":  {"score": 0, "missing_skills": [], "matched_skills": [], "critical_missing": []},
        "readability": {"score": 0, "issues": [], "worst_section": "experience", "has_summary": False, "tense_consistent": False},
    }
    for section, defs in defaults.items():
        # LLM sometimes returns flat integers instead of objects e.g. {"ats": 75, ...}
        if isinstance(result.get(section), (int, float)):
            result[section] = {"score": int(result[section])}
        result.setdefault(section, {})
        for key, val in defs.items():
            result[section].setdefault(key, val)
    result.setdefault("overall", 0)
    return {
        "text": result,
        "tokens": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "cost_usd": cost_usd,
    }
