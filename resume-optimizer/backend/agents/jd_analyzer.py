"""
JD Analyzer Agent
Extracts keywords, requirements, and skills from a job description
using spaCy, TF-IDF, and an LLM (configured via MODEL_JD_ANALYZER in config.py).
"""

import json
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from llm import complete
from config import MODEL_JD_ANALYZER
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


async def analyze_jd(jd_text: str) -> dict:
    cached = result_cache.get("jd_analysis", jd_text)
    if cached is not None:
        return cached

    # ── spaCy + TF-IDF extraction ────────────────────────────────────────────
    doc = nlp(jd_text)
    spacy_keywords = [chunk.text.lower() for chunk in doc.noun_chunks]
    spacy_keywords += [
        token.text.lower()
        for token in doc
        if token.pos_ in ("NOUN", "PROPN") and not token.is_stop and len(token.text) > 2
    ]
    spacy_keywords = list(dict.fromkeys(spacy_keywords))

    tfidf_keywords = []
    try:
        tfidf = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", max_features=30)
        tfidf.fit([jd_text])
        tfidf_keywords = list(tfidf.get_feature_names_out())
    except Exception:
        pass

    merged_keywords = list(dict.fromkeys(spacy_keywords + tfidf_keywords))
    merged_keywords = [k for k in merged_keywords if len(k) > 2]

    # ── LLM extraction ───────────────────────────────────────────────────────
    prompt = f"""Extract structured information from this job description.
Return ONLY a valid JSON object. No explanation, no markdown.
Example: {{"keywords": ["python", "ml"], "requirements": ["3+ years"], "skills": ["pytorch"]}}
Max 20 keywords, 10 requirements, 10 skills.

Job Description:
{jd_text}

JSON:"""

    raw = await complete(prompt, MODEL_JD_ANALYZER)

    try:
        llm_data = json.loads(_clean_json(raw))
    except (json.JSONDecodeError, ValueError):
        llm_data = {"keywords": [], "requirements": [], "skills": []}

    all_keywords = list(dict.fromkeys(
        merged_keywords + [k.lower() for k in llm_data.get("keywords", [])]
    ))

    result = {
        "keywords": all_keywords[:50],
        "requirements": llm_data.get("requirements", []),
        "skills": llm_data.get("skills", []),
    }
    result_cache.set("jd_analysis", jd_text, value=result)
    return result
