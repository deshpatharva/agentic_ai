"""
Resume Humanizer Agent
Step 1 — MODEL_HUMANIZER: polish language
Step 2 — MODEL_CRITIC: structured feedback (cheap model)
Step 3 — MODEL_HUMANIZER: incorporate feedback
"""

import json
from llm import complete
from config import MODEL_HUMANIZER, MODEL_CRITIC


def _clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


async def humanize_resume(
    resume_text: str,
    industry: str = "",
    seniority_level: str = "mid",
) -> dict:
    """
    Humanize resume text by polishing language, removing buzzwords, and improving readability.
    Optionally scoped to a target industry and seniority level for more focused output.
    Returns a dict with "text" (the humanized resume) and "tokens" (accumulated token counts).
    """
    accumulated = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    industry_note = f" Match the vocabulary a working {industry} professional would use." if industry else ""
    seniority_note = {
        "entry":  " Keep the tone clear and straightforward.",
        "mid":    " Keep the tone clear and professional.",
        "senior": " Keep the tone measured and professional.",
        "lead":   " Keep the tone measured and professional.",
    }.get(seniority_level, "")

    step1_system = f"""You are a resume line editor. Polish the wording so it reads cleanly and
professionally, WITHOUT changing what any line claims. You are editing language, not
strengthening the resume -- an earlier stage already handled content and keyword alignment.{industry_note}{seniority_note}

Do exactly these things:
1. Vary sentence and bullet openings so consecutive lines don't begin with the same word.
2. Fix grammar, keep tense consistent (past tense for past roles), and smooth awkward phrasing.
3. Cut filler and vague qualifiers ("responsible for", "various", "some", "helped to") by
   tightening the sentence -- not by upgrading what it claims.

Hard rules -- each line in your output must claim neither more nor less than the source:
- Keep every action at its original scope. If the source says "helped with", "assisted",
  "supported", or "was part of a team", KEEP that scope. Do NOT rewrite it as "led",
  "spearheaded", "orchestrated", "drove", "owned", "established", "transformed", or any verb
  that implies more ownership or initiative than the source states.
- Add NO outcome, result, or impact the source doesn't state -- nothing like "resulting in",
  "generating", "improving", "reducing", "increasing", or "enabling", and no implied numbers.
- Do NOT add any new skill, tool, technology, metric, or achievement.
- Do NOT change any metric, company name, date, job title, or seniority wording anywhere,
  including the summary; never insert a placeholder like "[XX%]".
- Keep the section structure and every bullet. Do NOT drop, merge, or collapse bullets into
  paragraphs.

Plain text ONLY: no markdown and NO LaTeX or "$" math wrappers. Write figures plainly
("100M+ events/day", "$500K") -- never "$(100M+events/day$".
Return ONLY the edited resume text. No commentary."""

    # ── Step 1: Humanize ─────────────────────────────────────────────────────
    response = await complete(f"""{step1_system}

Resume:
\"\"\"
{resume_text}
\"\"\"

Return ONLY the polished resume text.""", MODEL_HUMANIZER)
    humanized_v1 = response["text"]
    accumulated["input_tokens"] += response.get("input_tokens", 0)
    accumulated["output_tokens"] += response.get("output_tokens", 0)
    accumulated["cost_usd"] += response.get("cost_usd", 0.0)

    step2_system = f"""You are a copy editor reviewing a {seniority_level}-level {industry or "technology"} resume.
Look ONLY for language and readability problems -- NOT for weak content to strengthen. Do NOT
suggest adding skills, metrics, outcomes, or stronger/more-senior verbs; that would misrepresent
the candidate. Flag only: cliche or robotic phrasing, consecutive bullets that open with the
same word, and wordy or redundant phrasing."""

    # ── Step 2: Critic ───────────────────────────────────────────────────────
    response = await complete(f"""{step2_system}

Return ONLY a JSON object, no markdown, with any of these keys (omit a key with no items):
  "robotic_phrases": exact cliche/robotic phrases that should be reworded,
  "repetitive_openings": opening words repeated across consecutive bullets,
  "wordy_phrases": exact wordy or redundant phrases that should be tightened.
Example: {{"robotic_phrases": ["responsible for"], "wordy_phrases": ["in order to"]}}

Resume:
{humanized_v1}

JSON:""", MODEL_CRITIC, response_format={"type": "json_object"})
    raw_critic = response["text"]
    accumulated["input_tokens"] += response.get("input_tokens", 0)
    accumulated["output_tokens"] += response.get("output_tokens", 0)
    accumulated["cost_usd"] += response.get("cost_usd", 0.0)

    try:
        feedback = json.loads(_clean_json(raw_critic))
    except (json.JSONDecodeError, ValueError):
        return {
            "text": humanized_v1,
            "tokens": accumulated,
            "cost_usd": accumulated["cost_usd"],
        }

    # ── Step 3: Incorporate feedback ─────────────────────────────────────────
    feedback_lines = []
    if feedback.get("robotic_phrases"):
        feedback_lines.append(f"- Reword these cliche/robotic phrases: {', '.join(map(str, feedback['robotic_phrases'][:4]))}")
    if feedback.get("repetitive_openings"):
        feedback_lines.append(f"- Vary bullets that repeat these opening words: {', '.join(map(str, feedback['repetitive_openings'][:4]))}")
    if feedback.get("wordy_phrases"):
        feedback_lines.append(f"- Tighten these wordy phrases: {', '.join(map(str, feedback['wordy_phrases'][:4]))}")

    if not feedback_lines:
        return {
            "text": humanized_v1,
            "tokens": accumulated,
            "cost_usd": accumulated["cost_usd"],
        }

    response = await complete(f"""Apply these copy-edits to the resume. They are wording fixes only.

Edits:
{chr(10).join(feedback_lines)}

Resume:
\"\"\"
{humanized_v1}
\"\"\"

Rules -- do NOT change what any line claims:
- Fix only the wording flagged above. Keep every claim at its original scope and strength.
- Do NOT upgrade verbs -- no "led", "spearheaded", "drove", "owned", or "transformed" in place
  of "helped", "assisted", or "supported".
- Add NO outcome, result, metric, skill, tool, or achievement the source doesn't state.
- Do NOT change names, dates, companies, job titles, or seniority wording; no placeholders like "[XX%]".
- Keep every bullet and the section structure -- do NOT drop, merge, or collapse bullets.
Return ONLY the final resume text. No commentary.""", MODEL_HUMANIZER)
    final_text = response["text"]
    accumulated["input_tokens"] += response.get("input_tokens", 0)
    accumulated["output_tokens"] += response.get("output_tokens", 0)
    accumulated["cost_usd"] += response.get("cost_usd", 0.0)

    return {
        "text": final_text,
        "tokens": accumulated,
        "cost_usd": accumulated["cost_usd"],
    }
