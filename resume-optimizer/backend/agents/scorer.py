"""
Resume Scorers
  1. ATS Match  — pure Python, zero API calls
  2-4. Impact + Skills Gap + Readability — single combined call via MODEL_SCORER
"""

import json
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from llm import complete
from config import MODEL_SCORER
from utils import cache as result_cache

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    raise RuntimeError(
        "spaCy model 'en_core_web_sm' not found. "
        "Run: python -m spacy download en_core_web_sm"
    )


def _clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


# ── SCORER 1: ATS Match (pure Python) ───────────────────────────────────────

def score_ats(resume_text: str, jd_text: str, jd_keywords: list) -> dict:
    doc = nlp(jd_text)
    spacy_keywords = [chunk.text.lower() for chunk in doc.noun_chunks]
    spacy_keywords += [
        token.text.lower()
        for token in doc
        if token.pos_ in ("NOUN", "PROPN") and not token.is_stop
    ]
    try:
        tfidf = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", max_features=30)
        tfidf.fit([jd_text])
        tfidf_keywords = list(tfidf.get_feature_names_out())
    except Exception:
        tfidf_keywords = []

    all_keywords = list(dict.fromkeys(
        spacy_keywords + tfidf_keywords + [k.lower() for k in jd_keywords]
    ))
    all_keywords = [k for k in all_keywords if len(k) > 2]
    resume_lower = resume_text.lower()
    matched = [k for k in all_keywords if k in resume_lower]
    missing = [k for k in all_keywords if k not in resume_lower]
    score = round((len(matched) / len(all_keywords)) * 100) if all_keywords else 0
    return {"score": score, "missing_keywords": missing[:20], "matched_keywords": matched[:20]}


# ── SCORERS 2-4: Combined single LLM call ────────────────────────────────────

async def score_combined(resume_text: str, jd_text: str) -> dict:
    cached = result_cache.get("combined", resume_text, jd_text)
    if cached is not None:
        return cached

    prompt = f"""You are a professional resume evaluator. Score this resume on 3 dimensions.

Job Description:
{jd_text}

Resume:
{resume_text}

Return ONLY a valid JSON object. No explanation, no markdown. Max 3 items per list.
Example:
{{
  "impact": {{"score": 74, "weak_bullets": ["responsible for reports"], "suggestions": ["add metrics"]}},
  "skills_gap": {{"score": 68, "missing_skills": ["docker"], "matched_skills": ["python"]}},
  "readability": {{"score": 82, "issues": ["missing summary"], "strengths": ["clear sections"]}}
}}

Scoring criteria:
- impact (0-100): quantified achievements, strong action verbs, measurable outcomes
- skills_gap (0-100): required JD skills vs skills demonstrated in resume
- readability (0-100): section completeness, formatting consistency, professional tone

JSON:"""

    raw = await complete(prompt, MODEL_SCORER, max_tokens=1024)

    try:
        data = json.loads(_clean_json(raw))
        for key, defaults in [
            ("impact",      {"weak_bullets": [], "suggestions": []}),
            ("skills_gap",  {"missing_skills": [], "matched_skills": []}),
            ("readability", {"issues": [], "strengths": []}),
        ]:
            if key not in data:
                data[key] = {"score": 50, **defaults}
            data[key]["score"] = max(0, min(100, int(data[key].get("score", 50))))
            for field, default in defaults.items():
                data[key].setdefault(field, default)
    except (json.JSONDecodeError, ValueError, TypeError):
        data = {
            "impact":      {"score": 50, "weak_bullets": [], "suggestions": []},
            "skills_gap":  {"score": 50, "missing_skills": [], "matched_skills": []},
            "readability": {"score": 50, "issues": [], "strengths": []},
        }

    result_cache.set("combined", resume_text, jd_text, value=data)
    return data


async def score_impact(resume_text: str, jd_text: str = "", _combined: dict = None) -> dict:
    combined = _combined or await score_combined(resume_text, jd_text)
    return combined["impact"]


async def score_skills_gap(resume_text: str, jd_text: str, _combined: dict = None) -> dict:
    combined = _combined or await score_combined(resume_text, jd_text)
    return combined["skills_gap"]


async def score_readability(resume_text: str, jd_text: str = "", _combined: dict = None) -> dict:
    combined = _combined or await score_combined(resume_text, jd_text)
    return combined["readability"]
