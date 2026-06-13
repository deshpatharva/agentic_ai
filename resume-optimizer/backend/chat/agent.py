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

STYLE: concise, warm, expert. 1–3 sentences per reply. Never invent the user's experience or skills.

LAUNCH PROTOCOL — read carefully:
When and ONLY when the user has (a) given a job description or URL AND (b) chosen a profile AND \
(c) given the green light, end your reply with EXACTLY this control token on its own line:

[READY_TO_OPTIMIZE: {"profile_id": "<id from the list>", "instruction": "<one-line note or empty>"}]

Rules for the token:
- Emit it at most once, only at launch, as the LAST thing in your message.
- profile_id MUST be one of the ids in the profile list below — never fabricate one.
- Put any special user instruction (e.g. "emphasize leadership") in instruction; otherwise use "".
- Do NOT include the job text in the token — the system already has it.
- Before the token, write one short human sentence confirming the launch."""


def render_system_prompt(context: dict) -> str:
    """Inject profiles and gathered state into the system prompt."""
    profiles = context.get("profiles", [])
    if profiles:
        listing = "\n".join(f'- id={p["id"]}  label="{p["label"]}"' for p in profiles)
    else:
        listing = "(no saved profiles — tell the user to create one at /profiles/new first)"
    jd_state = (
        "A job description has already been captured from this conversation."
        if context.get("jd_text")
        else "No job description yet — ask the user for one."
    )
    return f"{_SYSTEM_PROMPT}\n\nUSER'S SAVED PROFILES:\n{listing}\n\nSTATE: {jd_state}"


_HANDOFF_RE = re.compile(r"\[READY_TO_OPTIMIZE:\s*(\{.*?\})\s*\]", re.DOTALL)
# The sentinel prefix — used to suppress the trailing token while streaming.
_SENTINEL_PREFIX = "[READY_TO_OPTIMIZE:"


def extract_handoff(text: str) -> tuple[str, dict | None]:
    """Split assistant text into (visible_text, handoff_payload | None).

    Strips the control token from what we store and display. Returns parsed
    JSON payload if present and valid; None on parse failure (keep talking).
    """
    m = _HANDOFF_RE.search(text)
    if not m:
        return text.strip(), None
    visible = (text[: m.start()] + text[m.end() :]).strip()
    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError:
        return visible, None
    return visible, payload


def in_sentinel(text: str) -> bool:
    """True once the sentinel prefix has started appearing in the accumulated text."""
    return _SENTINEL_PREFIX in text
