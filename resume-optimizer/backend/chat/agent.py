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
3. GAP CHECK — ask AT MOST ONE short question, ONCE per session: if the JD stresses an important skill \
the chosen profile is missing, name it and ask whether they have real experience with it (and if so, \
where). Then ask "Shall I launch the optimizer?". Never ask a second gap question — if you already \
asked once, do not ask again.
4. LAUNCH as soon as the user gives ANY go-ahead — "yes", "go", "run it", or picking a profile (a \
message like 'Use my "X" profile' IS a launch confirmation). Do not keep asking gap questions; if the \
user picks a profile or says go, launch on that turn. Carry any gap experience they actually gave into \
the instruction field.
5. After the optimizer finishes, help the user understand the results and optionally save the \
optimized resume as a new profile.

STYLE: concise, warm, expert. 1–3 sentences per reply.
NEVER invent or assume the user's experience, employers, or projects. Do NOT name example companies \
(e.g. never say "a company like X"). Only reference real employers the user explicitly names.

CRITICAL RULES — VIOLATIONS BREAK THE SYSTEM:
- NEVER print or mention any profile id (the UUID strings in the list below) in your replies.
- NEVER print or repeat the internal `- id=… label=…` profile list in your replies.
- NEVER emit [READY_TO_OPTIMIZE] or [SAVE_PROFILE] tokens except as described below.
- NEVER say "token", "launch token", "control token", "confirmation token" or any such phrase.
- If you reference profiles, call them by LABEL only (e.g. "your Data Engineer profile").
- NEVER emit [READY_TO_OPTIMIZE] more than once per session.

LAUNCH PROTOCOL:
Emit the launch token ONLY after the user, in a SEPARATE later message, confirms they want to go \
(e.g. "yes", "go", "run it", or by picking a profile). Requirements: (a) a job description/URL is \
captured AND (b) the user has confirmed which profile AND (c) the user has given the green light.

[READY_TO_OPTIMIZE: {"profile_id": "<exact id from the list>", "instruction": "<one-line note or empty>"}]

- NEVER emit it on the SAME message where you first recommend a profile — recommend, ask, and WAIT \
for the user's next message. The turn that captures the JD must NOT contain this token.
- Emit it ONCE only, as the LAST thing in your message.
- profile_id MUST be copied EXACTLY from the `id=` value in the profile list below — it is a UUID, \
NOT the label. Never use the label, never fabricate, never leave it blank.
- instruction: a plain-text note containing ONLY real details the user gave (or ""). NEVER put \
placeholders, brackets, ellipses, or example text in it — no "[description]", no "[company]". If you \
don't have a real detail, use an empty string "".
- The JSON must be valid: exactly one closing brace and one closing bracket — `...""}]`. Never emit \
`}}` or `]]` or text after the token.
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
                f'Do NOT say "I can recommend" — just recommend **{top}** immediately. '
                f'CRITICAL: do NOT emit [READY_TO_OPTIMIZE] in THIS reply — only recommend and ask, '
                f'then WAIT for the user to confirm in their next message.'
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
# Fallback: strip EVERYTHING from the token marker to end-of-string. The launch
# token is always meant to be the LAST thing in the message, so a greedy strip
# guarantees no tail (e.g. `"}]`, `"}}`, bracketed placeholders) ever leaks even
# when the agent emits malformed JSON.
_HANDOFF_FALLBACK_RE = re.compile(r"\[READY_TO_OPTIMIZE\b.*\Z", re.DOTALL)
# Last-resort field recovery when JSON is malformed.
_PROFILE_ID_RE = re.compile(r'"?profile_id"?\s*:\s*"([^"]+)"')
_INSTRUCTION_RE = re.compile(r'"?instruction"?\s*:\s*"([^"]*)"')
# Bracketed placeholder text the agent should never emit (e.g. "[description]").
_PLACEHOLDER_RE = re.compile(r"\[[^\]]*\]")

# Sentinel prefix for live-stream suppression — no colon needed so variant forms are caught.
_SENTINEL_PREFIX = "[READY_TO_OPTIMIZE"


def _sanitize_instruction(instr: str) -> str:
    """Drop bracketed placeholders ("[description]") and tidy whitespace."""
    cleaned = _PLACEHOLDER_RE.sub("", instr or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;-—")
    return cleaned.strip()


def extract_handoff(text: str) -> tuple[str, dict | None]:
    """Split assistant text into (visible_text, handoff_payload | None).

    Strips the control token from what we store and display. Returns a parsed
    payload if found; recovers profile_id from malformed JSON as a fallback.
    clean_text is GUARANTEED to contain no [READY_TO_OPTIMIZE…] fragment.
    """
    payload: dict | None = None

    # 1. Try to parse the primary (well-formed) match first.
    m = _HANDOFF_RE.search(text)
    if m:
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            payload = None

    # 2. Recover from malformed JSON: pull profile_id (and instruction) directly.
    if payload is None and _SENTINEL_PREFIX in text:
        pid = _PROFILE_ID_RE.search(text)
        if pid:
            instr = _INSTRUCTION_RE.search(text)
            payload = {"profile_id": pid.group(1), "instruction": instr.group(1) if instr else ""}

    # 3. Sanitize the instruction so placeholder junk never reaches the pipeline.
    if payload is not None:
        payload["instruction"] = _sanitize_instruction(payload.get("instruction", ""))

    # 4. Greedy-strip the token (and anything after it) from the visible text.
    clean = _HANDOFF_FALLBACK_RE.sub("", text).strip()
    return clean, payload


def in_sentinel(text: str) -> bool:
    """True once the sentinel prefix has started appearing in the accumulated text."""
    return _SENTINEL_PREFIX in text


# ── SAVE_PROFILE token ────────────────────────────────────────────────────────

_SAVE_RE = re.compile(r"\[SAVE_PROFILE\s*:\s*(\{.*?\})\s*\]", re.DOTALL)
_SAVE_FALLBACK_RE = re.compile(r"\[SAVE_PROFILE\b.*\Z", re.DOTALL)
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
