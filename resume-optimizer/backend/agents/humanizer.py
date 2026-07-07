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

    industry_note = f" Write in the voice of a credible {industry} professional." if industry else ""
    seniority_note = {
        "entry":  " Tone should be eager, growth-focused.",
        "mid":    " Tone should be confident and results-oriented.",
        "senior": " Tone should be authoritative, strategic, outcome-driven.",
        "lead":   " Tone should be visionary, org-level impact, team multiplier.",
    }.get(seniority_level, "")

    step1_system = f"""You are a professional resume writer.{industry_note}{seniority_note}

Improve the resume text on exactly THREE dimensions:
1. Voice variety — vary sentence openings; avoid starting consecutive bullets with the same verb
2. Confident assertions — replace hedges ("helped with", "assisted in", "worked on") with direct ownership ("led", "built", "delivered", "owned")
3. Industry tone — use vocabulary natural to the target industry; avoid generic filler phrases

Preserve every metric, company name, job title, and date exactly as written — never invent,
inflate, or alter a number, and never insert a placeholder like "[XX%]".
Plain text ONLY: no markdown and NO LaTeX or "$" math wrappers. Write figures plainly
("100M+ events/day", "$500K") — never "$(100M+events/day$".
Return ONLY the improved resume text. No commentary."""

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

    step2_system = f"""You are a senior hiring manager reviewing a resume for a {seniority_level}-level {industry or "technology"} role.

Critique the revised resume below. Be specific: quote the exact phrases that still feel weak, robotic, or generic.
State what should be different and why. Include every issue you find — no limit on feedback items."""

    # ── Step 2: Critic ───────────────────────────────────────────────────────
    response = await complete(f"""{step2_system}

Review this resume and return ONLY a JSON object with issues.
No explanation, no markdown.
Example: {{"robotic_phrases": ["responsible for"], "weak_bullets": ["helped team"], "improvements": ["add metrics"]}}

Resume:
{humanized_v1}

JSON:""", MODEL_CRITIC)
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
        feedback_lines.append(f"- Replace robotic phrases: {', '.join(feedback['robotic_phrases'][:3])}")
    if feedback.get("weak_bullets"):
        feedback_lines.append(f"- Strengthen weak bullets: {'; '.join(feedback['weak_bullets'][:3])}")
    if feedback.get("improvements"):
        feedback_lines.append(f"- Apply improvements: {'; '.join(feedback['improvements'][:3])}")

    if not feedback_lines:
        return {
            "text": humanized_v1,
            "tokens": accumulated,
            "cost_usd": accumulated["cost_usd"],
        }

    response = await complete(f"""Apply the following critic feedback to this resume.

Feedback:
{chr(10).join(feedback_lines)}

Resume:
\"\"\"
{humanized_v1}
\"\"\"

- Address every piece of feedback
- Do NOT change names, dates, companies, or metrics
- Do NOT add new metrics, numbers, achievements, or facts that aren't already in the resume
- Do NOT invent placeholder metrics like "[XX%]" or absolute claims like "100% reliability"
- Keep plain-text structure
Return ONLY the final resume text.""", MODEL_HUMANIZER)
    final_text = response["text"]
    accumulated["input_tokens"] += response.get("input_tokens", 0)
    accumulated["output_tokens"] += response.get("output_tokens", 0)
    accumulated["cost_usd"] += response.get("cost_usd", 0.0)

    return {
        "text": final_text,
        "tokens": accumulated,
        "cost_usd": accumulated["cost_usd"],
    }
