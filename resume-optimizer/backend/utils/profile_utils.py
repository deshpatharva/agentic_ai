def sections_to_text(sections: dict) -> str:
    """Convert profile sections JSON to plain text for pipeline and docx-generator consumption.

    Emits the line structure generate_docx styles into the target layout:
      "{name}"                     → centered, blue, bold
      "{contact_fields}"           → centered, grey (location • email • phone • linkedin • website)
      Section header line          → blue underlined header
      "{title}  {dates}"           → bold title, date right-aligned
      "{company}"                  → italic line under the title
      "• {bullet}"                 → bullet list item
    """
    parts = []
    contact = sections.get("contact") or {}
    full_name = (contact.get("full_name") or "").strip()
    if full_name:
        parts.append(full_name)
    contact_bits = [
        (contact.get(k) or "").strip()
        for k in ("location", "email", "phone", "linkedin", "website")
    ]
    contact_line = " • ".join(b for b in contact_bits if b)
    if contact_line:
        parts.append(contact_line)
    if full_name or contact_line:
        parts.append("")
    if sections.get("summary"):
        parts.append("Professional Summary")
        parts.append(sections["summary"])
        parts.append("")
    if sections.get("experience"):
        parts.append("Professional Experience")
        for exp in sections["experience"]:
            title = (exp.get("title") or "").strip()
            company = (exp.get("company") or "").strip()
            dates = (exp.get("dates") or "").strip()
            header = f"{title}  {dates}".strip() if dates else title
            if header:
                parts.append(header)
            if company:
                parts.append(company)
            for b in exp.get("bullets", []):
                parts.append(f"• {b}")
            parts.append("")
    if sections.get("education"):
        parts.append("Education")
        for edu in sections["education"]:
            institution = (edu.get("institution") or "").strip()
            degree = (edu.get("degree") or "").strip()
            dates = (edu.get("dates") or "").strip()
            header = f"{institution}  {dates}".strip() if dates else institution
            if header:
                parts.append(header)
            if degree:
                parts.append(degree)
        parts.append("")
    if sections.get("skills"):
        parts.append("Skills")
        skill_categories: dict | None = sections.get("skill_categories")
        if skill_categories and isinstance(skill_categories, dict):
            # Emit one "Category: a, b, c" line per group — docx LABEL_LINE_PATTERN bolds the label.
            for cat, cat_skills in skill_categories.items():
                if not cat_skills:
                    continue
                if cat:
                    parts.append(f"{cat}: {', '.join(cat_skills)}")
                else:
                    parts.append(", ".join(cat_skills))
        else:
            parts.append(", ".join(sections["skills"]))
        parts.append("")
    for sec in sections.get("additional_sections") or []:
        heading = (sec.get("heading") or "").strip()
        content = (sec.get("content") or "").strip()
        # A heading with no content is meaningless — drop it. Content with no
        # heading is still worth keeping.
        if not content:
            continue
        if heading:
            parts.append(heading)
        parts.append(content)
        parts.append("")
    return "\n".join(parts).strip()
