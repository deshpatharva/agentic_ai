"""Conversation state machine for the optimize co-pilot.

Each chat session moves through phases. Each phase has:
  - a focused system prompt (not the full kitchen-sink)
  - a limited set of available tools
  - deterministic handlers for common inputs (URL paste, picker click, "yes")
"""

from __future__ import annotations

import re
from chat.tools import TOOLS, LAUNCH_TOOL, SAVE_TOOL, DOWNLOAD_TOOL, EDIT_TOOL

# ── Phases ──────────────────────────────────────────────────────────────────────

AWAITING_JD = "awaiting_jd"
JD_CAPTURED = "jd_captured"
OPTIMIZING = "optimizing"
RESULTS_READY = "results_ready"

_AFFIRM_RE = re.compile(
    r"^(yes|yeah|yep|yup|sure|go|go ahead|run|run it|ok|okay|do it|proceed|let'?s go|launch|start|confirm)\s*[.!]?$",
    re.I,
)
_PICKER_RE = re.compile(r'^Use my "(.+)" profile$')
_URL_RE = re.compile(r"^https?://", re.I)

_TOOLS_BY_NAME = {t["function"]["name"]: t for t in TOOLS}


def resolve_phase(ctx: dict) -> str:
    if ctx.get("last_result"):
        return RESULTS_READY
    if ctx.get("_optimizer_launched"):
        return OPTIMIZING
    if ctx.get("jd_text"):
        return JD_CAPTURED
    return AWAITING_JD


def tools_for_phase(phase: str) -> list[dict]:
    if phase == AWAITING_JD:
        return [_TOOLS_BY_NAME[DOWNLOAD_TOOL]]
    if phase == JD_CAPTURED:
        return [_TOOLS_BY_NAME[LAUNCH_TOOL], _TOOLS_BY_NAME[DOWNLOAD_TOOL]]
    if phase == OPTIMIZING:
        return []
    # RESULTS_READY
    return [
        _TOOLS_BY_NAME[SAVE_TOOL],
        _TOOLS_BY_NAME[DOWNLOAD_TOOL],
        _TOOLS_BY_NAME[EDIT_TOOL],
    ]


def try_deterministic(
    phase: str, message: str, ctx: dict, profiles: list[dict]
) -> dict | None:
    """Try to handle the input without an LLM call.

    Returns {"action": str, "response": str, ...} or None if the LLM is needed.

    Actions:
      "respond"   — just send the response text, no tool call
      "launch"    — call fire_optimizer with profile_id
      "download"  — call resolve_profile_download with profile_id
    """
    text = message.strip()

    # ── Profile picker click: 'Use my "Senior Data Engineer" profile' ────────
    picker_match = _PICKER_RE.match(text)
    if picker_match:
        label = picker_match.group(1)
        profile = _find_profile_by_label(label, profiles)
        if profile:
            if phase == JD_CAPTURED and ctx.get("jd_text") and not ctx.get("_optimizer_launched"):
                return {
                    "action": "launch",
                    "profile_id": profile["id"],
                    "response": f'Launching the optimizer with your "{profile["label"]}" profile now…',
                }
            return {
                "action": "download",
                "profile_id": profile["id"],
                "response": f'Generating your "{profile["label"]}" resume…',
            }

    # ── Bare profile label (e.g. user types "Senior Data Engineer") ──────────
    if not _URL_RE.match(text) and len(text) < 120:
        profile = _find_profile_by_label(text, profiles)
        if profile:
            if phase == JD_CAPTURED and ctx.get("jd_text") and not ctx.get("_optimizer_launched"):
                return {
                    "action": "launch",
                    "profile_id": profile["id"],
                    "response": f'Great — launching the optimizer with your "{profile["label"]}" profile…',
                }
            if phase == AWAITING_JD:
                return {
                    "action": "download",
                    "profile_id": profile["id"],
                    "response": f'Generating your "{profile["label"]}" resume as a Word document…',
                }

    # ── Affirmation ("yes", "go", "run it") with a recommended profile ───────
    if phase == JD_CAPTURED and _AFFIRM_RE.match(text):
        recommended = _get_recommended_profile(ctx, profiles)
        if recommended and not ctx.get("_optimizer_launched"):
            return {
                "action": "launch",
                "profile_id": recommended["id"],
                "response": f'Launching the optimizer with your "{recommended["label"]}" profile…',
            }

    # ── Optimizing phase — block input ───────────────────────────────────────
    if phase == OPTIMIZING:
        return {
            "action": "respond",
            "response": "The optimizer is still running — I'll let you know as soon as it's done.",
        }

    return None


def fallback_response(phase: str, ctx: dict) -> str:
    """Deterministic response when the LLM returns empty."""
    if phase == AWAITING_JD:
        return (
            "To get started, paste a job description or a job listing URL. "
            "I'll match it to your best profile and optimize your resume for that role."
        )
    if phase == JD_CAPTURED:
        matched = ctx.get("_jd_matched_profiles", [])
        if matched:
            top = matched[0].get("label", "your profile")
            return (
                f'I\'d recommend your "{top}" profile for this role. '
                f"Would you like me to go ahead and optimize it?"
            )
        return "Which profile would you like to use for this job? You can pick one from the list above."
    if phase == OPTIMIZING:
        return "The optimizer is still running — hang tight!"
    # RESULTS_READY
    return (
        "Your optimized resume is ready! You can ask me about the scores, "
        "request specific edits, save it as a new profile, or download it as a Word document."
    )


def _find_profile_by_label(text: str, profiles: list[dict]) -> dict | None:
    """Match user input to a profile by label (case-insensitive, flexible)."""
    needle = text.strip().strip('"').strip("'").lower()
    if not needle:
        return None
    # Exact match first
    for p in profiles:
        if (p.get("label") or "").strip().lower() == needle:
            return p
    # Contains match (either direction)
    for p in profiles:
        pl = (p.get("label") or "").strip().lower()
        if pl and (needle in pl or pl in needle):
            return p
    return None


def _get_recommended_profile(ctx: dict, profiles: list[dict]) -> dict | None:
    """Return the top-matched profile if one was recommended."""
    matched = ctx.get("_jd_matched_profiles", [])
    if not matched:
        return profiles[0] if len(profiles) == 1 else None
    top_id = matched[0].get("id")
    return next((p for p in profiles if p.get("id") == top_id), None)
