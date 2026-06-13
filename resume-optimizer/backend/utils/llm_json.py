"""
Robust extraction of JSON from LLM output — the single implementation used by
every agent/endpoint that parses model responses (scorer, JD analyzer,
profile parser/interview, profile matching).

LLM output is untrusted: models wrap JSON in markdown fences, <thinking> tags,
or conversational prose. `parse_llm_json` recovers the payload or raises
ValueError so each call site can degrade in its own way.
"""
import json
import re
from typing import Any

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)


def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        parts = text.split("```")
        candidate = parts[1] if len(parts) > 1 else text
        if candidate.startswith("json"):
            candidate = candidate[4:]
        return candidate.strip()
    return text


def extract_json(text: str, kind: str = "object") -> str:
    """Best-effort extraction of the first JSON object/array from LLM output."""
    text = _THINKING_RE.sub("", text.strip()).strip()
    text = _strip_fences(text)
    pattern = r"\{.*\}" if kind == "object" else r"\[.*\]"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(0) if match else text


def parse_llm_json(text: str, kind: str = "object") -> Any:
    """
    Parse a JSON object/array out of raw LLM output.

    Raises ValueError when nothing parseable is found or the parsed value has
    the wrong shape (callers decide whether that means a fallback, a retry,
    or a 502).
    """
    candidate = extract_json(text, kind)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"no parseable JSON {kind} in LLM output") from exc

    expected = dict if kind == "object" else list
    if not isinstance(parsed, expected):
        raise ValueError(f"LLM output parsed to {type(parsed).__name__}, expected {kind}")
    return parsed
