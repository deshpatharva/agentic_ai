"""
Resume Rewriter Agent
"""

from typing import Optional

from llm import complete
from config import MODEL_REWRITER, MODEL_REWRITER_FAST
from agents.fact_extractor import ClaimsLedger


async def rewrite_resume(
    resume_text: str,
    jd_keywords: list[str],
    consolidated_feedback: Optional[str] = None,
    claims_ledger: Optional[ClaimsLedger] = None,
    seniority_level: str = "mid",
    industry: str = "",
) -> dict:
    """
    Rewrite resume to align with JD keywords and feedback.
    Returns a dict with "text" (the rewritten resume) and "tokens" (accumulated token counts).
    """
    accumulated = {"input_tokens": 0, "output_tokens": 0}
    keywords_str = ", ".join(jd_keywords[:40]) if jd_keywords else "None provided"

    input_word_count = len(resume_text.split())
    max_words = min(700, int(input_word_count * 1.2))

    industry_note = f" Tailor language for the {industry} industry." if industry else ""

    # Inject the claims ledger when available so the model knows which
    # numbers and organisations are real facts it may use.
    ledger_block = (
        f"\n{claims_ledger.prompt_block()}\n"
        if claims_ledger else ""
    )

    system = f"""You are an expert resume writer specializing in ATS optimization.{industry_note}

Rewrite the resume following THREE priorities in order:

PRIORITY 1 — KEYWORD SATURATION
  Weave all JD keywords naturally into bullets and summary.
  Every required keyword must appear at least once; critical keywords ideally 2-3 times.

PRIORITY 2 — QUANTIFIED IMPACT
  Every bullet must contain a metric (%, $, count, time). If a bullet has no metric, add a
  realistic placeholder using the format [XX%] that the user can fill in.
  Replace duty-description ("Responsible for X") with achievement framing ("Delivered X, resulting in Y").
  Use ONLY numbers and metrics that appear verbatim in the CLAIMS LEDGER below; do NOT invent new figures.

PRIORITY 3 — FLOW AND CONCISION
  Keep total length within {max_words} words (current: {input_word_count} words).
  Vary bullet openings — no two consecutive bullets may start with the same verb.
  Use consistent past tense throughout except for current role (present tense).
  Keep formatting clean: plain text, no tables or columns.

SELF-CHECK before returning: confirm all required keywords appear, all bullets have metrics,
and the word count is under {max_words}.

Preserve all company names, job titles, dates, and degrees exactly as written.
Do NOT add parenthetical qualifiers like "(Established Company)" after company names.
Return ONLY the rewritten resume text. No commentary, no fences."""

    prompt = f"""{system}
{ledger_block}
Job Description Keywords to incorporate:
{keywords_str}

Current Resume:
\"\"\"
{resume_text}
\"\"\"
"""

    if consolidated_feedback:
        prompt += f"\nCRITICAL — Fix ALL of the following issues:\n{consolidated_feedback}\n"

    model = MODEL_REWRITER_FAST if consolidated_feedback else MODEL_REWRITER
    response = await complete(prompt, model)
    final_text = response["text"]
    accumulated["input_tokens"] += response.get("input_tokens", 0)
    accumulated["output_tokens"] += response.get("output_tokens", 0)

    return {
        "text": final_text,
        "tokens": accumulated,
    }
