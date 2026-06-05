"""
Shared resume section parser.

Detects named sections (summary, experience, education, skills, etc.) from
plain resume text using regex header matching.

Used by:
  - orchestration/optimizer.py (splits resume into sections before Phase 2)

Key design decision: section header lines ARE included in each section's
content block so that reassembly is a lossless '\n\n'.join(sections.values()).
"""

import re
from typing import Dict

SECTION_PATTERNS: Dict[str, re.Pattern] = {
    "summary": re.compile(
        r"^(summary|professional\s+summary|objective|profile|about\s+me|career\s+objective)[\s:]*$",
        re.IGNORECASE,
    ),
    "experience": re.compile(
        r"^(experience|work\s+experience|employment|work\s+history|professional\s+experience|career\s+history)[\s:]*$",
        re.IGNORECASE,
    ),
    "education": re.compile(
        r"^(education|academic\s+background|qualifications|academic\s+qualifications)[\s:]*$",
        re.IGNORECASE,
    ),
    "skills": re.compile(
        r"^(skills|technical\s+skills|core\s+competencies|competencies|technologies|tools)[\s:]*$",
        re.IGNORECASE,
    ),
    "certifications": re.compile(
        r"^(certifications?|licenses?|credentials?|professional\s+development)[\s:]*$",
        re.IGNORECASE,
    ),
    "projects": re.compile(
        r"^(projects?|key\s+projects?|notable\s+projects?)[\s:]*$",
        re.IGNORECASE,
    ),
}

# Canonical section order for reassembly
SECTION_ORDER = ["header", "summary", "experience", "education", "skills", "certifications", "projects"]


def detect_sections(text: str) -> Dict[str, str]:
    """
    Split resume text into named sections.

    Section header lines (e.g. "EXPERIENCE", "Skills") are INCLUDED in each
    section's content block so reassembly with join() is lossless.

    The "header" section captures everything before the first named section
    (typically the candidate's name and contact information).

    Returns:
        Dict mapping section name to its full text block (including the header line).
        Empty sections are excluded.
    """
    current_section = "header"
    current_lines: list = []
    buckets: dict = {"header": []}

    for line in text.splitlines():
        stripped = line.strip()

        matched_section = None
        for section_name, pattern in SECTION_PATTERNS.items():
            if pattern.match(stripped):
                matched_section = section_name
                break

        if matched_section:
            content = "\n".join(current_lines).strip()
            if content:
                buckets[current_section] = current_lines[:]
            current_section = matched_section
            current_lines = [line]
            buckets.setdefault(current_section, [])
        else:
            current_lines.append(line)

    content = "\n".join(current_lines).strip()
    if content:
        buckets.setdefault(current_section, [])
        buckets[current_section] = current_lines[:]

    return {
        name: "\n".join(lines).strip()
        for name, lines in buckets.items()
        if "\n".join(lines).strip()
    }


def reassemble(sections: Dict[str, str]) -> str:
    """
    Reassemble a sections dict into a full resume string.
    Sections are joined in canonical order; unknown sections appended at the end.
    """
    parts: list = []
    for name in SECTION_ORDER:
        text = sections.get(name, "").strip()
        if text:
            parts.append(text)
    for name, text in sections.items():
        if name not in SECTION_ORDER and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)
