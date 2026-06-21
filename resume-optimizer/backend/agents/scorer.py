"""
Resume Scorers
All 5 scores returned from a single LLM call via MODEL_SCORER.
  1. ATS Match     — keyword coverage (moved from local to LLM prompt)
  2. Impact Score  — quantified achievements, action verbs
  3. Skills Gap    — JD skills vs resume skills
  4. Readability   — structure, tone, formatting
  5. JD Tailoring  — summary specificity + bullet ordering for this role
"""

import hashlib
import logging
from typing import List, Optional
from llm import complete
from config import MODEL_SCORER, SCORE_DIMENSIONS
from utils.llm_json import parse_llm_json
from utils import cache as result_cache

_logger = logging.getLogger(__name__)


async def _llm_complete(
    prompt: str,
    system: str = None,
    response_format: dict = None,
    cached_prefix: str = None,
) -> tuple:
    # If cached_prefix is set, the rubric is sent as a cached prefix block —
    # do NOT concatenate it into the main prompt to avoid duplication.
    if cached_prefix:
        full_prompt = prompt
    else:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
    response = await complete(full_prompt, MODEL_SCORER, response_format=response_format, cached_prefix=cached_prefix)
    cost_usd = response.get("cost_usd", 0.0)
    input_tokens = response.get("input_tokens", 0)
    output_tokens = response.get("output_tokens", 0)
    raw = response["text"]
    try:
        return parse_llm_json(raw), cost_usd, input_tokens, output_tokens
    except ValueError:
        _logger.error("scorer JSON parse failed — retrying once. raw (first 500): %s", raw[:500])
        response2 = await complete(full_prompt, MODEL_SCORER, response_format=response_format, cached_prefix=cached_prefix)
        try:
            parsed2 = parse_llm_json(response2["text"])
        except ValueError:
            _logger.error("scorer JSON parse failed twice — degrading to empty result (safe defaults)")
            parsed2 = {}
        return parsed2, response2.get("cost_usd", 0.0), response2.get("input_tokens", 0), response2.get("output_tokens", 0)


def _normalize_scores(result: dict) -> dict:
    """Guarantee every scoring dimension is a dict with an int score in [0, 100], so
    downstream aggregation never KeyErrors on a schema-non-conforming response."""
    if not isinstance(result, dict):
        result = {}
    for section in SCORE_DIMENSIONS:
        sec = result.get(section)
        if not isinstance(sec, dict):
            sec = {}
            result[section] = sec
        score = sec.get("score", 0)
        sec["score"] = max(0, min(100, score)) if isinstance(score, (int, float)) else 0
    overall = result.get("overall", 0)
    result["overall"] = max(0, min(100, overall)) if isinstance(overall, (int, float)) else 0
    return result


# ── All 5 scores in one LLM call ─────────────────────────────────────────────

async def score_combined(
    resume_text: str,
    jd_text: str,
    jd_keywords: Optional[List[str]] = None,
    seniority_level: str = "mid",
    required_hard_skills: Optional[List[str]] = None,
) -> dict:
    """Return structured scoring across 5 dimensions with calibration rubric."""
    # Result cache: key over EVERY input that feeds the scoring prompt, so two runs that
    # differ only in jd_keywords or required_hard_skills don't collide on a stale score.
    _kw_part  = "|".join(sorted(jd_keywords or []))
    _req_part = "|".join(sorted(required_hard_skills or []))
    cache_key = hashlib.sha256(
        f"{resume_text}||{jd_text}||{seniority_level}||{_kw_part}||{_req_part}".encode()
    ).hexdigest()
    cached = result_cache.get("score_combined", cache_key)
    if cached is not None:
        return {"text": cached, "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

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

JD Tailoring (0-100):
  90-100 = Summary explicitly mentions the domain, target role, and key focus from the JD; most JD-relevant bullets are at the TOP of each experience section (highest keyword density first)
  70-89  = Summary references the role/domain but is somewhat generic; bullet ordering is mostly relevant-first
  40-60  = Summary is generic/boilerplate not written for THIS specific role; bullet ordering is random
  <40    = Summary is completely generic; bullets are in reverse-chronological or random order with no JD alignment

Seniority context: {seniority_note}
{required_block}

Return ONLY a raw JSON object — no markdown, no code fences, no prose before or after.
Use EXACTLY these top-level keys: "ats", "impact", "skills_gap", "readability", "jd_tailoring", "overall".

Required JSON shape:
{{
  "ats": {{"score": <int 0-100>, "missing_keywords": [...], "matched_keywords": [...], "keyword_coverage_pct": <float>}},
  "impact": {{"score": <int 0-100>, "weak_bullets": [...], "strong_bullets": [...], "has_quantified_achievements": <bool>}},
  "skills_gap": {{"score": <int 0-100>, "missing_skills": [...], "matched_skills": [...], "critical_missing": [...]}},
  "readability": {{"score": <int 0-100>, "issues": [...], "worst_section": "<string>", "has_summary": <bool>, "tense_consistent": <bool>}},
  "jd_tailoring": {{"score": <int 0-100>, "issues": [...], "summary_generic": <bool>}},
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
            "jd_tailoring": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "issues": {"type": "array", "items": {"type": "string"}},
                    "summary_generic": {"type": "boolean"},
                },
                "required": ["score", "issues", "summary_generic"],
            },
            "overall": {"type": "integer"},
        },
        "required": ["ats", "impact", "skills_gap", "readability", "jd_tailoring", "overall"],
    }

    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "resume_scores", "schema": schema, "strict": True},
    }

    result, cost_usd, input_tokens, output_tokens = await _llm_complete(
        prompt, system=None, response_format=response_format, cached_prefix=system
    )

    # Guarantee shape + clamp scores to [0, 100] so every caller can subscript safely.
    result = _normalize_scores(result)

    # If schema-valid but all sub-scores are 0 — retry once, then accept.
    if all(result[s]["score"] == 0 for s in SCORE_DIMENSIONS):
        _logger.warning("scorer returned all-zero scores — retrying once")
        result, cost_usd, input_tokens, output_tokens = await _llm_complete(
            prompt, system=None, response_format=response_format, cached_prefix=system
        )
        result = _normalize_scores(result)

    result_cache.set("score_combined", cache_key, value=result)
    return {
        "text": result,
        "tokens": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "cost_usd": cost_usd,
    }
