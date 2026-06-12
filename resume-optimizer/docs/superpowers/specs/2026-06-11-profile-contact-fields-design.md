# Profile Contact Fields — Design

**Date:** 2026-06-11
**Status:** Approved

## Problem

Generated resume documents from the profile flow have no name/contact header.
Profile sections only store summary, experience, education, and skills, so
`sections_to_text` cannot emit the centered name + contact line that
`generate_docx` already knows how to style.

## Fields

`full_name`, `location`, `email`, `phone`, `linkedin`, `website` — all
optional strings. `website` is a free-form URL (GitHub, portfolio, etc.).

## Storage — no migration

A new optional `contact` object inside the existing `sections` JSON blob on
`Profile.sections` (already a JSON column). Old profiles simply lack the key;
all fields default to empty strings.

**Schema change** (`profiles/schemas.py`):

```python
class ContactData(BaseModel):
    full_name: str = ""
    location: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    website: str = ""

class SectionsData(BaseModel):
    contact: ContactData = ContactData()
    summary: str = ""
    experience: list[ExperienceEntry] = []
    education: list[EducationEntry] = []
    skills: list[str] = []
```

## Parse and interview flows

- `_parse_sections` prompt (profiles/router.py): add `"contact"` to the
  required JSON shape with the six keys; the LLM extracts them from resume
  text. Missing values are empty strings.
- AI-interview synthesis prompt (`interview_finish`): same `"contact"` key.
- `_INTERVIEW_QUESTIONS`: add one question asking for name, city,
  email, phone, and LinkedIn/portfolio URLs.

## Docx output

`sections_to_text` (utils/profile_utils.py) emits, before the summary:

1. `{full_name}` as the first line
2. One contact line joined with ` • `:
   `location • email • phone • linkedin • website` (empty parts skipped)

No `generate_docx` changes: the first short line (≤60 chars, no `@`/URL)
already renders as the centered blue name; a following line matching
`_CONTACT_PATTERNS` (contains `@`, URL, or phone digits) renders as the
centered grey contact line.

Edge: if `full_name` is empty, the name line is skipped and the document
starts with the contact line (if any) or `Professional Summary` — the header
regex prevents it being mistaken for a name.

## Editor UI

`ProfileEditor.jsx`: new "Contact" section above Role/Profile Label —
six inputs in a 2-column grid (name and location, email and phone,
linkedin and website), state initialized from `initialSections.contact`,
included in the `onSave` sections payload.

`ProfileNewPage.jsx`: pass `contact: data.contact ?? {}` into
`setInitialSections` after parse; same in the interview `onComplete` handler.

## Error handling

- LLM omits `contact` key → Pydantic default supplies empty `ContactData`.
- Old saved profiles without `contact` → same default on read; the editor
  shows empty inputs.

## Testing

- Extend the docx verification: sections with contact → confirm the name
  paragraph is centered/bold and the contact line is centered/grey.
- `tests/test_profiles.py`: SectionsData round-trip with and without the
  `contact` key.
