# Design System Refresh ("Instrument, restrained") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "Manila & Ink" cream/serif visual identity with "Instrument, restrained" — a near-monochrome, instrument-grade look with a single teal signal accent — by swapping design tokens, fonts, and restyling the signature components, without rebuilding the token architecture.

**Architecture:** The app is token-driven: semantic Tailwind color names map to CSS variables in `src/index.css`, toggled by `.dark` on `<html>`. Changing the variable *values* (plus fonts in `tailwind.config.js` / `index.html` and a few component tweaks) re-skins ~95% of the app automatically. Work proceeds foundation-first (tokens → fonts → shape) then signature components, then debt cleanup, then a full-app sweep.

**Tech Stack:** React 18 + Vite, Tailwind CSS (class dark mode, CSS-variable colors), `clsx`, `lucide-react`. No test runner — verification is `npm run build`, `grep`, and visual `npm run dev` in light + dark.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-23-design-system-refresh-instrument.md`.
- All work is under `resume-optimizer/frontend/`. Run all `npm` / `grep` commands from that directory.
- Keep the CSS-variable token architecture and the Tailwind semantic names unchanged — only change values, fonts, radius, shadows, and the listed components.
- Keep light/dark toggle, `prefers-reduced-motion` handling, and keyboard focus styles working. `src/theme.js` must not change.
- **Accent discipline:** teal (`--c-accent`) only on primary CTAs, active nav/tabs, focus rings, links, and score/gauge fills. Amber (`--c-hilite`) rare attention-only. Everything else grayscale.
- In dark mode the accent is *light*; dark-text-on-teal must use `dark:text-bg` (never `dark:text-ink`).
- Commit after each task. Branch: `feature/adding_agent` (already checked out).
- Verification baseline command (used throughout): `npm run build` must exit 0.

---

### Task 1: Color tokens + shadows (`index.css`)

**Files:**
- Modify: `resume-optimizer/frontend/src/index.css:8-48` (`:root` and `.dark` blocks)

**Interfaces:**
- Consumes: nothing.
- Produces: the full token palette every later task and component relies on (`--c-bg`, `--c-surface`, `--c-surface-2`, `--c-ink`, `--c-ink-mute`, `--c-ink-faint`, `--c-line`, `--c-accent`, `--c-accent-strong`, `--c-accent-soft`, `--c-hilite`, `--c-hilite-soft`, `--c-err`, `--c-err-soft`, `--shadow-card`, `--shadow-lifted`, `--shadow-accent`).

- [ ] **Step 1: Replace the `:root` block**

Replace `resume-optimizer/frontend/src/index.css` lines 8–27 (`:root { … }`) with:

```css
:root {
  --c-bg:            248 249 250;  /* near-white   #F8F9FA */
  --c-surface:       255 255 255;  /* card         #FFFFFF */
  --c-surface-2:     241 243 245;  /* subtle fill  #F1F3F5 */
  --c-ink:           17 20 24;     /* text         #111418 */
  --c-ink-mute:      90 97 105;    /* secondary    #5A6169 */
  --c-ink-faint:     138 145 152;  /* tertiary     #8A9198 */
  --c-line:          228 231 234;  /* hairline     #E4E7EA */
  --c-accent:        13 148 136;   /* signal teal  #0D9488 */
  --c-accent-strong: 15 118 110;   /* hover        #0F766E */
  --c-accent-soft:   224 244 241;  /* teal tint    #E0F4F1 */
  --c-hilite:        161 98 7;     /* amber        #A16207 */
  --c-hilite-soft:   248 240 224;  /* amber tint   #F8F0E0 */
  --c-err:           198 56 47;    /* error        #C6382F */
  --c-err-soft:      250 233 231;  /* error tint   #FAE9E7 */

  --shadow-card:   0 1px 2px rgba(17, 20, 24, 0.04), 0 1px 3px rgba(17, 20, 24, 0.06);
  --shadow-lifted: 0 2px 6px rgba(17, 20, 24, 0.06), 0 8px 24px rgba(17, 20, 24, 0.08);
  --shadow-accent: 0 0 0 1px rgba(13, 148, 136, 0.25);
}
```

- [ ] **Step 2: Replace the `.dark` block**

Replace lines 29–48 (`.dark { … }`) with:

```css
.dark {
  --c-bg:            14 16 20;     /* graphite     #0E1014 */
  --c-surface:       23 26 31;     /* card         #171A1F */
  --c-surface-2:     32 36 42;     /* subtle fill  #20242A */
  --c-ink:           233 236 240;  /* text         #E9ECF0 */
  --c-ink-mute:      154 161 170;  /* secondary    #9AA1AA */
  --c-ink-faint:     106 112 120;  /* tertiary     #6A7078 */
  --c-line:          38 42 48;     /* hairline     #262A30 */
  --c-accent:        45 212 191;   /* signal teal  #2DD4BF */
  --c-accent-strong: 94 234 212;   /* hover        #5EEAD4 */
  --c-accent-soft:   17 43 41;     /* teal tint    #112B29 */
  --c-hilite:        234 179 8;    /* amber        #EAB308 */
  --c-hilite-soft:   41 33 12;     /* amber tint   #29210C */
  --c-err:           239 109 100;  /* error        #EF6D64 */
  --c-err-soft:      51 28 26;     /* error tint   #331C1A */

  --shadow-card:   0 1px 2px rgba(0, 0, 0, 0.4), 0 2px 8px rgba(0, 0, 0, 0.3);
  --shadow-lifted: 0 2px 6px rgba(0, 0, 0, 0.5), 0 8px 24px rgba(0, 0, 0, 0.4);
  --shadow-accent: 0 0 0 1px rgba(45, 212, 191, 0.25);
}
```

- [ ] **Step 3: Verify old palette is gone**

Run: `grep -nE "250 246 239|26 107 82|178 117 21|77 184 146|FAF6EF|1A6B52" src/index.css`
Expected: no matches (exit 1 / empty output).

- [ ] **Step 4: Verify build**

Run: `npm run build`
Expected: exits 0, no errors.

- [ ] **Step 5: Commit**

```bash
git add src/index.css
git commit -m "refactor(theme): swap color + shadow tokens to Instrument palette"
```

---

### Task 2: Typography swap (`index.html`, `tailwind.config.js`, `index.css`)

**Files:**
- Modify: `resume-optimizer/frontend/index.html` (Google Fonts `<link href=…>`)
- Modify: `resume-optimizer/frontend/tailwind.config.js:28-32` (`fontFamily`)
- Modify: `resume-optimizer/frontend/src/index.css:53` (body font) and `:71-74` (`@layer base h1, h2`)

**Interfaces:**
- Consumes: nothing.
- Produces: font families `display` = Space Grotesk, `sans` = Inter, `mono` = JetBrains Mono (relied on by all components using `font-display` / `font-sans` / `font-mono` and by `h1`/`h2`).

- [ ] **Step 1: Swap the Google Fonts link in `index.html`**

Replace the existing `<link href="https://fonts.googleapis.com/css2?family=Fraunces…">` element with:

```html
    <link
      href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap"
      rel="stylesheet"
    />
