"""
PDF Resume Parser
Extracts text from a PDF file and detects common resume sections.
"""

import pdfplumber
from utils.section_parser import SECTION_PATTERNS


def _detect_sections(lines: list[str]) -> dict:
    """
    Walk through lines and assign each line to a section bucket.

    Returns a dict mapping section names to their content strings.
    """
    sections: dict[str, list[str]] = {k: [] for k in SECTION_PATTERNS}
    sections["header"] = []  # name / contact info before first section

    current_section = "header"

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        matched = False
        for section_name, pattern in SECTION_PATTERNS.items():
            if pattern.match(stripped):
                current_section = section_name
                matched = True
                break

        if not matched:
            sections[current_section].append(stripped)

    # Convert lists to strings and drop empty sections
    return {k: "\n".join(v) for k, v in sections.items() if v}


def parse_pdf(file_path) -> dict:
    """
    Parse a PDF resume file.

    Args:
        file_path: Absolute path to the PDF file.

    Returns:
        {
            "raw_text": str,
            "sections": {
                "header": str,
                "summary": str,
                "experience": str,
                "education": str,
                "skills": str,
                ...
            }
        }
    """
    all_lines: list[str] = []
    raw_text_parts: list[str] = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                raw_text_parts.append(page_text)
                all_lines.extend(page_text.splitlines())

    raw_text = "\n".join(raw_text_parts)
    sections = _detect_sections(all_lines)

    return {
        "raw_text": raw_text,
        "sections": sections,
    }
