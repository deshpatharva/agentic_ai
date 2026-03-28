"""
Resume Scorers
All 4 scores returned from a single LLM call via MODEL_SCORER.
  1. ATS Match     — keyword coverage (moved from local to LLM prompt)
  2. Impact Score  — quantified achievements, action verbs
  3. Skills Gap    — JD skills vs resume skills
  4. Readability   — structure, tone, formatting
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


def _extract_jd_keywords(jd_text: str, jd_keywords: list) -> list:
    """Extract keywords from JD using spaCy + TF-IDF (used to build keyword list for ATS prompt)."""
    doc = nlp(jd_text)
    spacy_kw = [chunk.text.lower() for chunk in doc.noun_chunks]
    spacy_kw += [t.text.lower() for t in doc if t.pos_ in ("NOUN", "PROPN") and not t.is_stop]
    try:
        tfidf = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", max_features=30)
        tfidf.fit([jd_text])
        tfidf_kw = list(tfidf.get_feature_names_out())
    except Exception:
        tfidf_kw = []
    all_kw = list(dict.fromkeys(spacy_kw + tfidf_kw + [k.lower() for k in jd_keywords]))
    return [k for k in all_kw if len(k) > 2]


# ── All 4 scores in one LLM call ─────────────────────────────────────────────

async def score_combined(
    resume_text: str,
    jd_text: str,
    jd_keywords: list = None,
    gemini_cache_name: str = None,
) -> dict:
    cached = result_cache.get("combined", resume_text, jd_text)
    if cached is not None:
        return cached

    # Build keyword list for ATS scoring context
    kw_list = _extract_jd_keywords(jd_text, jd_keywords or [])
    keywords_str = ", ".join(kw_list[:50]) if kw_list else "see job description"

    if gemini_cache_name:
        # JD text is in the server-side cache — omit it from the prompt to save tokens
        jd_section = "Job Description: (see cached context above)"
    else:
        jd_section = f"Job Description:\n{jd_text}"

    prompt = f"""You are a professional resume evaluator. Score this resume on 4 dimensions against the job description.

{jd_section}

Extracted JD Keywords (for ATS scoring):
{keywords_str}

Resume:
{resume_text}

Return ONLY a valid JSON object. No explanation, no markdown. Max 3 items per list.
Example:
{{
  "ats": {{"score": 74, "missing_keywords": ["docker", "ci/cd"], "matched_keywords": ["python", "sql"]}},
  "impact": {{"score": 68, "weak_bullets": ["responsible for reports"], "suggestions": ["add metrics"]}},
  "skills_gap": {{"score": 72, "missing_skills": ["kubernetes"], "matched_skills": ["python"]}},
  "readability": {{"score": 85, "issues": ["missing summary"], "strengths": ["clear sections"]}}
}}

Scoring criteria:
- ats (0-100): how many of the extracted JD keywords appear in the resume (keyword coverage)
- impact (0-100): quantified achievements, strong action verbs, measurable outcomes
- skills_gap (0-100): required JD skills vs skills demonstrated in resume
- readability (0-100): section completeness, formatting consistency, professional tone

JSON:"""

    raw = await complete(prompt, MODEL_SCORER, max_tokens=1024, gemini_cache_name=gemini_cache_name)

    try:
        data = json.loads(_clean_json(raw))
        for key, defaults in [
            ("ats",         {"missing_keywords": [], "matched_keywords": []}),
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
            "ats":         {"score": 50, "missing_keywords": [], "matched_keywords": []},
            "impact":      {"score": 50, "weak_bullets": [], "suggestions": []},
            "skills_gap":  {"score": 50, "missing_skills": [], "matched_skills": []},
            "readability": {"score": 50, "issues": [], "strengths": []},
        }

    result_cache.set("combined", resume_text, jd_text, value=data)
    return data
