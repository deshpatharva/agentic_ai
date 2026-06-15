"""Tool definitions for the optimize co-pilot (LiteLLM / OpenAI function-calling
format — provider-agnostic).

The model converses normally and, when an action is warranted, returns a
validated tool call instead of emitting a control token in free text. This
removes the entire class of "token leaked into chat / malformed JSON" bugs:
tool arguments are structured and separate from the assistant's visible text.
"""

from __future__ import annotations

import json

LAUNCH_TOOL = "launch_optimizer"
SAVE_TOOL = "save_profile"
DOWNLOAD_TOOL = "download_profile"

# OpenAI-style tool schemas. LiteLLM translates these to each provider's native
# tool format (Anthropic, Groq, Gemini) under the hood.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": LAUNCH_TOOL,
            "description": (
                "Launch the resume optimizer once the user has confirmed which saved "
                "profile to tailor and given the go-ahead. Call this ONLY after the user "
                "explicitly agrees to proceed (e.g. 'yes', 'go', 'run it', or by picking a "
                "profile). Do not call it on the turn the job description is first captured."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "The exact id of the profile to optimize, copied from the provided profile list.",
                    },
                    "added_context": {
                        "type": "string",
                        "description": (
                            "Optional. Real gap experience the user explicitly confirmed, in plain "
                            "text (e.g. 'Built Azure ML churn model at Contoso'). Use ONLY facts the "
                            "user actually stated — never placeholders, brackets, or invented details. "
                            "Empty string if none."
                        ),
                    },
                },
                "required": ["profile_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": DOWNLOAD_TOOL,
            "description": (
                "Generate a downloadable .docx of one of the user's saved profiles AS-IS, with NO "
                "job-description optimization. Call this when the user just wants their resume/profile "
                "exported as a Word document and has not asked to tailor it to a specific job. No job "
                "description is required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "The exact id of the profile to export, copied from the provided profile list.",
                    },
                },
                "required": ["profile_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": SAVE_TOOL,
            "description": (
                "Save the most recently optimized resume as a new saved profile. Call this only "
                "after an optimization has completed and the user explicitly asks to save it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "The profile name the user chose.",
                    },
                },
                "required": ["label"],
            },
        },
    },
]


def parse_tool_calls(message: dict | object) -> list[dict]:
    """Extract tool calls from a LiteLLM/OpenAI assistant message.

    Accepts either a dict-like message or an object with `.tool_calls`. Returns a
    list of {"name": str, "arguments": dict} — arguments parsed from the JSON
    string the model produced; malformed arguments yield {} (caller validates).
    """
    raw = _get(message, "tool_calls") or []
    out: list[dict] = []
    for call in raw:
        fn = _get(call, "function") or {}
        name = _get(fn, "name")
        if not name:
            continue
        args_raw = _get(fn, "arguments")
        args: dict = {}
        if isinstance(args_raw, dict):
            args = args_raw
        elif isinstance(args_raw, str) and args_raw.strip():
            try:
                parsed = json.loads(args_raw)
                if isinstance(parsed, dict):
                    args = parsed
            except (json.JSONDecodeError, ValueError):
                args = {}
        out.append({"name": name, "arguments": args})
    return out


def message_text(message: dict | object) -> str:
    """Return the assistant message's text content (empty string if none)."""
    content = _get(message, "content")
    if isinstance(content, str):
        return content
    # Some providers return content as a list of blocks.
    if isinstance(content, list):
        parts = []
        for block in content:
            text = _get(block, "text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


def _get(obj, key):
    """Attribute-or-key accessor (LiteLLM returns pydantic-ish objects or dicts)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
