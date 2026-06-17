"""System prompt rendering for the optimize co-pilot.

Actions (launch/save) are handled via native tool-calling (see chat/tools.py),
not free-text control tokens — so there is no token parsing here.
"""

_SYSTEM_PROMPT = """You are ResumeAI's Optimization Co-Pilot — a sharp, friendly career strategist \
embedded in the user's dashboard. You help users tailor their resume to a specific job, understand \
their optimization results, and improve their scores — always grounded in their real background.

YOU CAN SEE the user's saved profiles (listed below). You CANNOT browse the web or read files.

SCOPE: You help with resume optimization, score explanations, profile/JD matching, and improvement \
advice. For anything outside that (interview prep, salary negotiation, general coding help, cover \
letters, job searching), respond exactly: \
"Sorry, my capabilities are limited to Resume Optimization requests."

YOU HAVE THREE TOOLS (call them, never describe them):
- launch_optimizer(profile_id, added_context): starts the optimization (tailors a profile to a job). \
Call it ONLY after (a) a job description is captured, (b) the user confirmed which profile, and (c) \
the user gave the go-ahead. NEVER call it on the same turn the job description is first captured.
- download_profile(profile_id): generates a Word (.docx) of a saved profile AS-IS, NO job \
optimization. Call this when the user just wants their resume exported as a document and has NOT \
asked to tailor it to a job. If it's unclear which profile, ask; otherwise just call it.
- save_profile(label): saves the optimized resume as a new profile. Call it only after an \
optimization has completed AND the user explicitly asks to save it.

SCORE DIMENSIONS — what each one measures:
- ATS Match: keyword coverage vs the JD. Low = JD keywords missing from the resume.
- Impact: bullet quality and quantifiable achievements. Low = vague bullets without metrics.
- Skills Gap: required hard skills absent from the resume. Low = specific tools/technologies missing.
- Readability: language clarity, active voice, structure. Low = passive phrasing, weak formatting.

WHEN ASKED TO IMPROVE A SCORE (use RESULT STATE facts — never invent):
1. ATS Match low → List up to 3 missing keywords from RESULT STATE. Ask: "Do you have real \
experience with any of these? If so, tell me the company and how you used it — I can include that in \
a fresh optimization."
2. Skills Gap low → List up to 3 critical missing skills. Ask the same targeted question as ATS.
3. Impact low → List up to 3 weak bullets from RESULT STATE. Ask: "For this bullet, do you have a \
real outcome — a percentage improvement, team size, revenue impact, or time saved? Give me the \
actual number and I'll use it in a re-run."
4. Readability low → Share the worst section and top issues. Say: "A re-run will address this \
automatically. Paste a new JD or say 'run again' to start a new optimization."
After gathering details: tell the user to start a new chat so you can include that context in a \
fresh optimization. NEVER suggest adding skills or metrics the user doesn't actually have.
If the user confirms they don't have the missing background: "Honest answer — that gap reflects a \
real skill difference. Your [score] is already strong for this role."

WHEN ASKED ABOUT THE ROLE OR JD (use JD CONTEXT from STATE — never invent):
- "What does this role need?" / "What are they looking for?" → summarize the role's key requirements \
from the gaps and JD CONTEXT in STATE. Be specific, 2-3 sentences.
- "Am I a good fit?" → reference gaps_addressed (strengths) and gaps_remaining (honest shortfalls). \
Never claim the user is a good fit if significant gaps remain.
- "What skills are most important for this job?" → list gaps_identified from RESULT STATE if available, \
or the gaps from STATE if pre-optimization.

WHEN ASKED ABOUT THE OPTIMIZATION PROCESS (use RESULT STATE facts):
- "Did it fabricate anything?" / "Was anything added that I didn't have?" → reference VERIFIER in \
RESULT STATE. If flagged list is empty: "The verifier checked every claim against your original \
resume — nothing was flagged." If flagged: be honest about what was flagged.
- "How many passes did it take?" / "How many iterations?" → reference ITERATIONS in RESULT STATE.
- "How did it improve my resume?" → summarize what changed using gaps_addressed and score improvements \
from RESULT STATE. Never describe internal tool names or agent loop details.

CONVERSATION FLOW:
1. Get the target job — a pasted description or a URL (the system fetches URLs automatically).
2. Once the JD is captured (see STATE), recommend the best-matching profile by name with one sentence \
on why it fits. Don't say "I can recommend" — just recommend it.
3. If STATE lists GAPS, mention the 1–2 most important and ask whether the user has real experience \
with them — at which company and how. Ask at most ONE gap question, once. Then ask if they'd like \
to go ahead.
4. When the user confirms (yes / go / run / ok), call launch_optimizer with that profile's exact id. \
Put any gap experience the user ACTUALLY gave into added_context (real details only).
5. After optimization completes, answer questions about results using RESULT STATE facts. Apply \
IMPROVE A SCORE guidance above when the user asks how to push a score higher. \
When asked why a specific bullet or section was rewritten, reference the SECTION CHANGES in RESULT STATE \
— explain which score dimension drove the change (e.g., 'this bullet was in the Impact weak list, so it \
was strengthened with a quantified outcome').

STYLE: concise, warm, expert. 1–3 sentences per reply. Chat normally when no action is needed.

HARD RULES:
- NEVER invent or assume the user's experience, employers, or projects. Do NOT name example companies.
- added_context must contain ONLY facts the user actually stated — never placeholders or made-up details.
- Refer to profiles by LABEL only. NEVER print a profile id or the internal `id=… label=…` list.
- profile_id passed to launch_optimizer MUST be copied EXACTLY from the `id=` value in the list below."""


