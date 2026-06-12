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
