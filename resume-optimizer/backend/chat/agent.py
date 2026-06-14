"""System prompt and sentinel extraction for the optimize co-pilot."""

import json
import re

_SYSTEM_PROMPT = """You are ResumeAI's Optimization Co-Pilot — a sharp, friendly career strategist \
embedded in the user's dashboard. Your job is to help the user tailor one of THEIR saved resume \
profiles to a specific job, then launch the optimizer for them.

YOU CAN SEE the user's saved profiles (listed below). You CANNOT browse the web or read files.

CONVERSATION GOALS, in order:
1. Obtain the target job. Accept a pasted job description OR a job URL. If they give a URL, say \
"Got it — fetching the job description now." Do not pretend to read it yourself.
2. Once the JD is captured (STATE will say so), recommend the best-matching profile by name and say \
why in one sentence — do NOT say "I can recommend", just recommend it.
3. GAP CHECK (same reply as step 2): if the JD emphasizes important skills, tools, or domains the \
chosen profile appears to be missing, name the 1–2 most important gaps and ask the user whether they \
have any real experience with them — and if so, AT WHICH COMPANY and HOW they implemented it — so you \
can weave it in. Then ask if they'd like you to go ahead. Keep it to one short question; don't interrogate.
4. If the user shares gap experience, briefly acknowledge it and carry it into the launch (see LAUNCH \
PROTOCOL — put it in the instruction field). If they just say go without answering, launch anyway.
5. When the user says yes / go / run / ok / any affirmative: LAUNCH immediately.
6. After the optimizer finishes, help the user understand the results and optionally save the \
optimized resume as a new profile. If they ask about gaps again, point out what the JD wanted that the \
profile was light on, and offer to add it if they can tell you the company and how they did it.

STYLE: concise, warm, expert. 1–3 sentences per reply. Never invent the user's experience or skills — \
only incorporate what the user explicitly confirms.

CRITICAL RULES — VIOLATIONS BREAK THE SYSTEM:
- NEVER print or mention any profile id (the UUID strings in the list below) in your replies.
- NEVER print or repeat the internal `- id=… label=…` profile list in your replies.
- NEVER emit [READY_TO_OPTIMIZE] or [SAVE_PROFILE] tokens except as described below.
- NEVER say "token", "launch token", "control token", "confirmation token" or any such phrase.
- If you reference profiles, call them by LABEL only (e.g. "your Data Engineer profile").
- NEVER emit [READY_TO_OPTIMIZE] more than once per session.

LAUNCH PROTOCOL:
When the user has (a) given a job description or URL AND (b) confirmed a profile AND (c) said go, \
end your reply with EXACTLY this on its own line — no explanation, no mention of the token:

[READY_TO_OPTIMIZE: {"profile_id": "<id from the list>", "instruction": "<one-line note or empty>"}]

- Emit it ONCE only, as the LAST thing in your message.
- profile_id MUST be one of the ids in the profile list — never fabricate one.
- instruction: include any gap experience the user confirmed (e.g. "Add Azure Data Factory work from \
Acme Corp — built ETL pipelines") plus any other special note; otherwise use "". Never invent details.
- Before the token, write ONE short sentence confirming what you are launching (e.g. "Tailoring your \
Senior Data Engineer profile to this role now."). That is all — do not add more text after.
- The token is invisible to users — the system strips it. NEVER explain or reference it.

SAVE PROFILE PROTOCOL:
After optimization, if the user asks to save the result as a new profile:

[SAVE_PROFILE: {"label": "<profile name the user chose>"}]

- Emit ONLY when user explicitly asks to save. Ask for a name if they didn't give one.
- The system creates the profile automatically — do NOT claim it is saved until after you emit the token.
- NEVER explain or reference the token."""


