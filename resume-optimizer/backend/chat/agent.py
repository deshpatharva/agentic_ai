"""System prompt rendering for the optimize co-pilot.

Split into a compact system prompt (instructions + profiles) and a dynamic
context message (state, scores, gaps) injected as a user-role message.
This keeps the system message small and cacheable while giving the model
all the dynamic context it needs in a natural position.
"""

from __future__ import annotations

from chat.state_machine import AWAITING_JD, JD_CAPTURED, OPTIMIZING, RESULTS_READY

# ── Base instructions (shared across all phases) ────────────────────────────────

_BASE = """\
You are ResumeAI's Optimization Co-Pilot — a sharp, friendly career strategist.
You help users tailor their resume to a specific job, understand optimization results, \
and improve scores — always grounded in their real background.

SCOPE: Resume optimization, score explanations, profile/JD matching, improvement advice. \
For anything outside that respond: "Sorry, my capabilities are limited to Resume Optimization requests."

STYLE: concise, warm, expert. 1–3 sentences per reply.

HARD RULES:
- NEVER invent or assume the user's experience, employers, or projects.
- Refer to profiles by LABEL only. Never print a profile id.
- profile_id passed to tools MUST be copied EXACTLY from the id= value in the profiles list."""

# ── Per-phase instructions ──────────────────────────────────────────────────────

_EDIT_GUIDANCE = """\
RESUME EDITS: to change a saved profile (e.g. "remove the objective section"), call \
edit_resume with the user's request verbatim as instruction and that profile's exact \
id as profile_id. Ask which profile they mean if it's ambiguous. Never invent experience."""

_PHASE_INSTRUCTIONS = {
    AWAITING_JD: f"""\
The user has not provided a job description yet.
Ask for one — they can paste the text or a URL. Keep it to one sentence.
If the user asks to download a profile, call download_profile with the profile's id.
{_EDIT_GUIDANCE}""",

    JD_CAPTURED: f"""\
A job description has been captured.
YOUR TOOLS: launch_optimizer(profile_id, added_context), download_profile(profile_id), \
edit_resume(instruction, profile_id).

CONVERSATION FLOW:
1. Recommend the best-matching profile by name with one sentence on why it fits.
2. If GAPS are listed in CONTEXT, mention the 1–2 most important and ask whether the user \
has real experience (at which company, how). Ask at most once.
3. When the user confirms — "yes", "go", "run", "ok", profile picker button, or any clear \
affirmation — call launch_optimizer immediately with that profile's exact id.
- 'Use my "[label]" profile' from picker = direct selection AND confirmation, no follow-up needed.
- added_context must contain ONLY facts the user actually stated — never placeholders.
- NEVER call launch_optimizer on the same turn the JD is first captured.
{_EDIT_GUIDANCE}""",

    OPTIMIZING: """\
The optimizer is currently running. Do NOT call any tools.
Tell the user their resume is being optimized and they'll see results shortly.""",

    RESULTS_READY: """\
An optimized resume was produced. YOUR TOOLS: save_profile(label), download_profile(profile_id), \
edit_resume(instruction, profile_id).

SCORE DIMENSIONS:
- ATS Match: keyword coverage vs JD. Low = JD keywords missing.
- Impact: bullet quality and quantifiable achievements. Low = vague bullets.
- Skills Gap: required hard skills absent. Low = tools/technologies missing.
- Readability: language clarity, active voice, structure. Low = passive phrasing.
- JD Tailoring: how specifically customized for the role. Low = generic language.

WHEN ASKED TO IMPROVE A SCORE (use RESULT CONTEXT facts — never invent):
- ATS/Skills Gap low → List up to 3 missing keywords/skills. Ask: "Do you have real \
experience with any of these?"
- Impact low → List weak bullets. Ask for real outcomes (%, team size, revenue, time saved).
- Readability low → Share worst section. Say a re-run will address it.
Never suggest adding skills the user doesn't have.

WHEN ASKED ABOUT THE PROCESS:
- Fabrication → reference VERIFIER in context.
- Iterations → reference ITERATIONS in context.
- What changed → reference SECTION CHANGES in context.

EDITS: call edit_resume with the user's request verbatim. Never invent experience.
SAVE: call save_profile only when the user explicitly asks.""",
}