```

(Keep the two existing `preconnect` links above it unchanged.)

- [ ] **Step 2: Update `fontFamily` in `tailwind.config.js`**

Replace lines 28–32 (`fontFamily: { … }`) with:

```js
      fontFamily: {
        sans:    ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
```

- [ ] **Step 3: Update body font in `index.css`**

In `resume-optimizer/frontend/src/index.css`, line 53, replace:

```css
  font-family: 'Archivo', system-ui, sans-serif;
```

with:

```css
  font-family: 'Inter', system-ui, sans-serif;
```

- [ ] **Step 4: Update `@layer base` h1/h2 font in `index.css`**

Replace lines 71–74:

```css
  h1, h2 {
    font-family: 'Fraunces', Georgia, serif;
    letter-spacing: -0.01em;
  }
```

with:

```css
  h1, h2 {
    font-family: 'Space Grotesk', system-ui, sans-serif;
    letter-spacing: -0.01em;
  }
```

- [ ] **Step 5: Verify old fonts are gone**

Run: `grep -rniE "fraunces|archivo" index.html src/`
Expected: no matches (exit 1 / empty output).

- [ ] **Step 6: Verify build**

Run: `npm run build`
Expected: exits 0.

- [ ] **Step 7: Commit**

```bash
git add index.html tailwind.config.js src/index.css
git commit -m "refactor(theme): swap fonts to Space Grotesk + Inter + JetBrains Mono"
```

---

### Task 3: Shape & texture (`tailwind.config.js`, `index.css`)

**Files:**
- Modify: `resume-optimizer/frontend/tailwind.config.js:33-37` (`borderRadius`)
- Modify: `resume-optimizer/frontend/src/index.css:59-68` (remove `body::before` texture)

**Interfaces:**
- Consumes: nothing.
- Produces: `borderRadius.DEFAULT` = 6px, `borderRadius.card` = 8px; no page texture overlay.

- [ ] **Step 1: Tighten border radius**

Replace lines 33–37 of `tailwind.config.js` (`borderRadius: { … }`) with:

```js
      borderRadius: {
        // instrument: crisp panels, no pills on containers
        DEFAULT: '6px',
        card: '8px',
      },
```

- [ ] **Step 2: Remove the paper-grain texture**

In `resume-optimizer/frontend/src/index.css`, delete the entire comment + rule spanning lines 59–68 (the `/* Paper grain … */` comment and the `body::before { … }` block). Leave a single blank line where it was.

- [ ] **Step 3: Verify texture is gone**

Run: `grep -nE "Paper grain|body::before|feTurbulence" src/index.css`
Expected: no matches.

- [ ] **Step 4: Verify build**

Run: `npm run build`
Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add tailwind.config.js src/index.css
git commit -m "refactor(theme): tighten radius, remove paper-grain texture"
```

---

### Task 4: Core UI components (`Button`, `Card`, `Badge`, `QuotaBar`)

**Files:**
- Modify: `resume-optimizer/frontend/src/components/ui/Button.jsx`
- Modify: `resume-optimizer/frontend/src/components/ui/Card.jsx`
- Modify: `resume-optimizer/frontend/src/components/ui/Badge.jsx`
- Modify: `resume-optimizer/frontend/src/components/ui/QuotaBar.jsx` (verify only)

**Interfaces:**
- Consumes: tokens from Task 1, fonts from Task 2.
- Produces: restyled shared kit; no prop/API changes (variants and sizes keep their names).

- [ ] **Step 1: Fix Button primary text-on-teal for dark mode**

In `Button.jsx`, replace the `variants` object with:

```js
const variants = {
  primary:   'bg-primary hover:bg-primary-dark text-white dark:text-bg shadow-primary',
  secondary: 'bg-card hover:bg-surface-2 text-ink border border-line shadow-card',
  ghost:     'bg-transparent hover:bg-surface-2 text-ink-mute',
  danger:    'bg-err hover:opacity-90 text-white shadow-sm',
};
```

(Only change: `dark:text-ink` → `dark:text-bg` on `primary`, so dark text lands on the light teal in dark mode.)

- [ ] **Step 2: Soften Card hover (border-led, not shadow-led)**

In `Card.jsx`, replace the outer wrapper `className` clsx block:

```jsx
    <div className={clsx(
      'bg-card rounded-card shadow-card border border-line',
      'hover:border-ink-faint/40 hover:shadow-lifted transition-all duration-200',
      className
    )}>
```

(Removes the `hover:-translate-y-0.5` lift in favour of a quiet border emphasis, matching the restrained direction.)

- [ ] **Step 3: Re-map Badge variants to the new palette**

In `Badge.jsx`, replace the `styles` object with:

```js
const styles = {
  free:       'bg-surface-2 text-ink-mute',
  pro:        'bg-accent-soft text-primary',
  enterprise: 'bg-hilite-soft text-hilite',
  admin:      'bg-err-soft text-err',
  green:      'bg-accent-soft text-primary',
  amber:      'bg-hilite-soft text-hilite',
  red:        'bg-err-soft text-err',
  blue:       'bg-surface-2 text-ink-mute',
  teal:       'bg-accent-soft text-primary',
};
```

(Only change: `blue` now maps to neutral grayscale instead of teal, enforcing accent discipline. Others already token-driven.)

- [ ] **Step 4: Verify QuotaBar needs no change**

Run: `grep -nE "#|rgb\(" src/components/ui/QuotaBar.jsx`
Expected: no matches — it is fully token-driven (`bg-primary`, `bg-surface-2`). No edit needed.

- [ ] **Step 5: Verify build**

Run: `npm run build`
Expected: exits 0.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/Button.jsx src/components/ui/Card.jsx src/components/ui/Badge.jsx
git commit -m "refactor(ui): restyle Button/Card/Badge for Instrument palette + accent discipline"
```

---

### Task 5: Signature — `PipelineProgress` (de-hardcode + gauge restyle)

**Files:**
- Modify: `resume-optimizer/frontend/src/components/PipelineProgress.jsx`

**Interfaces:**
- Consumes: tokens from Task 1.
- Produces: pipeline track styled as a segmented gauge; no hardcoded colors; props (`stage`, `iteration`, `score`, `message`, `running`) unchanged.

- [ ] **Step 1: Remove the hardcoded green glow on the active node**

In `PipelineProgress.jsx`, find the active-node class:

```jsx
                  state === 'active'  && 'border-primary bg-card shadow-[0_0_0_3px_rgba(26,107,82,0.15)]',
```

Replace it with a token-based ring:

```jsx
                  state === 'active'  && 'border-primary bg-card ring-2 ring-primary/20',
```

- [ ] **Step 2: Make stage labels mono (instrument readout)**

In the stage-label `<span>`, replace its `className` clsx:

```jsx
                <span className={clsx(
                  'font-mono text-[9px] leading-none whitespace-nowrap uppercase tracking-wide',
                  state === 'active'  ? 'text-primary font-semibold' :
                  state === 'done'    ? 'text-ink-mute' : 'text-ink-faint'
                )}>
```

- [ ] **Step 3: Verify no hardcoded colors remain**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}|rgba?\(" src/components/PipelineProgress.jsx`
Expected: no matches.

- [ ] **Step 4: Verify build**

Run: `npm run build`
Expected: exits 0.

- [ ] **Step 5: Visual check (dark + light)**

Run: `npm run dev`, open the app, trigger an optimization (or render the component) and confirm the pipeline track, active-node ring, and mono stage labels look correct in both themes. Stop the dev server when done.

- [ ] **Step 6: Commit**

```bash
git add src/components/PipelineProgress.jsx
git commit -m "refactor(ui): de-hardcode PipelineProgress glow + mono gauge labels"
```

---

### Task 6: Signature — `ScoreReveal` (mono delta + gauges)

**Files:**
- Modify: `resume-optimizer/frontend/src/components/ScoreReveal.jsx`

**Interfaces:**
- Consumes: tokens from Task 1, fonts from Task 2.
- Produces: score readout with mono delta and gauge sub-scores; props unchanged.

- [ ] **Step 1: Make the baseline delta a mono readout**

In `ScoreReveal.jsx`, find the improved-from line:

```jsx
            {improved && <span className="text-primary font-semibold">↑ from {baseline} · </span>}
```

Replace with a mono delta:

```jsx
            {improved && <span className="font-mono text-primary font-semibold">{baseline} → {Math.round(finalScore)} · </span>}
```

- [ ] **Step 2: Fix the download CTA text-on-teal for dark mode**

Find the download link `className` containing `text-white dark:text-ink` and replace that token pair so dark text lands on teal:

```jsx
          className="reveal reveal-4 flex items-center justify-center gap-2 w-full bg-primary hover:bg-primary-dark text-white dark:text-bg py-3 rounded-lg font-semibold shadow-primary transition-colors active:scale-[0.98]"
```

- [ ] **Step 3: Verify no hardcoded colors remain**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}|rgba?\(" src/components/ScoreReveal.jsx`
Expected: no matches.

- [ ] **Step 4: Verify build**

Run: `npm run build`
Expected: exits 0.

- [ ] **Step 5: Visual check (dark + light)**

Run: `npm run dev`, render a completed optimization, confirm the big Space Grotesk score, mono `NN → MM` delta, and sub-score gauges read correctly in both themes. Stop the dev server.

- [ ] **Step 6: Commit**

```bash
git add src/components/ScoreReveal.jsx
git commit -m "refactor(ui): ScoreReveal mono delta readout + dark-mode CTA contrast"
```

---

### Task 7: Landing Pricing band debt (`Landing.jsx`)

**Files:**
- Modify: `resume-optimizer/frontend/src/pages/Landing.jsx:97-129` (Pricing `<section>`) and the hero CTA at `:42`

**Interfaces:**
- Consumes: tokens from Task 1.
- Produces: Landing page free of hardcoded Manila/Ink hex; follows tokens.

- [ ] **Step 1: Fix the hero CTA dark-mode contrast**

In `Landing.jsx` line ~42, in the "Get started free" `Link`, replace `text-white dark:text-ink` with `text-white dark:text-bg`.

- [ ] **Step 2: Replace the Pricing section with a token-driven version**

Replace the entire Pricing `<section className="bg-[#1E1A15] py-24"> … </section>` block (lines ~97–129) with:

```jsx
      {/* Pricing — token-driven ink band */}
      <section className="bg-surface-2 dark:bg-card py-24 border-y border-line">
        <div className="max-w-5xl mx-auto px-6">
          <h2 className="font-display text-3xl font-semibold text-ink text-center mb-4">Simple, transparent pricing</h2>
          <p className="text-ink-mute text-center mb-12">Start free. Upgrade when you need more.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {plans.map(({ name, price, period, features, highlight }) => (
              <div key={name} className="flex flex-col">
                <div className="h-7 flex items-center justify-center mb-1">
                  {highlight && <span className="bg-hilite text-bg text-xs font-bold px-3 py-1 rounded-full whitespace-nowrap">Most popular</span>}
                </div>
                <div className={`rounded-card p-8 border ${highlight ? 'bg-accent-soft border-primary/40 text-ink' : 'bg-card border-line text-ink'}`}>
                  <div className="font-semibold text-lg mb-1">{name}</div>
                  <div className="flex items-end gap-1 mb-6">
                    <span className="font-display text-4xl font-semibold">{price}</span>
                    <span className="text-sm mb-1 text-ink-faint">{period}</span>
                  </div>
                  <ul className="space-y-3 mb-8">
                    {features.map(f => (
                      <li key={f} className="flex items-center gap-2 text-sm">
                        <Check className="w-4 h-4 shrink-0 text-primary" />{f}
                      </li>
                    ))}
                  </ul>
                  <Link to="/register" className={`block text-center py-2.5 rounded-lg font-medium text-sm transition-colors ${highlight ? 'bg-primary hover:bg-primary-dark text-white dark:text-bg' : 'bg-surface-2 hover:bg-line text-ink'}`}>
                    Get started
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
```

- [ ] **Step 3: Verify no hardcoded hex remains in Landing**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}" src/pages/Landing.jsx`
Expected: no matches.

