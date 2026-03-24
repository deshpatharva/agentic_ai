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


async def humanize_resume(resume_text: str) -> str:

    # ── Step 1: Humanize ─────────────────────────────────────────────────────
    humanized_v1 = await complete(f"""You are an expert resume editor. Polish this resume so it:
1. Sounds natural and conversational — eliminate robotic or AI-sounding phrases
2. Removes hollow buzzwords (e.g., "dynamic", "synergize", "leverage" used gratuitously)
3. Uses varied sentence structures and strong action verbs
4. Maintains confident, professional tone
5. Preserves all factual content — do NOT change names, dates, companies, or metrics
6. Keeps plain-text structure (no markdown, no tables)
7. STRICT LENGTH LIMIT: Keep the resume within 2 pages (max 600 words). Do not add new content — only refine what exists.

Resume:
\"\"\"
{resume_text}
\"\"\"

Return ONLY the polished resume text.""", MODEL_HUMANIZER)

    # ── Step 2: Critic ───────────────────────────────────────────────────────
    raw_critic = await complete(f"""Review this resume and return ONLY a JSON object with issues.
No explanation, no markdown. Max 3 items per list.
Example: {{"robotic_phrases": ["responsible for"], "weak_bullets": ["helped team"], "improvements": ["add metrics"]}}

Resume:
{humanized_v1}

JSON:""", MODEL_CRITIC, max_tokens=1024)

    try:
        feedback = json.loads(_clean_json(raw_critic))
    except (json.JSONDecodeError, ValueError):
        return humanized_v1

    # ── Step 3: Incorporate feedback ─────────────────────────────────────────
    feedback_lines = []
    if feedback.get("robotic_phrases"):
        feedback_lines.append(f"- Replace robotic phrases: {', '.join(feedback['robotic_phrases'][:3])}")
    if feedback.get("weak_bullets"):
        feedback_lines.append(f"- Strengthen weak bullets: {'; '.join(feedback['weak_bullets'][:3])}")
    if feedback.get("improvements"):
        feedback_lines.append(f"- Apply improvements: {'; '.join(feedback['improvements'][:3])}")

    if not feedback_lines:
        return humanized_v1

    return await complete(f"""Apply the following critic feedback to this resume.

Feedback:
{chr(10).join(feedback_lines)}

Resume:
\"\"\"
{humanized_v1}
\"\"\"

- Address every piece of feedback
- Do NOT change names, dates, companies, or metrics
- Keep plain-text structure
Return ONLY the final resume text.""", MODEL_HUMANIZER)
