# Frontend Redesign — Profile-First Architecture

**Date:** 2026-06-09
**Status:** Approved

## Overview

Redesign the resume-optimizer frontend around a "profile" concept. A profile stores a user's structured resume data (experience, education, skills) and is the source material for all optimization runs. The upload-per-run flow is replaced by a chat-based optimize page that matches JDs to stored profiles.

Four features delivered together:

- **(a) Onboarding** — post-signup prompt to create a first profile
- **(b) Profile creation** — upload+parse path and AI interview path, both converging on a bullet-level editor
- **(c) Chat Optimize** — replaces AppPage; user pastes JD or job URL, system matches profiles, pipeline runs with chat narration and user instructions
- **(d) Profiles page** — expandable accordion cards with inline bullet-level editing

---

## Data Model

### New: `profiles` table

```sql
profiles (
  id               UUID PRIMARY KEY,
  user_id          UUID REFERENCES users(id),
  label            VARCHAR(100),          -- "Web Developer", "Data Engineer"
  label_confirmed  BOOLEAN DEFAULT false, -- has user confirmed AI-suggested label?
  raw_text         TEXT,                  -- original parsed text (kept for re-parsing)
  sections         JSONB,                 -- structured resume data (see below)
  created_at       TIMESTAMP,
  updated_at       TIMESTAMP
)
```

`sections` JSONB shape:

```json
{
  "summary": "Senior frontend engineer with 4 years React experience…",
  "experience": [
    {
      "company": "Acme Corp",
      "title": "Senior Frontend Developer",
      "dates": "2021–2024",
      "bullets": [
        "Led migration to React 18",
        "Improved load time by 40%",
        "Mentored 3 junior developers"
      ]
    }
  ],
  "education": [
    {
      "institution": "MIT",
      "degree": "B.S. Computer Science",
      "dates": "2015–2019"
    }
  ],
  "skills": ["React", "TypeScript", "Node.js", "AWS", "Docker"]
}
```

### Updated: `resumes` table

Add nullable foreign key so each optimization output references the profile it was built from:

```sql
ALTER TABLE resumes ADD COLUMN profile_id UUID REFERENCES profiles(id);
```

Existing rows are unaffected (column is nullable).

### New: `jd_scrape_cache` table

```sql
jd_scrape_cache (
  url_hash   CHAR(64) PRIMARY KEY,  -- SHA-256 of the URL
  jd_text    TEXT,
  scraped_at TIMESTAMP
)
```

Scrapes are cached for 24 hours. Same URL within 24h returns cached text without re-scraping.

---

## Routes

| Route | Page | Status |
|---|---|---|
| `/dashboard` | Dashboard (+ onboarding banner for new users) | updated |
| `/optimize` | Chat Optimize — default landing after login | **new** |
| `/app` | Redirect → `/optimize` | redirect |
| `/profiles` | Profile list (expandable cards) | **new** |
| `/profiles/new` | Create profile — upload or AI interview | **new** |
| `/profiles/:id` | Redirect → `/profiles` (no separate detail page; editing is inline) | redirect |
| `/dashboard/resumes` | Optimization output history | unchanged |
| `/dashboard/settings` | Settings | unchanged |

### Sidebar navigation (updated order)

1. Optimize ← default active
2. Profiles ← new
3. Dashboard
4. Resumes
5. Settings

---

## Feature (a) — Onboarding

New users land on `/optimize` after signup. The Dashboard shows a dismissible banner:

> "Welcome! Create your first profile to start optimizing."
> **[Upload resume]** **[Start from scratch]**

- Both buttons navigate to `/profiles/new`
- Dismissed state stored in `localStorage` (`onboarding_dismissed: true`)
- Banner does not block access to any page

---

## Feature (b) — Profile Creation (`/profiles/new`)

Single page with both paths side by side. User picks one; both converge at the same profile editor before saving.

### Upload path

1. Drop or browse PDF/DOCX → `POST /upload` (existing endpoint) → returns `job_id` + parsed `text`
2. `POST /profile/parse` → LLM converts raw text to structured `sections` JSON
3. Profile editor shown (see Editor section below)
4. User confirms label and edits
5. `POST /profiles` → saves profile → navigate to `/profiles`

### AI Interview path

1. Chat interface opens; AI asks questions one at a time (~6–10 questions):
   - Most recent role + company + dates
   - Key responsibilities (3–5 bullets)
   - Previous roles (abbreviated)
   - Education
   - Skills
2. Each user response is sent to `POST /profile/ai-interview/message` (stateless — full history in request body)
3. When interview complete, `POST /profile/ai-interview/finish` synthesizes conversation → `sections` JSON
4. Same profile editor shown as upload path
5. Same save flow

### Profile editor (shared by both paths)

- **Label row:** editable text input, pre-filled by AI; badge shows "AI suggested" until user edits
- **Experience section:** each job is a card — company, title, dates; bullets are inline-editable (click pencil to edit in place, ✕ to remove); "+ Add bullet"; "+ Add job"
- **Education section:** same pattern
- **Skills section:** tag chips with ✕ to remove; "+ Add skill" chip
- **Summary:** single textarea
- **Save Profile** button → `POST /profiles`