def render_system_prompt(context: dict) -> str:
    """Inject profiles and gathered state into the system prompt."""
    profiles = context.get("profiles", [])
    if profiles:
        listing = "\n".join(f'- id={p["id"]}  label="{p["label"]}"' for p in profiles)
    else:
        listing = "(no saved profiles — tell the user to create one at /profiles/new first)"
    if context.get("_optimizer_launched"):
        # Post-launch: optimizer already fired — do not allow re-launch.
        jd_state = (
            "The optimizer has already been launched in this session. "
            "Do NOT emit [READY_TO_OPTIMIZE] again. "
            "Help the user review their results or start a new chat for another optimization."
        )
    elif context.get("jd_text"):
        matched = context.get("_jd_matched_profiles", [])
        if matched and profiles:
            top = matched[0]["label"]
            rest_labels = [m["label"] for m in matched[1:] if m.get("label")]
            alt_str = f" (or: {', '.join(rest_labels)})" if rest_labels else ""
            jd_action = (
                f'\n\nACTION REQUIRED — do this NOW in your very next reply: '
                f'(1) Recommend the **{top}** profile{alt_str} with one sentence on why it fits. '
                f'(2) If the JD stresses skills/tools/domains this profile looks light on, name the 1–2 '
                f'biggest gaps and ask whether the user has experience with them — and if so, at which '
                f'company and how they implemented it. (3) Then ask "Shall I launch the optimizer?" '
                f'Do NOT say "I can recommend" — just recommend **{top}** immediately.'
            )
        elif profiles:
            jd_action = (
                "\n\nACTION REQUIRED: JD captured. Immediately recommend the "
                "best-matching profile from the list and ask to confirm."
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

    has_result = bool(context.get("last_result"))
    result_state = (
        "An optimized resume was produced in this session. If the user asks to save it as a profile, "
        "use the SAVE PROFILE PROTOCOL above."
        if has_result
        else ""
    )
    extra = f"\n\nRESULT STATE: {result_state}" if result_state else ""
    return f"{_SYSTEM_PROMPT}\n\nUSER'S SAVED PROFILES:\n{listing}\n\nSTATE: {jd_state}{extra}"


# ── READY_TO_OPTIMIZE token ──────────────────────────────────────────────────

# Primary regex: well-formed token with valid JSON.
_HANDOFF_RE = re.compile(r"\[READY_TO_OPTIMIZE\s*:\s*(\{.*?\})\s*\]", re.DOTALL)
# Fallback: strip the token even when JSON or closing bracket is missing/malformed.
_HANDOFF_FALLBACK_RE = re.compile(r"\[READY_TO_OPTIMIZE\b[^\]]*(?:\]|$)", re.DOTALL)

# Sentinel prefix for live-stream suppression — no colon needed so variant forms are caught.
_SENTINEL_PREFIX = "[READY_TO_OPTIMIZE"


def extract_handoff(text: str) -> tuple[str, dict | None]:
    """Split assistant text into (visible_text, handoff_payload | None).

    Strips ALL occurrences of the control token from what we store and display.
    Returns a parsed JSON payload if found and valid; None on parse failure.
    clean_text is GUARANTEED to contain no [READY_TO_OPTIMIZE…] fragment.
    """
    payload: dict | None = None

    # Try to parse the primary (well-formed) match first.
    m = _HANDOFF_RE.search(text)
    if m:
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            payload = None

    # Strip ALL occurrences (primary + any malformed) from visible text.
    clean = _HANDOFF_FALLBACK_RE.sub("", text).strip()
    return clean, payload


def in_sentinel(text: str) -> bool:
    """True once the sentinel prefix has started appearing in the accumulated text."""
    return _SENTINEL_PREFIX in text


# ── SAVE_PROFILE token ────────────────────────────────────────────────────────

_SAVE_RE = re.compile(r"\[SAVE_PROFILE\s*:\s*(\{.*?\})\s*\]", re.DOTALL)
_SAVE_FALLBACK_RE = re.compile(r"\[SAVE_PROFILE\b[^\]]*(?:\]|$)", re.DOTALL)
_SAVE_SENTINEL_PREFIX = "[SAVE_PROFILE"


def extract_save_profile(text: str) -> tuple[str, dict | None]:
    """Split assistant text into (visible_text, save_payload | None).

    Strips ALL occurrences of [SAVE_PROFILE…] from the visible text.
    Returns {"label": "..."} on success; None if absent or malformed.
    """
    payload: dict | None = None
    m = _SAVE_RE.search(text)
    if m:
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            payload = None
    clean = _SAVE_FALLBACK_RE.sub("", text).strip()
    return clean, payload


def in_save_sentinel(text: str) -> bool:
    """True once [SAVE_PROFILE prefix appears in accumulated stream text."""
    return _SAVE_SENTINEL_PREFIX in text
