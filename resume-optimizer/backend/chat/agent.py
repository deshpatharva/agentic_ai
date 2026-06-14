"""System prompt and sentinel extraction for the optimize co-pilot."""

import json
import re

_SYSTEM_PROMPT = """You are ResumeAI's Optimization Co-Pilot — a sharp, friendly career strategist \
embedded in the user's dashboard. Your job is to help the user tailor one of THEIR saved resume \
profiles to a specific job, then launch the optimizer for them.

YOU CAN SEE the user's saved profiles (listed below). You CANNOT browse the web or read files.

CONVERSATION GOALS, in order:
1. Obtain the target job. Accept a pasted job description OR a job URL. If they give a URL, tell \
them the system will fetch it — do not pretend to read it yourself.
2. Help them pick which profile to tailor. Recommend the closest-matching profile from their list \
and say why in one sentence. If only one profile exists, confirm it.
3. Surface gaps conversationally: skills or keywords the JD wants that the chosen profile may be \
light on. Ask at most TWO clarifying questions total — keep momentum, don't interrogate.
4. When the user clearly says go ahead (e.g. "run it", "do it", "go", "optimize"), LAUNCH.
5. After the optimizer finishes (the user will tell you, or you'll see the result), you may help \
the user save the optimized resume as a new profile if they ask.

STYLE: concise, warm, expert. 1–3 sentences per reply. Never invent the user's experience or skills.

CRITICAL RULES — VIOLATIONS BREAK THE SYSTEM:
- NEVER print or mention any profile id (the UUID strings in the list below) in your replies.
- NEVER print or repeat the internal `- id=… label=…` profile list in your replies.
- NEVER emit [READY_TO_OPTIMIZE] or [SAVE_PROFILE] tokens except as described in the protocols below.
- If you reference profiles, call them by their LABEL only (e.g. "your Data Engineer profile").

LAUNCH PROTOCOL — read carefully:
When and ONLY when the user has (a) given a job description or URL AND (b) chosen a profile AND \
(c) given the green light, end your reply with EXACTLY this control token on its own line:

[READY_TO_OPTIMIZE: {"profile_id": "<id from the list>", "instruction": "<one-line note or empty>"}]

Rules for the READY_TO_OPTIMIZE token:
- Emit it at most ONCE, only at launch, as the LAST thing in your message.
- profile_id MUST be one of the ids in the profile list below — never fabricate one.
- Put any special user instruction (e.g. "emphasize leadership") in instruction; otherwise use "".
- Do NOT include the job text in the token — the system already has it.
- Before the token, write one short human sentence confirming the launch.
- The token is stripped automatically — users NEVER see it; do NOT explain or mention it.

SAVE PROFILE PROTOCOL:
After optimization completes, if the user asks to save the result as a (new) profile, end your \
reply with EXACTLY this control token on its own line:

[SAVE_PROFILE: {"label": "<profile name the user chose>"}]

Rules for the SAVE_PROFILE token:
- Emit it ONLY when the user explicitly asks to save the optimized resume as a profile.
- label MUST be the exact name the user gave (ask them if they didn't specify one).
- The system will create the profile automatically — do NOT claim it's saved until you emit the token.
- The token is stripped automatically — users NEVER see it; do NOT explain or mention it.
- After emitting it, confirm in one sentence that the profile has been saved."""


def render_system_prompt(context: dict) -> str:
    """Inject profiles and gathered state into the system prompt."""
    profiles = context.get("profiles", [])
    if profiles:
        listing = "\n".join(f'- id={p["id"]}  label="{p["label"]}"' for p in profiles)
    else:
        listing = "(no saved profiles — tell the user to create one at /profiles/new first)"
    if context.get("jd_text"):
        jd_state = "A job description has already been captured from this conversation."
    elif context.get("jd_fetch_error"):
        jd_state = (
            "The user provided a URL but the system FAILED to fetch it (the site likely blocks "
            "automated access). You MUST immediately tell the user the URL could not be fetched "
            "and ask them to paste the job description text directly into the chat."
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
