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
        parts.append(", ".join(sections["skills"]))
    return "\n".join(parts).strip()