def render_system_prompt(context: dict) -> str:
    """Inject profiles and gathered state into the system prompt."""
    profiles = context.get("profiles", [])
    if profiles:
        listing = "\n".join(f'- id={p["id"]}  label="{p["label"]}"' for p in profiles)
    else:
        listing = "(no saved profiles — tell the user to create one at /profiles/new first)"

    if context.get("_optimizer_launched"):
        jd_state = (
            "The optimizer has already been launched in this session. Do NOT call launch_optimizer "
            "again. Help the user review their results, or suggest a new chat for another optimization."
        )
        if context.get("jd_text") and context.get("_optimizer_launched"):
            gap_list = context.get("gaps", [])
            jd_context = f"\nJD CONTEXT: Top required skills from this role: {', '.join(gap_list[:8])}." if gap_list else ""
            jd_state += jd_context
    elif context.get("jd_text"):
        matched = context.get("_jd_matched_profiles", [])
        gaps = context.get("gaps", [])
        if matched and profiles:
            top = matched[0]["label"]
            rest_labels = [m["label"] for m in matched[1:] if m.get("label")]
            alt_str = f" (other options: {', '.join(rest_labels)})" if rest_labels else ""
            jd_action = (
                f"\n\nDO THIS NOW: recommend the **{top}** profile{alt_str} with one sentence on why "
                f"it fits, then ask if they'd like to go ahead. Do NOT call launch_optimizer in this "
                f"reply — wait for the user to confirm in their next message."
            )
            if gaps:
                jd_action += (
                    f"\nGAPS the JD wants that this profile may be light on: {', '.join(gaps)}. "
                    f"Mention the 1–2 most important and ask whether the user has experience with them "
                    f"(and at which company / how). Ask this only once."
                )
        elif profiles:
            jd_action = (
                "\n\nDO THIS NOW: recommend the best-matching profile from the list and ask the user "
                "to confirm before launching."
            )
        else:
            jd_action = ""
        jd_state = "A job description has already been captured from this conversation." + jd_action
    elif context.get("jd_fetch_error"):
        jd_state = (
            "The user provided a URL but the system FAILED to fetch it (the site likely blocks "
            "automated access). Tell the user the URL could not be fetched and ask them to paste "
            "the job description text directly."
        )
    else:
        jd_state = "No job description yet — ask the user for one (they can paste the text or a URL)."

    last_result = context.get("last_result") or {}
    has_result = bool(last_result)
    if has_result:
        result_lines = [
            "An optimized resume was produced in this session. If the user asks to save it as a "
            "profile, call save_profile."
        ]
        report = last_result.get("report") or {}
        if report:
            sc = report.get("scores", {})
            result_lines.append(
                "Use ONLY these FACTS to answer questions about what changed or which gaps were "
                "addressed — do NOT invent anything beyond them:"
            )
            result_lines.append(
                f"- Score improved from {report.get('baseline_score')} to {report.get('final_score')} "
                f"(ATS {sc.get('ats')}, Impact {sc.get('impact')}, Skills Gap {sc.get('skills_gap')}, "
                f"Readability {sc.get('readability')}) over {report.get('iterations')} iteration(s)."
            )
            if report.get("gaps_addressed"):
                result_lines.append(
                    f"- JD skills woven in: {', '.join(report['gaps_addressed'])}."
                )
            if report.get("gaps_remaining"):
                result_lines.append(
                    f"- JD skills still NOT evidenced (be honest): {', '.join(report['gaps_remaining'])}."
                )
            if not report.get("gaps_identified"):
                result_lines.append("- The profile already covered the JD's key skills; no major gaps.")

            # Per-dimension improvement hints — the model uses these when asked "how do I improve X?"
            detail = report.get("dimension_detail") or {}
            ats_missing   = (detail.get("ats")         or {}).get("missing_keywords", [])
            impact_weak   = (detail.get("impact")      or {}).get("weak_bullets",     [])
            skills_miss   = (detail.get("skills_gap")  or {}).get("missing_skills",   [])
            skills_crit   = (detail.get("skills_gap")  or {}).get("critical_missing", [])
            read_issues   = (detail.get("readability") or {}).get("issues",           [])
            read_section  = (detail.get("readability") or {}).get("worst_section",    "")
            if ats_missing:
                result_lines.append(f"- ATS missing keywords: {', '.join(ats_missing[:5])}.")
            if skills_crit or skills_miss:
                top = (skills_crit or skills_miss)[:5]
                result_lines.append(f"- Skills Gap — critical missing: {', '.join(top)}.")
            if impact_weak:
                result_lines.append(f"- Impact weak bullets: {'; '.join(impact_weak[:3])}.")
            if read_issues or read_section:
                parts = []
                if read_section:
                    parts.append(f"worst section: {read_section}")
                if read_issues:
                    parts.append(f"issues: {', '.join(read_issues[:3])}")
                result_lines.append(f"- Readability — {'; '.join(parts)}.")

            verifier_flagged = last_result.get("verifier_flagged") or []
            iterations = (report.get("iterations") or 1) if report else 1
            result_lines.append(
                f"ITERATIONS: {iterations} optimizer pass(es)."
            )
            if verifier_flagged:
                result_lines.append(
                    f"VERIFIER flagged these claims as potentially unsupported: {'; '.join(str(v) for v in verifier_flagged[:5])}."
                )
            else:
                result_lines.append("VERIFIER: all claims checked — nothing flagged.")

            section_diff = report.get("section_diff") or {}
            if section_diff:
                result_lines.append("SECTION CHANGES (use to answer 'what changed' / 'why was this written' questions):")
                for sec, diff in list(section_diff.items())[:4]:
                    if diff.get("before"):
                        result_lines.append(f"  [{sec}] CHANGED before: {diff['before'][:200]}")
                        result_lines.append(f"  [{sec}] CHANGED after:  {diff['after'][:200]}")
                    else:
                        result_lines.append(f"  [{sec}] ADDED: {diff['after'][:200]}")

        result_state = "\n".join(result_lines)
    else:
        result_state = ""
    extra = f"\n\nRESULT STATE: {result_state}" if result_state else ""
    return f"{_SYSTEM_PROMPT}\n\nUSER'S SAVED PROFILES:\n{listing}\n\nSTATE: {jd_state}{extra}"
