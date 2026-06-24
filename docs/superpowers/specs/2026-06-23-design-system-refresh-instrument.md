# Design System Refresh — "Instrument, restrained"

**Date:** 2026-06-23
**Status:** Approved — ready for implementation plan
**Scope:** Frontend design-system refresh (`resume-optimizer/frontend`)

## Summary

Replace the current **"Manila & Ink"** visual identity (cream paper, Fraunces serif,
editorial green) with **"Instrument, restrained"** — a near-monochrome, instrument-grade
look where a single accent appears only as *signal*. The product is a multi-agent resume
optimizer (extract facts → analyze JD → rewrite → humanize → score → verify →
fabrication-guard); the new identity should read as a precision career-intelligence tool,
not a literary publication.

The change is a **personality swap on top of the existing token architecture**, not a
rebuild. The app's CSS-variable token system, light/dark toggle, and ~95% of component
markup stay intact. Most of the refresh flows through CSS variables, the Tailwind config,
and the font links; a small number of components need targeted edits.

### Why
The old system sits on top of the most common AI-default look (warm cream + high-contrast
serif + editorial accent). Reference site [tsenta.com](https://tsenta.com) — a clean,
near-monochrome, instrument-like competitor in the same job-search space — informed a
more restrained, neutral direction.

## Direction: "Instrument, restrained"

Career-instrument bones (gauge/readout signature, technical type) with Tsenta-borrowed
discipline: **near-monochrome UI, one accent used only as signal.**

### The accent rule (the heart of the direction)
Teal (`--c-accent`) appears **only** on: primary CTAs, active nav/tabs, focus rings,
links, and score/gauge fills. Everything else is grayscale. Amber (`--c-hilite`) is
demoted to **rare attention-only** use (e.g. "not yet evidenced" warnings, score
highlights). This restraint is what distinguishes the look from a generic colorful
dashboard.

### Self-critique vs. AI defaults
- **Risk:** near-black + teal could drift toward the "black + one acid accent" default.
  **Mitigations:** teal is a cyan-teal (`#2DD4BF`), not lime/acid; base is graphite
  (`#0E1014`), not pure black; full light mode retained; personality lives in the
  typographic + gauge system, not a glow. Texture and decorative shadows are removed.
- The old light mode *was* the cream-serif default; the new neutral near-white light mode
  retires it.

## Color tokens

RGB triplets live in `src/index.css` (so Tailwind keeps `<alpha-value>` support).
Tailwind semantic names in `tailwind.config.js` are unchanged — only the underlying
values change.

### Dark (canonical) — neutral graphite, no blue cast

| token | value | role |
|---|---|---|
| `--c-bg` | `14 16 20` (#0E1014) | near-black graphite page |
| `--c-surface` | `23 26 31` (#171A1F) | cards / panels |
| `--c-surface-2` | `32 36 42` (#20242A) | fills, hovers |
| `--c-ink` | `233 236 240` (#E9ECF0) | text |
| `--c-ink-mute` | `154 161 170` (#9AA1AA) | secondary (neutral gray) |
| `--c-ink-faint` | `106 112 120` (#6A7078) | tertiary |
| `--c-line` | `38 42 48` (#262A30) | hairlines / gauge tracks |
| `--c-accent` | `45 212 191` (#2DD4BF) | signal teal — only everyday color |
| `--c-accent-strong` | `94 234 212` (#5EEAD4) | hover |
| `--c-accent-soft` | `17 43 41` (#112B29) | teal tint bg |
| `--c-hilite` | `234 179 8` (#EAB308) | amber — rare attention only |
| `--c-hilite-soft` | `41 33 12` (#29210C) | amber tint bg |
| `--c-err` | `239 109 100` (#EF6D64) | error |
| `--c-err-soft` | `51 28 26` (#331C1A) | error tint bg |

### Light (derived) — clean near-white, neutral (not cream)

| token | value | role |
|---|---|---|
| `--c-bg` | `248 249 250` (#F8F9FA) | near-white page |
| `--c-surface` | `255 255 255` (#FFFFFF) | cards |
| `--c-surface-2` | `241 243 245` (#F1F3F5) | fills, hovers |
| `--c-ink` | `17 20 24` (#111418) | text |
| `--c-ink-mute` | `90 97 105` (#5A6169) | secondary |
| `--c-ink-faint` | `138 145 152` (#8A9198) | tertiary |
| `--c-line` | `228 231 234` (#E4E7EA) | hairlines |
| `--c-accent` | `13 148 136` (#0D9488) | deep teal (AA on white) |
| `--c-accent-strong` | `15 118 110` (#0F766E) | hover |
| `--c-accent-soft` | `224 244 241` (#E0F4F1) | teal tint bg |
| `--c-hilite` | `161 98 7` (#A16207) | amber (AA on white) |
| `--c-hilite-soft` | `248 240 224` (#F8F0E0) | amber tint bg |
| `--c-err` | `198 56 47` (#C6382F) | error |
| `--c-err-soft` | `250 233 231` (#FAE9E7) | error tint bg |

### Shadows
Lean on **hairline borders over shadows**. Card/lifted shadows become subtle; the old
accent *glow* shadow is removed (or reduced to a faint, near-invisible value). Update
`--shadow-card`, `--shadow-lifted`, `--shadow-accent` accordingly in both modes.

## Typography

| role | family | replaces |
|---|---|---|
| Display (h1/h2, big score) | **Space Grotesk** (500/700) | Fraunces |
| Body | **Inter** (400/500/600/700) | Archivo |
| Data / eyebrows / mono | **JetBrains Mono** (400/600) | kept, role promoted |

- `index.html` Google Fonts link swaps Fraunces→Space Grotesk and Archivo→Inter; keeps
  JetBrains Mono.
- `tailwind.config.js` `fontFamily.display` → Space Grotesk, `fontFamily.sans` → Inter.
- `index.css` `body` font → Inter; `@layer base` `h1, h2` font → Space Grotesk.
- Personality comes from Space Grotesk + the promoted mono usage (scores, deltas,
  uppercase eyebrows), not the body face.

## Shape & texture
- **Remove** the paper-grain `body::before` texture entirely (no replacement texture —
  clean surfaces).
- Border radius tightens: `DEFAULT 6px`, `card 8px` (from 8/10) in `tailwind.config.js`.
- Keep custom scrollbar, page-fade, reveal, typing, msg-in, stage-pulse keyframes;
  retune any color references to tokens.

## Signature: the instrument readout
The two pieces that carry the thesis, restyled near-monochrome with teal only on fills /
active nodes:

- **`ScoreReveal.jsx`** — big Space Grotesk score with a mono delta readout
  (e.g. `72 → 91`); sub-scores as labeled horizontal **gauges** with mono values.
- **`PipelineProgress.jsx`** — stages as a segmented **gauge track** with mono stage
  labels + live status line. **Fix the hardcoded** active-stage glow
  (`shadow-[0_0_0_3px_rgba(26,107,82,0.15)]`) → token-based teal.

## Components to touch
All are already token-driven, so most update automatically. Targeted edits:

- `src/components/ui/Button.jsx` — verify primary contrast in both modes
  (`dark:text-ink` on teal already handled); tighten focus ring to teal; radius via token.
- `src/components/ui/Card.jsx` — reduce hover lift, rely on border; radius via token.
- `src/components/ui/Badge.jsx` — re-map variants to new palette; teal for `pro`,
  amber for `enterprise`, keep grayscale defaults.
- `src/components/ui/QuotaBar.jsx` — fill = teal (already token-driven; verify).
- `src/components/ui/ThemeToggle.jsx` — inherits; no change expected.
- `src/components/ScoreReveal.jsx`, `src/components/PipelineProgress.jsx` — signature
  restyle + de-hardcode (see above).

## Files changed (summary)
- `index.html` — font links
- `src/index.css` — tokens (both modes), body font, base h1/h2 font, remove texture,
  shadow values, keyframe color references
- `tailwind.config.js` — `fontFamily` (display/sans), `borderRadius`, shadow/glow tokens
- `src/components/ui/{Button,Card,Badge,QuotaBar}.jsx` — token-driven tweaks
- `src/components/{ScoreReveal,PipelineProgress}.jsx` — signature restyle + de-hardcode
- `src/theme.js` — **untouched** (logic only)

## Out of scope (this pass)
- **Landing page rebuild** — deferred to a follow-up spec (see below).
- Page-by-page redesign of Dashboard, Chat, Profiles, admin — they inherit tokens.

## Known debt to address while refreshing
- `src/pages/Landing.jsx` hardcodes ~15 old Manila/Ink hex values in the Pricing band
  (`#1E1A15`, `#1A6B52`, `#D9A03F`, `#4DB892`, etc.). These will **not** follow the new
  tokens. Minimum: migrate the Pricing band's hardcoded colors to tokens so the page
  isn't visually broken after the refresh. (Full Landing rebuild is the follow-up.)

## Follow-up (separate spec, after this lands)
**Landing rebuild**, informed by Tsenta's structure but reflecting *our* product
(optimize/score, not auto-apply). Missing sections to add:
1. Real product preview (score reveal + pipeline) in/under hero, replacing abstract
   `HeroVisual`.
2. Social proof (logo strip / stats row).
3. "How it works" built on the real 5–7 stage pipeline (not the generic 3-step).
4. FAQ section.
5. Final CTA band.
6. Real footer (multi-column + links).

## Acceptance criteria
- New tokens applied in both light and dark; no remaining references to old Manila/Ink
  hex values outside intentionally-migrated spots.
- Fonts load: Space Grotesk, Inter, JetBrains Mono; Fraunces/Archivo removed from
  `index.html`.
- Accent discipline holds: teal only on CTAs/active/focus/links/gauges; amber rare.
- `PipelineProgress` hardcoded glow removed; Landing Pricing band uses tokens.
- Light/dark toggle still works; `prefers-reduced-motion` and keyboard focus preserved.
- App builds and runs; signature pieces (ScoreReveal, PipelineProgress) render correctly
  in both modes.
