"""
Resume Rewriter Agent
"""

from llm import complete
from config import MODEL_REWRITER, MODEL_REWRITER_FAST


async def rewrite_resume(
    resume_text: str,
    jd_keywords: list,
    consolidated_feedback: dict = None,
) -> str:
    keywords_str = ", ".join(jd_keywords[:40]) if jd_keywords else "None provided"

    prompt = f"""You are an expert resume writer and career coach specializing in ATS optimization.

Rewrite the following resume to strongly align with the job description keywords provided.

Key objectives:
1. Naturally incorporate as many of the JD keywords as possible throughout the resume
2. Strengthen bullet points with quantifiable achievements (use numbers where plausible)
3. Mirror the language and terminology used in the job description
4. Preserve all factual information — do NOT fabricate companies, titles, or dates. Do NOT add parenthetical qualifiers like "(Established Company)" after company names
5. Keep the overall structure: name/contact, summary, experience, education, skills
6. Use strong action verbs at the start of each bullet point
7. Keep formatting clean: plain text, no tables or columns
8. STRICT LENGTH LIMIT: The entire resume must fit within 2 pages — maximum 600 words / 50 bullet points total. Cut older or less relevant bullets if needed to stay within this limit. Do NOT pad or repeat content.

Job Description Keywords to incorporate:
{keywords_str}

Current Resume:
\"\"\"
{resume_text}
\"\"\"
"""

    if consolidated_feedback:
        feedback_lines = []
        ats = consolidated_feedback.get("ats", {})
        if ats.get("missing_keywords"):
            feedback_lines.append(f"- ATS: Add these missing keywords naturally: {', '.join(ats['missing_keywords'][:15])}")
        impact = consolidated_feedback.get("impact", {})
        if impact.get("weak_bullets"):
            feedback_lines.append(f"- Impact: Strengthen these weak bullets: {'; '.join(impact['weak_bullets'][:5])}")
        if impact.get("suggestions"):
            feedback_lines.append(f"- Impact suggestions: {'; '.join(impact['suggestions'][:5])}")
        skills = consolidated_feedback.get("skills_gap", {})
        if skills.get("missing_skills"):
            feedback_lines.append(f"- Skills Gap: Add or highlight: {', '.join(skills['missing_skills'][:10])}")
        readability = consolidated_feedback.get("readability", {})
        if readability.get("issues"):
            feedback_lines.append(f"- Readability: Fix these issues: {'; '.join(readability['issues'][:5])}")
        if feedback_lines:
            prompt += f"\nCRITICAL — Fix ALL of the following issues:\n" + "\n".join(feedback_lines) + "\n"

    prompt += "\nReturn ONLY the rewritten resume text. No commentary, no explanations, no markdown — just the plain resume text."

    model = MODEL_REWRITER_FAST if consolidated_feedback else MODEL_REWRITER
    return await complete(prompt, model)
