# Landing Page Rebuild — Design Spec

**Date:** 2026-06-23
**Status:** Approved — ready for implementation plan
**Scope:** Rebuild `resume-optimizer/frontend/src/pages/Landing.jsx` and add focused section components.
**Depends on:** `2026-06-23-design-system-refresh-instrument.md` (Instrument tokens already shipped).

## Summary

Rebuild the marketing Landing page so it actually shows what the product does, using the
new "Instrument, restrained" design system. The current page has only Hero + a generic
3-step + Features + Pricing. The rebuild replaces the abstract hero visual with a real
product preview, adds an honest stats row, a real-pipeline "how it works", an FAQ, a final
CTA band, and a multi-column footer. Structure is informed by [tsenta.com](https://tsenta.com)
but the content reflects *our* product (optimize/score a resume — not auto-apply).

**Honesty constraints (hard):**
- No fabricated customer/hiring-company logos. Social proof is product-true metrics only.
- Footer links point only to routes that exist (`/`, `/login`, `/register`, on-page
  anchors). Legal links are placeholders (`#`), not fake pages.
- Copy describes what the product genuinely does; the fabrication guard is the honest
  differentiator and may be emphasized.

## Page structure (top → bottom)

1. `TopNav` (existing, unchanged)
2. **Hero** — headline + sub + CTAs (left) · **product preview** (right)
3. **Stats row** — honest metrics
4. **How it works** — the real pipeline (6 steps)
5. **Pricing** (existing section, already token-migrated — keep as-is)
6. **FAQ**
7. **Final CTA band**
8. **Footer** (multi-column)

## Components (new, under `src/components/landing/`)

Each is a focused, presentational, prop-light unit. `Landing.jsx` becomes a thin
composition of `TopNav` + these + the existing Pricing block.

### `HeroPreview.jsx`
Static instrument card reusing the gauge/score visual language (NOT wired to live data).
Shows:
- a score readout `72 → 91` (Space Grotesk number + mono delta),
- 3–4 labeled sub-score gauges (ATS, Impact, Skills Gap, JD Tailoring) with mono values,
- a compact pipeline track (reuse the segmented-track styling from `PipelineProgress`).
No props required (self-contained mock). Replaces `HeroVisual` in the hero.

### `StatsRow.jsx`
A responsive row of honest, product-true stats. Content:
- `5` — scoring dimensions (ATS · Impact · Skills Gap · Readability · JD Tailoring)
- `Fabrication-guarded` — never invents experience
- `Iterative` — refines until the score stops climbing
- `3 sources` — Adzuna · RemoteOK · The Muse
Data lives in a local array in the component. No props.

### `HowItWorks.jsx`
The actual pipeline as a numbered sequence (numbering is meaningful here — it IS an
ordered process). Steps:
1. **Analyze the JD** — pull keywords, must-haves, and signals from the posting
2. **Score your resume** — ATS, impact, skills-gap, readability, JD-tailoring
3. **Rewrite & tailor** — align bullets to what the role asks for
4. **Humanize** — natural phrasing, not robotic keyword stuffing
5. **Verify & guard** — every claim checked against your real history; never fabricated
6. **Generate** — a clean `.docx` / `.pdf`, ready to send
Steps live in a local array. No props.

### `FAQ.jsx`
Accordion (or simple stacked) Q&A. Use native `<details>/<summary>` for zero-JS
accessibility, styled with tokens. Questions:
- "Does it make up experience I don't have?" → No — a fabrication guard checks every
  rewritten claim against your real history.
- "What file formats can I use?" → Upload PDF or DOCX; download optimized DOCX or PDF.
- "How is the score calculated?" → Five dimensions: ATS match, impact, skills gap,
  readability, and JD tailoring.
- "Is my data private?" → Your resume is used only to optimize your documents.
- "Is there a free tier?" → Yes — start free, no card required.
Q&A pairs live in a local array. No props.

### `FinalCTA.jsx`
A closing band: short headline + "Get started free" CTA → `/register`. Uses a token
accent-soft / surface band consistent with the restrained palette (no fixed hex).

### `SiteFooter.jsx`
Multi-column footer. Columns:
- **Product:** Features (anchor `#how-it-works`), Pricing (anchor `#pricing`), Sign in
  (`/login`), Get started (`/register`)
- **Company:** About (`#`), Blog (`#`) — placeholders, clearly non-functional for now
- **Legal:** Privacy (`#`), Terms (`#`) — placeholders
- Tagline + the honest "Powered by Gemini · Groq · Anthropic" line already used in the
  hero badge.
No props.

## `Landing.jsx` (rewrite)
Thin composition. Keeps the existing `features`/`plans` data only where still used (Pricing
keeps `plans`; the old `features`/`steps` arrays move into / are replaced by the new
section components). Adds `id` anchors: `#how-it-works`, `#pricing`, `#faq` for nav/footer
links. Removes the `HeroVisual` import and its usage.

## Retired / cleanup
- `HeroVisual` is used only by `Landing.jsx`; `HeroScene` (three.js, ~820kB chunk) is used
  only via the hero. After the rebuild both are unused. **Delete** `src/components/HeroVisual.jsx`
  and `src/components/three/HeroScene.jsx` (and remove any now-dead `three` usage) so the
  820kB chunk drops from the build. Verify no other importers before deleting.

## Visual direction
Follows the shipped Instrument system: near-monochrome surfaces, teal accent only on
CTAs/active/gauges/links, Space Grotesk display + Inter body + JetBrains Mono for
numbers/eyebrows. Sections separated by `border-line` hairlines rather than heavy bands.
Respect `prefers-reduced-motion`; keep keyboard focus rings.

## Acceptance criteria
- Landing renders all sections in order; light + dark both correct.
- Hero shows the product preview (gauges + score delta), not the 3D scene.
- No fabricated logos; stats row shows only the metrics above.
- "How it works" lists the six real pipeline steps including the fabrication guard.
- FAQ is keyboard-accessible; footer links resolve to real routes or are clearly
  placeholder (`#`).
- `HeroVisual` and `HeroScene` deleted; `grep -rn "HeroVisual\|HeroScene" src/` returns
  nothing; build no longer emits the large three.js chunk.
- No hardcoded hex; all colors via tokens.
- `npm run build` exits 0.

## Out of scope
- Real testimonials/customer logos (add when we have them).
- Functional blog/about/legal pages (placeholders for now).
- Changes to authenticated app pages.
