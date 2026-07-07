"""Deterministic JD-vs-profile gap computation.

The co-pilot must ask the user about REAL gaps — skills/tools the job description
emphasizes that the chosen profile doesn't show. Computing this deterministically
(instead of letting the LLM infer gaps) eliminates hallucinated gaps and invented
example companies: the model only asks about gaps we actually found.
"""

from __future__ import annotations

import re


def _present_in_text(skill_lower: str, haystack: str) -> bool:
    """True if skill appears in haystack bounded by non-alphanumerics.

    A plain ``skill in haystack`` test gives false positives for short skills —
    the language 'R' matches the 'r' in "orchestration", 'Go' matches "logo" —
    so a genuine gap is silently treated as already covered. Alnum lookarounds
    (rather than \\b, which mishandles symbols like 'c++') keep 'c++'/'node.js'
    matching correctly while requiring a real token boundary.
    """
    if not skill_lower:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(skill_lower)}(?![a-z0-9])", haystack) is not None


def compute_gaps(
    jd_result: dict,
    profile_skills: list[str],
    profile_text: str = "",
    limit: int = 3,
) -> list[str]:
    """Return up to `limit` JD-required skills absent from the profile.

    Priority order: required_hard_skills → critical_keywords → tech_stack. A skill
    counts as present if it matches a profile skill (case-insensitive) or appears
    anywhere in the profile's resume text.
    """
    candidates: list[str] = []
    for key in ("required_hard_skills", "critical_keywords", "tech_stack"):
        for item in (jd_result.get(key) or []):
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())

    # De-duplicate, preserving priority order (case-insensitive).
    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        cl = c.lower()
        if cl not in seen:
            seen.add(cl)
            ordered.append(c)

    skill_set = {s.lower() for s in profile_skills if isinstance(s, str) and s.strip()}
    haystack = (profile_text or "").lower()

    gaps: list[str] = []
    for c in ordered:
        cl = c.lower()
        if cl in skill_set or _present_in_text(cl, haystack):
            continue
        gaps.append(c)
        if len(gaps) >= limit:
            break
    return gaps
