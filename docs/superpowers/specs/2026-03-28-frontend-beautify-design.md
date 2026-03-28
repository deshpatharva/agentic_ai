# Frontend Beautification Design

**Date:** 2026-03-28
**Scope:** All 6 frontend screens — Landing, Auth (Login/Register), AppPage, Dashboard, JobMatches, Settings
**Direction:** Refined & Clean — polish the existing aesthetic without a style overhaul
**Approach:** Component-first — upgrade the design system, then pages inherit improvements

---

## Decisions Made

| Question | Answer |
|----------|--------|
| Design direction | Refined & Clean (polish existing, no style overhaul) |
| Scope | All 6 screens |
| Landing hero anchor | "How it works" 3-step card (Upload → Optimize → Download) |
| Motion | Subtle animations included (≤200ms, tasteful) |
| Implementation strategy | Component-first (Option A) |

---

## Design Tokens (tailwind.config.js)

Add to `theme.extend`:

```js
boxShadow: {
  card:    '0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.04)',
  lifted:  '0 4px 16px rgba(0,0,0,.10), 0 1px 4px rgba(0,0,0,.06)',
  primary: '0 4px 12px rgba(127,119,221,.35)',
},
transitionDuration: {
  DEFAULT: '150ms',
},
```

Add to `index.css`:
- Base `transition: color 150ms ease, background-color 150ms ease, box-shadow 150ms ease, transform 150ms ease` on interactive elements via `@layer base`
- Route fade: `.page-fade { animation: pageFade 150ms ease; } @keyframes pageFade { from { opacity: 0 } to { opacity: 1 } }`
- Custom scrollbar: thin, `#e5e7eb` track, `#c4c3dc` thumb

---

## Component Upgrades

### Button (`components/ui/Button.jsx`)
- Primary variant: `linear-gradient(135deg, #8b84e0, #7F77DD)` background, `shadow-primary` box-shadow
- All variants: `rounded-xl` (up from `rounded-lg`), `active:scale-95`, `transition-all`
- Focus ring: `focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-1`

### Card (`components/ui/Card.jsx`)
- `rounded-2xl` border-radius, `shadow-card` box-shadow, `border border-[#ebebeb]`
- Hover state: `hover:-translate-y-0.5 hover:shadow-lifted transition-all duration-200`
- Structured header: title + optional right-side slot, `border-b border-gray-100 pb-3 mb-4`

### ScoreCard (`components/ui/ScoreCard.jsx`)
- White background (`bg-white`), `shadow-card`, `border border-[#ebebeb]`
- Score number: `text-2xl font-extrabold`
- Status badge pill: `Good` (≥85, green), `Fair` (≥70, amber), `Low` (<70, red) — small pill top-right
- Progress bar: `linear-gradient(90deg, #7F77DD, #a78bfa)` for primary scores; green gradient for impact/skills
- Bar animation: `transition-[width] duration-[600ms] [transition-timing-function:cubic-bezier(.4,0,.2,1)]` — starts at `0%` on mount, animates to actual value via `useEffect`

### CircularProgress (`components/ui/CircularProgress.jsx`)
- Track color: `#f0f0f8` (slightly purple-tinted, not bare gray)
- Easing on `stroke-dashoffset`: `cubic-bezier(.4,0,.2,1)` for 0.6s (already has transition — just update easing)

### QuotaBar (`components/ui/QuotaBar.jsx`)
- Fill: `linear-gradient(90deg, #7F77DD, #a78bfa)`
- Track: `bg-gray-100`, height `h-2`, `rounded-full`
- Fill `transition-[width] duration-500 ease-out`

### PipelineStep (`components/ui/PipelineStep.jsx`)
- Replace dot + text with full-width row:
  - `done`: `bg-green-50` row, `bg-green-100` icon square (✓), `text-green-700` label, `bg-green-100 text-green-700` status pill
  - `running`: `bg-violet-50` row, `bg-violet-100` icon square (●), `text-violet-700` label, `bg-violet-100 text-violet-700` status pill
  - `pending`: plain row, `bg-gray-100` icon square, `text-gray-400` label, no pill
- Row `transition-colors duration-200`

### Badge (`components/ui/Badge.jsx`)
- Sharper colors: `free` → gray-100/gray-600, `pro` → violet-100/violet-700, `enterprise` → amber-100/amber-700
- Font: `font-semibold text-xs`

### Sidebar (`components/layout/Sidebar.jsx`)
- Active item: `border-l-2 border-primary bg-primary/10 text-primary` (remove solid `bg-primary`)
- Inactive hover: `hover:bg-white/5 hover:text-white`
- Transition: `transition-all duration-150` on each nav link

### AuthLayout (`components/layout/AuthLayout.jsx`)
- Left panel background: keep `bg-gradient-to-br from-primary to-primary-dark` but overlay a subtle SVG dot-grid pattern (`opacity-10`) for texture
- Feature grid cards: `bg-white/10 backdrop-blur-sm` (already there — add `hover:bg-white/15 transition-colors`)

---

## Page Changes

### Landing (`pages/Landing.jsx`)
- **Hero anchor**: Replace the empty space below CTAs with a `"How it works"` card:
  ```
  ┌─────────────────────────────────────────┐
  │  HOW IT WORKS                           │
  │                                         │
  │  [1]──────[2●]──────[3]                 │
  │  Upload  Optimize  Download             │
  │  Drop PDF  AI rewrites  Get your .docx  │
  └─────────────────────────────────────────┘
  ```
  Step 2 (active) has filled purple circle. Connectors are `linear-gradient(90deg, #7F77DD, #a78bfa)` lines at 40% opacity.
