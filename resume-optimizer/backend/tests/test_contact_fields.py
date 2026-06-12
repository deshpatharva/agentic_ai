"""Unit tests for profile contact fields: schema, text assembly, docx render."""


def test_sections_data_defaults_contact():
    from profiles.schemas import SectionsData
    s = SectionsData()
    assert s.contact.full_name == ""
    assert s.model_dump()["contact"]["email"] == ""


def test_sections_data_accepts_contact():
    from profiles.schemas import SectionsData
    s = SectionsData(contact={"full_name": "Jane Doe", "email": "jane@doe.com"})
    assert s.contact.full_name == "Jane Doe"
    assert s.contact.phone == ""  # unspecified fields default to empty


def test_sections_to_text_emits_name_and_contact_first():
    from utils.profile_utils import sections_to_text
    text = sections_to_text({
        "contact": {
            "full_name": "Jane Doe",
            "location": "Austin, TX",
            "email": "jane@doe.com",
            "phone": "5551234567",
            "linkedin": "linkedin.com/in/janedoe",
            "website": "",
        },
        "summary": "Engineer.",
    })
    lines = text.splitlines()
    assert lines[0] == "Jane Doe"
    assert lines[1] == "Austin, TX • jane@doe.com • 5551234567 • linkedin.com/in/janedoe"
    assert "Professional Summary" in lines


def test_sections_to_text_without_contact_starts_at_summary():
    from utils.profile_utils import sections_to_text
    text = sections_to_text({"summary": "Engineer."})
    assert text.splitlines()[0] == "Professional Summary"


def test_sections_to_text_name_only_no_contact_line():
    from utils.profile_utils import sections_to_text
    text = sections_to_text({
        "contact": {"full_name": "Jane Doe"},
        "summary": "Engineer.",
    })
    lines = text.splitlines()
    assert lines[0] == "Jane Doe"
    assert lines[1] == ""  # blank separator, no empty bullet-joined line


def test_generate_docx_renders_centered_name_and_contact(tmp_path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from generators.docx_generator import generate_docx
    from utils.profile_utils import sections_to_text

    text = sections_to_text({
        "contact": {
            "full_name": "Jane Doe",
            "location": "Austin, TX",
            "email": "jane@doe.com",
            "phone": "5551234567",
            "linkedin": "",
            "website": "",
        },
        "summary": "Engineer with experience.",
    })
    out = tmp_path / "out.docx"
    generate_docx(text, str(out))
    paras = [p for p in Document(str(out)).paragraphs if p.text.strip()]

    assert paras[0].text == "Jane Doe"
    assert paras[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert paras[0].runs[0].bold is True

    assert paras[1].text.startswith("Austin, TX")
    assert paras[1].alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_generate_docx_renders_location_only_contact_centered(tmp_path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from generators.docx_generator import generate_docx
    from utils.profile_utils import sections_to_text

    text = sections_to_text({
        "contact": {"full_name": "Jane Doe", "location": "Austin, TX"},
        "summary": "Engineer.",
    })
    out = tmp_path / "out.docx"
    generate_docx(text, str(out))
    paras = [p for p in Document(str(out)).paragraphs if p.text.strip()]

    assert paras[0].text == "Jane Doe"
    assert paras[1].text == "Austin, TX"
    assert paras[1].alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_generate_docx_name_without_contact_keeps_header_styling(tmp_path):
    from docx import Document
    from generators.docx_generator import generate_docx
    from utils.profile_utils import sections_to_text

    text = sections_to_text({
        "contact": {"full_name": "Jane Doe"},
        "summary": "Engineer.",
    })
    out = tmp_path / "out.docx"
    generate_docx(text, str(out))
    paras = [p for p in Document(str(out)).paragraphs if p.text.strip()]

    assert paras[0].text == "Jane Doe"
    # The line after the name is the summary section header — it must keep
    # header styling (bold, uppercased), not be mistaken for contact info.
    assert paras[1].text == "PROFESSIONAL SUMMARY"
    assert paras[1].runs[0].bold is True
