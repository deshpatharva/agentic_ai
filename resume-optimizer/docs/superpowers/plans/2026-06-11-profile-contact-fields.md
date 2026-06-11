# Profile Contact Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add name/location/email/phone/linkedin/website contact fields to profiles so generated resume docs render the centered name + contact header.

**Architecture:** Contact data lives as an optional `contact` object inside the existing `Profile.sections` JSON column (no DB migration). The parse/interview LLM prompts extract it, `sections_to_text` emits it as the first two lines, and `generate_docx` already styles those lines (centered blue name, centered grey contact). The frontend editor gains a Contact section.

**Tech Stack:** FastAPI + Pydantic v2, python-docx, React (Vite), pytest.

**Spec:** `resume-optimizer/docs/superpowers/specs/2026-06-11-profile-contact-fields-design.md`

**Working directory for all backend commands:** `c:\Users\deshp\Documents\github_repo\agentic_ai\resume-optimizer` (the venv lives at `.venv\` inside it).

---

### Task 0: Install test dependencies into the local venv

pytest is not installed in `.venv` (CI installs it separately). One-time setup.

- [ ] **Step 1: Install pytest + helpers**

Run from `resume-optimizer/`:
```powershell
.venv\Scripts\python.exe -m pip install pytest pytest-asyncio aiosqlite httpx
```
Expected: `Successfully installed ...` (or already satisfied).

- [ ] **Step 2: Confirm collection works**

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_profiles.py --collect-only -q
```
Expected: lists 9 tests, exit code 0. No commit (no repo changes).

---

### Task 1: ContactData schema

**Files:**
- Modify: `backend/profiles/schemas.py`
- Test: `backend/tests/test_contact_fields.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_contact_fields.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_contact_fields.py -v
```
Expected: 2 FAILED — `SectionsData` has no field `contact` (ValidationError or AttributeError).

- [ ] **Step 3: Implement ContactData**

In `backend/profiles/schemas.py`, change the import line and add `ContactData` above `SectionsData`, then add the field:

```python
from typing import Optional
from pydantic import BaseModel, Field


class ContactData(BaseModel):
    full_name: str = ""
    location: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    website: str = ""
```

And in `SectionsData` add the first field:

```python
class SectionsData(BaseModel):
    contact: ContactData = Field(default_factory=ContactData)
    summary: str = ""
    experience: list[ExperienceEntry] = []
    education: list[EducationEntry] = []
    skills: list[str] = []
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_contact_fields.py -v
```
Expected: 2 PASSED.

- [ ] **Step 5: Run existing profile tests for regressions**

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_profiles.py -v
```
Expected: `test_parse_profile_endpoint` FAILS — it is stale (still posts JSON to the now-multipart endpoint; fixed in Task 3). All other tests PASS. If anything else fails, stop and investigate.

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/profiles/schemas.py resume-optimizer/backend/tests/test_contact_fields.py
git commit -m "feat(profiles): add ContactData schema inside sections JSON"
```

---

### Task 2: sections_to_text emits name + contact lines

**Files:**
- Modify: `backend/utils/profile_utils.py`
- Test: `backend/tests/test_contact_fields.py`

- [ ] **Step 1: Write the failing tests** (append to `test_contact_fields.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_contact_fields.py -v
```
Expected: the 2 Task-1 tests PASS, the 3 new ones FAIL (first line is "Professional Summary").

- [ ] **Step 3: Implement**

In `backend/utils/profile_utils.py`, insert at the top of `sections_to_text`, right after `parts = []`:

```python
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
```

Also update the docstring's line-structure list to mention the name and
contact lines.

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_contact_fields.py -v
```
Expected: 5 PASSED.

- [ ] **Step 5: Add docx end-to-end render test** (append to `test_contact_fields.py`)

```python
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
```

- [ ] **Step 6: Run all contact tests**

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_contact_fields.py -v
```
Expected: 6 PASSED. (The docx test passes without generator changes — `_is_name_line` matches the short first line and `_CONTACT_PATTERNS` matches the `@`/digits line. If it fails, the generator heuristics are off — investigate, do not patch the test.)

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/utils/profile_utils.py resume-optimizer/backend/tests/test_contact_fields.py
git commit -m "feat(profiles): emit name and contact header lines in sections_to_text"
```

---

### Task 3: LLM prompts extract contact; fix stale parse test

**Files:**
- Modify: `backend/profiles/router.py`
- Test: `backend/tests/test_profiles.py`

- [ ] **Step 1: Update the parse prompt**

In `backend/profiles/router.py` → `_parse_sections`, replace the JSON shape block inside the prompt string so it reads:

```python
    prompt = f"""You are a resume parser. Extract structured data from the resume text below.
Return ONLY valid JSON with this exact shape:
{{
  "label": "<job title / role>",
  "contact": {{
    "full_name": "<person's full name or empty string>",
    "location": "<city, state/country or empty string>",
    "email": "<email or empty string>",
    "phone": "<phone or empty string>",
    "linkedin": "<linkedin url or empty string>",
    "website": "<github/portfolio/other url or empty string>"
  }},
  "summary": "<professional summary or empty string>",
  "experience": [
    {{"company": "", "title": "", "dates": "", "bullets": ["..."]}}
  ],
  "education": [
    {{"institution": "", "degree": "", "dates": ""}}
  ],
  "skills": ["skill1", "skill2"]
}}

Resume text:
{raw_text[:8000]}"""
```

- [ ] **Step 2: Update the interview synthesis prompt**

In `interview_finish`, replace the required JSON shape in the prompt with:

```python
    prompt = f"""You are given a resume interview transcript. Extract structured resume data and return ONLY valid JSON.

Required JSON shape:
{{
  "label": "concise job title",
  "contact": {{"full_name": "...", "location": "...", "email": "...", "phone": "...", "linkedin": "...", "website": "..."}},
  "summary": "one-paragraph professional summary",
  "experience": [{{"company": "...", "title": "...", "dates": "...", "bullets": ["..."]}}],
  "education": [{{"institution": "...", "degree": "...", "dates": "..."}}],
  "skills": ["Skill1", "Skill2"]
}}

Use empty strings for contact fields the candidate did not provide.

Interview transcript:
{history_text}"""
```

- [ ] **Step 3: Add the contact interview question**

In `_INTERVIEW_QUESTIONS`, insert as the FIRST element:

```python
    "First, what's your full name, the city you're based in, and the best email, phone, and LinkedIn (or portfolio URL) to put on your resume?",
```

- [ ] **Step 4: Fix the stale parse endpoint test**

In `backend/tests/test_profiles.py`, replace `test_parse_profile_endpoint` entirely with:

```python
@pytest.mark.asyncio
async def test_parse_profile_endpoint(client, monkeypatch):
    token = await _register_and_token(client, "parse@test.com")

    import profiles.router as pr

    monkeypatch.setattr(
        pr, "_extract_file_text", lambda contents, filename: "Fake resume text here"
    )

    async def _fake_parse(raw_text: str) -> dict:
        return {
            "label": "Software Engineer",
            "contact": {"full_name": "Jane Doe", "location": "", "email": "",
                        "phone": "", "linkedin": "", "website": ""},
            "summary": "Parsed summary",
            "experience": [],
            "education": [],
            "skills": ["Python"],
        }
    monkeypatch.setattr(pr, "_parse_sections", _fake_parse)

    r = await client.post(
        "/profile/parse",
        files={"file": ("resume.docx", b"PK\x03\x04 fake docx bytes", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["label"] == "Software Engineer"
    assert data["contact"]["full_name"] == "Jane Doe"
    assert data["raw_text"] == "Fake resume text here"
```

- [ ] **Step 5: Run the profile test suite**

```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_profiles.py backend\tests\test_contact_fields.py -v
```
Expected: all PASS (the previously stale test now passes too).

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/profiles/router.py resume-optimizer/backend/tests/test_profiles.py
git commit -m "feat(profiles): extract contact fields in parse/interview prompts; fix stale multipart test"
```

---

### Task 4: Frontend — contact inputs in ProfileEditor, passthrough in ProfileNewPage

**Files:**
- Modify: `frontend/src/components/ProfileEditor.jsx`
- Modify: `frontend/src/pages/ProfileNewPage.jsx`

- [ ] **Step 1: Add contact state to ProfileEditor**

In `ProfileEditor.jsx`, after the `skills` useState (line ~13), add:

```jsx
  const [contact, setContact] = useState({
    full_name: '', location: '', email: '', phone: '', linkedin: '', website: '',
    ...(initialSections.contact || {}),
  });

  const updateContact = (patch) => setContact((prev) => ({ ...prev, ...patch }));
```

Update `handleSave` to include contact:

```jsx
  const handleSave = () => {
    onSave({ label, labelConfirmed, sections: { contact, summary, experience, education, skills } });
  };
```

- [ ] **Step 2: Add the Contact section UI**

Insert directly ABOVE the `{/* Label */}` block inside the returned `<div className="space-y-6">`:

```jsx
      {/* Contact */}
      <div>
        <label className={sectionLabel}>Contact</label>
        <div className="grid grid-cols-2 gap-3">
          <input className={fieldClass} placeholder="Full name"
            value={contact.full_name}
            onChange={(e) => updateContact({ full_name: e.target.value })} />
          <input className={fieldClass} placeholder="Location (e.g. Cincinnati, OH)"
            value={contact.location}
            onChange={(e) => updateContact({ location: e.target.value })} />
          <input className={fieldClass} placeholder="Email" type="email"
            value={contact.email}
            onChange={(e) => updateContact({ email: e.target.value })} />
          <input className={fieldClass} placeholder="Phone"
            value={contact.phone}
            onChange={(e) => updateContact({ phone: e.target.value })} />
          <input className={fieldClass} placeholder="LinkedIn URL"
            value={contact.linkedin}
            onChange={(e) => updateContact({ linkedin: e.target.value })} />
          <input className={fieldClass} placeholder="Website / GitHub URL"
            value={contact.website}
            onChange={(e) => updateContact({ website: e.target.value })} />
        </div>
      </div>
```

- [ ] **Step 3: Pass contact through in ProfileNewPage**

In `ProfileNewPage.jsx` → `handleParseResume`, update `setInitialSections` to:

```jsx
      setInitialSections({
        contact: data.contact ?? {},
        summary: data.summary ?? '',
        experience: data.experience ?? [],
        education: data.education ?? [],
        skills: data.skills ?? [],
      });
```

And in the `InterviewChat onComplete` handler:

```jsx
                onComplete={(sections) => {
                  setInitialLabel(sections.label || '');
                  setInitialSections({
                    contact: sections.contact || {},
                    summary: sections.summary || '',
                    experience: sections.experience || [],
                    education: sections.education || [],
                    skills: sections.skills || [],
                  });
                  setView('editor');
                }}
```

- [ ] **Step 4: Build the frontend**

Run from `resume-optimizer/frontend/`:
```powershell
npm run build
```
Expected: build succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/frontend/src/components/ProfileEditor.jsx resume-optimizer/frontend/src/pages/ProfileNewPage.jsx
git commit -m "feat(profiles): contact fields section in profile editor"
```

---

### Task 5: Full regression run and push

- [ ] **Step 1: Run the backend test suite**

From `resume-optimizer/`:
```powershell
.venv\Scripts\python.exe -m pytest backend\tests\test_profiles.py backend\tests\test_contact_fields.py backend\tests\test_profiles_models.py -v
```
Expected: all PASS. (Full suite runs in CI; these are the files this feature touches.)

- [ ] **Step 2: Push**

```bash
git push origin features/update_ui
```

- [ ] **Step 3: Verify CI passes on the PR before merging.**