- [ ] **Step 4: Verify build**

Run: `npm run build`
Expected: exits 0.

- [ ] **Step 5: Visual check (dark + light)**

Run: `npm run dev`, open `/`, confirm hero + pricing band render with the new palette in both themes (the "Most popular" tier should read as a teal-tinted card, not the old green band). Stop the dev server.

- [ ] **Step 6: Commit**

```bash
git add src/pages/Landing.jsx
git commit -m "refactor(landing): migrate hardcoded Manila/Ink colors to tokens"
```

---

### Task 8: Full-app verification sweep

**Files:**
- Modify (only if the sweep finds violations): any file flagged below.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: confirmation the refresh is complete and consistent.

- [ ] **Step 1: Sweep for leftover old-palette hex across the app**

Run: `grep -rniE "FAF6EF|1A6B52|B27515|4DB892|D9A03F|1E1A15|EDE6DA|B2A99B|29231C|3C342A" src/`
Expected: no matches. If any appear, migrate them to the matching token (`bg-surface`, `text-primary`, `text-ink`, `bg-card`, etc.) following Task 7's pattern, then re-run.

- [ ] **Step 2: Sweep for dark-mode text-on-teal contrast bugs**

Run: `grep -rnE "bg-primary[^\"]*dark:text-ink|dark:text-ink[^\"]*bg-primary" src/`
Expected: no matches. Any hit is light text on light teal — change `dark:text-ink` → `dark:text-bg`.

