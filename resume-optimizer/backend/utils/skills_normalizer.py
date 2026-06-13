"""
Skills section post-processor.

Three jobs:
  1. Reconcile — scan the experience section for tools/technologies mentioned
     there but absent from the skills list, and add them.
  2. Deduplicate — remove skills that are already covered by another entry
     (e.g. "Azure DevOps" appearing twice under different groupings).
  3. Strip low-signal filler — generic items that dilute strong skills for
     senior-level candidates.
"""

from __future__ import annotations

import re
from typing import Optional

# Low-signal items to remove for senior/lead resumes (mid/entry keep them).
_FILLER_SKILLS = frozenset({
    "data structures", "algorithms", "object-oriented programming", "oop",
    "functional programming", "software development lifecycle", "sdlc",
    "networking fundamentals", "cloud computing", "scalability",
    "api design", "database administration", "data modeling",
})

# Technologies we know to look for in experience text.
# Keys are the canonical skill label; values are patterns to search for.
_EXPERIENCE_TECH_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Kafka",              re.compile(r"\bKafka\b",              re.IGNORECASE)),
    ("JMeter",             re.compile(r"\bJMeter\b",             re.IGNORECASE)),
    ("CloudWatch",         re.compile(r"\bCloudWatch\b",         re.IGNORECASE)),
    ("Azure AI Foundry",   re.compile(r"\bAzure AI Foundry\b",   re.IGNORECASE)),
    ("Microsoft Graph API",re.compile(r"\bMicrosoft Graph\b",    re.IGNORECASE)),
    ("Spark",              re.compile(r"\bApache Spark\b|\bSpark\b", re.IGNORECASE)),
    ("Airflow",            re.compile(r"\bAirflow\b",            re.IGNORECASE)),
    ("FastAPI",            re.compile(r"\bFastAPI\b",            re.IGNORECASE)),
    ("GraphQL",            re.compile(r"\bGraphQL\b",            re.IGNORECASE)),
    ("Celery",             re.compile(r"\bCelery\b",             re.IGNORECASE)),
    ("RabbitMQ",           re.compile(r"\bRabbitMQ\b",           re.IGNORECASE)),
]


def _parse_skills(skills_text: str) -> list[str]:
    """Split a flat or categorized skills block into individual skill tokens."""
    # Strip section header line(s) before parsing
    lines = skills_text.splitlines()
    skill_lines = [ln for ln in lines if not re.match(
        r"^\s*(skills|technical skills|core competencies|competencies|technologies|tools)\s*:?\s*$",
        ln, re.IGNORECASE,
    )]
    combined = " ".join(skill_lines)
    # Split on commas and semicolons; handle "Foo (Bar)" as one token
    tokens = re.split(r"[,;]+", combined)
    return [t.strip() for t in tokens if t.strip()]


def _skills_lower_set(tokens: list[str]) -> set[str]:
    return {t.lower() for t in tokens}


def _dedup(tokens: list[str]) -> list[str]:
    """
    Remove tokens that are exact-case-insensitive duplicates of an earlier token,
    OR are a strict substring of an earlier token (catches 'Azure DevOps' appearing
    both inside 'Azure (IaaS, DevOps)' grouping and as 'CI/CD (Azure DevOps, Jenkins)').
    """
    seen_lower: list[str] = []
    result: list[str] = []

    for tok in tokens:
        tl = tok.lower()
        duplicate = False
        for prev in seen_lower:
            # Exact duplicate
            if tl == prev:
                duplicate = True
                break
            # tl is fully contained inside a previous token (e.g. "azure devops" inside
            # "ci/cd (azure devops, jenkins)") — the longer one already covers it
            if tl in prev or prev in tl:
                duplicate = True
                break
        if not duplicate:
            seen_lower.append(tl)
            result.append(tok)

    return result


def _strip_filler(tokens: list[str], seniority: str) -> list[str]:
    """Remove low-signal generic skills for senior/lead candidates."""
    if seniority not in ("senior", "lead"):
        return tokens
    return [t for t in tokens if t.lower() not in _FILLER_SKILLS]


def _reconcile_from_experience(
    tokens: list[str],
    experience_text: str,
) -> list[str]:
    """Add tools found in experience but missing from skills."""
    existing_lower = _skills_lower_set(tokens)
    additions: list[str] = []

    for label, pattern in _EXPERIENCE_TECH_PATTERNS:
        if label.lower() not in existing_lower and pattern.search(experience_text):
            additions.append(label)

    return tokens + additions


def normalize_skills(
    skills_text: str,
    experience_text: str = "",
    seniority: str = "mid",
) -> str:
    """
    Normalize the skills section text.

    Args:
        skills_text:     Raw skills section (may include the section header line).
        experience_text: Full experience section text for reconciliation.
        seniority:       'entry' | 'mid' | 'senior' | 'lead' — controls filler removal.

    Returns:
        Normalized skills section text (header line preserved if present).
    """
    if not skills_text.strip():
        return skills_text

    # Preserve header line
    lines = skills_text.splitlines()
    header_line: Optional[str] = None
    if lines and re.match(
        r"^\s*(skills|technical skills|core competencies|competencies|technologies|tools)\s*:?\s*$",
        lines[0], re.IGNORECASE,
    ):
        header_line = lines[0]

    tokens = _parse_skills(skills_text)
    tokens = _reconcile_from_experience(tokens, experience_text)
    tokens = _strip_filler(tokens, seniority)
    tokens = _dedup(tokens)

    skills_line = ", ".join(tokens) + "."
    if header_line:
        return f"{header_line}\n{skills_line}"
    return skills_line
