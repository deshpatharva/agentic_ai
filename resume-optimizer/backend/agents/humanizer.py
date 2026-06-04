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


async def humanize_resume(resume_text: str) -> dict:
    """
    Humanize resume text by polishing language, removing buzzwords, and improving readability.
    Returns a dict with "text" (the humanized resume) and "tokens" (accumulated token counts).
    """
    accumulated = {"input_tokens": 0, "output_tokens": 0}

    # ── Step 1: Humanize ─────────────────────────────────────────────────────
    response = await complete(f"""You are an expert resume editor. Polish this resume so it:
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
    humanized_v1 = response["text"]
    accumulated["input_tokens"] += response.get("input_tokens", 0)
    accumulated["output_tokens"] += response.get("output_tokens", 0)

    # ── Step 2: Critic ───────────────────────────────────────────────────────
    response = await complete(f"""Review this resume and return ONLY a JSON object with issues.
No explanation, no markdown. Max 3 items per list.
Example: {{"robotic_phrases": ["responsible for"], "weak_bullets": ["helped team"], "improvements": ["add metrics"]}}

Resume:
{humanized_v1}

JSON:""", MODEL_CRITIC, max_tokens=1024)
    raw_critic = response["text"]
    accumulated["input_tokens"] += response.get("input_tokens", 0)
    accumulated["output_tokens"] += response.get("output_tokens", 0)

    try:
        feedback = json.loads(_clean_json(raw_critic))
    except (json.JSONDecodeError, ValueError):
        return {
            "text": humanized_v1,
            "tokens": accumulated,
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
- Keep plain-text structure
Return ONLY the final resume text.""", MODEL_HUMANIZER)
    final_text = response["text"]
    accumulated["input_tokens"] += response.get("input_tokens", 0)
    accumulated["output_tokens"] += response.get("output_tokens", 0)

    return {
        "text": final_text,
        "tokens": accumulated,
    }


# ── CrewAI Agent Integration ────────────────────────────────────────────────
from crewai import tool
from agents.base import create_agent


@tool
def humanize_tool(resume_text: str) -> dict:
    """
    Polish resume language to sound natural and human.
    Returns dict with humanized_resume.
    """
    # Call existing humanize_resume function
    import asyncio
    result = asyncio.run(humanize_resume(resume_text))
    return result


def create_humanizer_agent():
    """Create the Humanizer CrewAI Agent."""
    return create_agent(
        role="Resume Humanizer",
        goal="Polish language to sound natural and human, not AI-generated",
        backstory=(
            "You are a master of natural language and tone. "
            "You remove buzzwords, make resumes conversational, and ensure authenticity."
        ),
        tools=[humanize_tool],
    )