---

## Feature (c) — Chat Optimize (`/optimize`)

Default page after login. Single chat window — no side panel.

### Flow

1. User pastes a job URL or JD text directly into the chat input
2. If URL detected: `POST /jd/scrape` fetches and caches the JD text; system replies with job title confirmation
3. `POST /analyze-jd` extracts keywords
4. `POST /profile/match` ranks user's profiles against the JD → system replies with up to 3 profile cards showing label, key skills, and match %
5. User selects a profile (clicks card or types response) and optionally gives instructions ("emphasize Python", "make it more senior")
6. `POST /run-pipeline` called with `profile_id` + `jd_text` + optional instruction string
7. SSE stream narrates progress in chat bubbles: stages, iteration count, keyword hits
8. User can send additional instructions mid-run; these are queued and passed to the optimizer agent
9. On completion: download button appears as a chat message

### Profile matching

`POST /profile/match` receives the JD text and runs a real-time comparison of the user's profiles:
- AI-suggested label vs JD role title (semantic)
- Skills overlap between profile sections and JD keywords
- Returns ranked list with a `match_pct` (0–100)

### JD URL scraping (`POST /jd/scrape`)

- Generic HTTP fetch + HTML parser; extracts main content (targets common job board patterns: LinkedIn, Indeed, Glassdoor, Lever, Greenhouse, and generic `<article>` / `<main>` extraction as fallback)
- 24h cache keyed on SHA-256 of URL
- Returns `{ jd_text, source_url, job_title }` (job_title extracted if detectable)

---

## Feature (d) — Profiles Page (`/profiles`)

Accordion list of all user profiles.

### Collapsed card (default)

- Role emoji icon + label + top 3 skills + years experience summary
- "Used N×" count
- ▾ chevron to expand

### Expanded card

- Editable label input (AI-suggested badge until user edits)
- Experience: each job expandable — company, title, dates; bullet-level inline edit (pencil / ✕ per bullet; "+ Add bullet"; "+ Add job")
- Education: same pattern
- Skills: editable chip tags
- **Save changes** button → `PUT /profiles/:id`
- **Delete profile** button → `DELETE /profiles/:id` (with confirmation)

Only one card is expanded at a time (others collapse when a new one opens).

---

## Backend Endpoints

### New endpoints

| Method | Route | Purpose |
|---|---|---|
| POST | `/profile/parse` | Raw resume text → structured `sections` JSON (LLM) |
| POST | `/profile/ai-interview/message` | One interview turn — stateless, history in body |
| POST | `/profile/ai-interview/finish` | Synthesize full conversation → `sections` JSON |
| POST | `/profiles` | Create profile |
| GET | `/profiles` | List user's profiles |
| GET | `/profiles/:id` | Get profile with full sections |
| PUT | `/profiles/:id` | Update label and/or sections |
| DELETE | `/profiles/:id` | Delete profile |
| POST | `/profile/match` | JD text → ranked profiles with `match_pct` |
| POST | `/jd/scrape` | URL → JD text (generic scraper, 24h cache) |

### Updated endpoints

| Method | Route | Change |
|---|---|---|
| POST | `/run-pipeline` | Accepts optional `profile_id`; when provided, reconstructs resume text from profile sections instead of using stored upload text |

---

## Frontend Components

### New pages
- `ProfilesPage` — accordion list (`/profiles`)
- `ProfileNewPage` — unified create page with upload + interview paths (`/profiles/new`)
- `ProfileEditor` — shared editor component used by both creation paths
- `ChatOptimizePage` — chat window with JD input and pipeline narration (`/optimize`)

### New components
- `ProfileCard` — expandable accordion card (used in `ProfilesPage`)
- `BulletEditor` — inline-editable bullet with pencil/remove controls
- `SkillChips` — tag chip list with add/remove
- `ChatMessage` — single chat bubble (system or user)
- `ProfileMatchCard` — compact profile card shown inside chat with match %
- `InterviewChat` — AI interview chat UI (used in `ProfileNewPage`)

### Modified
- `Sidebar` — updated nav order; "Optimize" first
- `Dashboard` — adds `OnboardingBanner` component
- `App.jsx` / router — new routes + `/app` redirect

---

## Error Handling

- **Scrape fails:** system replies in chat "Couldn't fetch that URL — please paste the job description directly."
- **No profiles exist when user opens `/optimize`:** chat greets with "You don't have any profiles yet. [Create one →]"
- **Profile parse returns empty sections:** show raw text editor fallback with "We couldn't fully parse this — edit manually below."
- **Pipeline fails mid-run:** SSE error event shows in chat as error bubble; download button does not appear

---

## Out of Scope

- Resume comparison between versions
- Sharing profiles between users
- Profile templates
- Bulk import of multiple resumes at once
