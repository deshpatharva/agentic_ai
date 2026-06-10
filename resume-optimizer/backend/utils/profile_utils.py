def sections_to_text(sections: dict) -> str:
    """Convert profile sections JSON back to plain text for pipeline consumption."""
    parts = []
    if sections.get("summary"):
        parts.append(sections["summary"])
    for exp in sections.get("experience", []):
        parts.append(f"{exp.get('title', '')} at {exp.get('company', '')} ({exp.get('dates', '')})")
        for b in exp.get("bullets", []):
            parts.append(f"• {b}")
    for edu in sections.get("education", []):
        parts.append(f"{edu.get('degree', '')} — {edu.get('institution', '')} ({edu.get('dates', '')})")
    if sections.get("skills"):
        parts.append("Skills: " + ", ".join(sections["skills"]))
    return "\n".join(parts)