def render_system_prompt(context: dict, phase: str | None = None) -> str:
    """Build a focused system prompt: base instructions + phase instructions + profiles."""
    if phase is None:
        from chat.state_machine import resolve_phase
        phase = resolve_phase(context)

    profiles = context.get("profiles", [])
    if profiles:
        listing = "\n".join(f'- id={p["id"]}  label="{p["label"]}"' for p in profiles)
    else:
        listing = "(no saved profiles — tell the user to create one at /profiles/new first)"

    phase_text = _PHASE_INSTRUCTIONS.get(phase, _PHASE_INSTRUCTIONS[AWAITING_JD])

    return f"{_BASE}\n\n{phase_text}\n\nUSER'S SAVED PROFILES:\n{listing}"


def render_context_message(context: dict, phase: str | None = None) -> str | None:
    """Build a dynamic context message (injected as user role before history).

    Returns None if there's no dynamic context to inject.
    """
    if phase is None:
        from chat.state_machine import resolve_phase
        phase = resolve_phase(context)

    parts: list[str] = []

    # JD state
    if context.get("jd_fetch_error"):
        parts.append(
            "URL FETCH FAILED: The user provided a URL but the system could not fetch it. "
            "Ask them to paste the job description text directly."
        )

    if phase == JD_CAPTURED:
        matched = context.get("_jd_matched_profiles", [])
        gaps = context.get("gaps", [])
        if matched:
            top = matched[0].get("label", "")
            rest = [m["label"] for m in matched[1:] if m.get("label")]
            alt_str = f" (other options: {', '.join(rest)})" if rest else ""
            parts.append(f"RECOMMENDED PROFILE: {top}{alt_str}")
        if gaps:
            parts.append(f"GAPS (JD skills this profile may lack): {', '.join(gaps)}")

    # Result state (only in RESULTS_READY)
    last_result = context.get("last_result") or {}
    if last_result and phase == RESULTS_READY:
        report = last_result.get("report") or {}
        if report:
            sc = report.get("scores", {})
            parts.append(
                f"SCORES: {report.get('baseline_score')} → {report.get('final_score')} "
                f"(ATS {sc.get('ats')}, Impact {sc.get('impact')}, Skills Gap {sc.get('skills_gap')}, "
                f"Readability {sc.get('readability')}, JD Tailoring {sc.get('jd_tailoring')}) "
                f"over {report.get('iterations')} iteration(s)."
            )
            if report.get("gaps_addressed"):
                parts.append(f"GAPS ADDRESSED: {', '.join(report['gaps_addressed'])}")
            if report.get("gaps_remaining"):
                parts.append(f"GAPS REMAINING: {', '.join(report['gaps_remaining'])}")

            detail = report.get("dimension_detail") or {}
            ats_missing = (detail.get("ats") or {}).get("missing_keywords", [])
            impact_weak = (detail.get("impact") or {}).get("weak_bullets", [])
            skills_crit = (detail.get("skills_gap") or {}).get("critical_missing", [])
            skills_miss = (detail.get("skills_gap") or {}).get("missing_skills", [])
            read_issues = (detail.get("readability") or {}).get("issues", [])
            read_section = (detail.get("readability") or {}).get("worst_section", "")

            if ats_missing:
                parts.append(f"ATS MISSING: {', '.join(ats_missing[:5])}")
            if skills_crit or skills_miss:
                parts.append(f"SKILLS MISSING: {', '.join((skills_crit or skills_miss)[:5])}")
            if impact_weak:
                parts.append(f"WEAK BULLETS: {'; '.join(impact_weak[:3])}")
            if read_issues or read_section:
                r = []
                if read_section:
                    r.append(f"worst: {read_section}")
                if read_issues:
                    r.append(f"issues: {', '.join(read_issues[:3])}")
                parts.append(f"READABILITY: {'; '.join(r)}")

            verifier = last_result.get("verifier_flagged") or []
            if verifier:
                parts.append(f"VERIFIER FLAGGED: {'; '.join(str(v) for v in verifier[:5])}")
            else:
                parts.append("VERIFIER: all claims checked — nothing flagged.")

            section_diff = report.get("section_diff") or {}
            if section_diff:
                diff_lines = ["SECTION CHANGES:"]
                for sec, diff in list(section_diff.items())[:4]:
                    if diff.get("before"):
                        diff_lines.append(f"  [{sec}] before: {diff['before'][:150]}")
                        diff_lines.append(f"  [{sec}] after: {diff['after'][:150]}")
                    else:
                        diff_lines.append(f"  [{sec}] added: {diff['after'][:150]}")
                parts.append("\n".join(diff_lines))

        gap_list = context.get("gaps", [])
        if gap_list:
            parts.append(f"JD CONTEXT: Top required skills: {', '.join(gap_list[:8])}")

    if not parts:
        return None

    return "[CONTEXT — use these facts to answer, never invent beyond them]\n" + "\n".join(parts)