- [ ] **Step 3: Confirm fonts and texture fully removed**

Run: `grep -rniE "fraunces|archivo|feTurbulence|Paper grain" index.html src/`
Expected: no matches.

- [ ] **Step 4: Production build**

Run: `npm run build`
Expected: exits 0, no warnings about missing tokens/fonts.

- [ ] **Step 5: Manual acceptance pass**

Run: `npm run dev` and verify against spec acceptance criteria:
- Landing, Dashboard, Chat (with a ScoreReveal/PipelineProgress), Profiles, and an admin page render in **dark** mode with neutral grays + teal-only accents.
- Toggle to **light** mode (ThemeToggle) — neutral near-white, teal deepened, readable.
- Toggle respects choice and OS; reload keeps the chosen theme.
- Keyboard-tab through buttons/links: visible teal focus ring.
- With OS "reduce motion" on, reveals/count-up collapse to instant.
Stop the dev server.

- [ ] **Step 6: Final commit (if any sweep fixes were made)**

```bash
git add -A
git commit -m "refactor(theme): final Instrument refresh sweep + contrast fixes"
```

(If steps 1–3 found nothing to fix, skip this commit.)

---

## Self-Review

**Spec coverage:**
- Color tokens (both modes) → Task 1. ✔
- Shadows (border-led) → Task 1. ✔
- Typography swap (Space Grotesk / Inter / JetBrains Mono; index.html + tailwind + index.css) → Task 2. ✔
- Shape/radius + texture removal → Task 3. ✔
- Accent discipline (teal-only, amber demoted, neutral `blue` badge) → Tasks 1, 4. ✔
- Core components (Button/Card/Badge/QuotaBar) → Task 4. ✔
- Signature PipelineProgress (de-hardcode glow, mono gauge) → Task 5. ✔
- Signature ScoreReveal (mono delta, dark CTA contrast) → Task 6. ✔
- Dark-mode text-on-teal fix → Tasks 4, 6, 7, swept in 8. ✔
- Landing hardcoded-color debt → Task 7. ✔
- Acceptance criteria (both modes, toggle, reduced-motion, focus, build) → Task 8. ✔
- `theme.js` untouched → not modified by any task. ✔
- Out of scope: Landing rebuild (deferred), page-by-page redesign — correctly excluded.

**Placeholder scan:** No TBD/TODO; every code step shows full replacement code; every verify step has an exact command + expected result.

**Type/name consistency:** Token names match the spec tables and Task 1 verbatim; `dark:text-bg` used consistently for teal CTAs across Tasks 4/6/7/8; Tailwind semantic names (`bg-primary`, `text-ink`, `bg-surface-2`, `bg-accent-soft`, `text-hilite`) match `tailwind.config.js` mappings unchanged by this plan.