- CTA primary button: apply new Button gradient + `shadow-primary`
- Feature cards: use updated Card component (gains hover lift automatically)
- Pricing cards: use updated Card; highlight card keeps `bg-primary` variant

### AppPage (`pages/AppPage.jsx`)
- Upload zone: icon box `w-12 h-12 rounded-xl bg-violet-50 flex items-center justify-center` centered above text; dashed border color `border-violet-200` (up from `border-gray-200`)
- JD textarea: `focus:ring-2 focus:ring-primary/20` wrapper glow on focus
- Keyword pills: already correct — keep
- Run button: `w-full justify-center` + new Button primary (gains gradient + glow automatically)
- Score grid: uses updated ScoreCard (gains white card + gradient bar + status badge)
- Pipeline section: uses updated PipelineStep (gains colored rows)
- Live log: add `scrollbar-thin` class, keep dark `bg-gray-900` terminal style — no change needed

### Dashboard (`pages/Dashboard.jsx`)
- Stat cards: add colored icon box above the number:
  - Today's runs: `bg-violet-50` box, `text-violet-500` icon
  - Best score: `bg-green-50` box, `text-green-500` icon
  - Resumes optimized: `bg-violet-50` box, `text-violet-500` icon
  - Unread matches: `bg-amber-50` box, `text-amber-500` icon
- Sidebar: automatically improved via Sidebar component change
- Usage chart: no structural change; gains Card hover lift via component
- QuotaBar: gains gradient fill via component change
- Recent resumes table: add `hover:bg-gray-50 transition-colors` on `<tr>`

### Login / Register (`pages/Login.jsx`, `pages/Register.jsx`)
- No layout change — already solid split design
- Input `focus:ring-2 focus:ring-primary/30` already present — ensure consistent across both pages
- Submit button gains gradient + glow from Button component change

### JobMatches (`pages/JobMatches.jsx`)
- Job card: add match score mini-bar below company name:
  ```jsx
  <div className="flex items-center gap-2 mt-1">
    <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
      <div className="h-1.5 rounded-full bg-gradient-to-r from-primary to-violet-400"
           style={{ width: `${Math.round(m.similarity_score * 100)}%` }} />
    </div>
    <span className="text-xs font-bold text-primary">
      {Math.round(m.similarity_score * 100)}%
    </span>
  </div>
  ```
- Card gains hover lift from Card component
- Upsell (locked) screen: icon gets `bg-gray-100 p-4 rounded-2xl` wrapper for visual weight

### Settings (`pages/Settings.jsx`)
- Each `<Card>` section already uses Card component — gains hover lift automatically
- Card `header` prop renders as the structured header (title + divider) from Card upgrade
- Form inputs: add `transition-shadow duration-150 focus:shadow-[0_0_0_3px_rgba(127,119,221,.15)]` for a soft glow on focus

---

## Motion Summary

| Element | Property | Duration | Easing |
|---------|----------|----------|--------|
| Card hover lift | `transform`, `box-shadow` | 200ms | ease |
| Button hover | `box-shadow`, `background` | 150ms | ease |
| Button press | `transform: scale(.95)` | 150ms | ease |
| Score bar fill | `width` | 600ms | cubic-bezier(.4,0,.2,1) |
| Circular progress | `stroke-dashoffset` | 600ms | cubic-bezier(.4,0,.2,1) |
| Pipeline step bg | `background-color` | 200ms | ease |
| Upload zone border/bg | `border-color`, `background-color` | 150ms | ease |
| Sidebar nav item | `color`, `background` | 150ms | ease |
| Page entry | `opacity` 0→1 | 150ms | ease |
| Input focus glow | `box-shadow` | 150ms | ease |

---

## Files Changed

| File | Type of change |
|------|---------------|
| `frontend/tailwind.config.js` | Add shadow tokens |
| `frontend/src/index.css` | Base transitions, route fade, scrollbar |
| `frontend/src/components/ui/Button.jsx` | Gradient, shadow, scale, focus ring |
| `frontend/src/components/ui/Card.jsx` | Rounded-2xl, shadow-card, hover lift, structured header |
| `frontend/src/components/ui/ScoreCard.jsx` | White card, gradient bar, status badge, animated fill |
| `frontend/src/components/ui/CircularProgress.jsx` | Track color, easing |
| `frontend/src/components/ui/QuotaBar.jsx` | Gradient fill, transition |
| `frontend/src/components/ui/PipelineStep.jsx` | Full-row state design |
| `frontend/src/components/ui/Badge.jsx` | Sharper variant colors |
| `frontend/src/components/layout/Sidebar.jsx` | Left accent border, semi-transparent active |
| `frontend/src/components/layout/AuthLayout.jsx` | Dot-grid texture on left panel |
| `frontend/src/pages/Landing.jsx` | "How it works" hero card |
| `frontend/src/pages/AppPage.jsx` | Upload zone icon box, upload zone dashed border |
| `frontend/src/pages/Dashboard.jsx` | Stat card icon boxes, table row hover |
| `frontend/src/pages/Login.jsx` | Input focus consistency check |
| `frontend/src/pages/Register.jsx` | Input focus consistency check |
| `frontend/src/pages/JobMatches.jsx` | Match score bar on job cards, upsell icon wrapper |
| `frontend/src/pages/Settings.jsx` | Input focus glow |

**No new files. No route changes. No API changes. No state changes.**

---

## Out of Scope

- Dark mode
- Mobile-specific layout changes (existing responsive behavior preserved)
- Animation library (framer-motion, etc.) — all motion via Tailwind/CSS only
- New pages or features
- Backend changes
