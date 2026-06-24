# Landing Page Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the marketing Landing page with the Instrument design system — real product preview, honest stats, real-pipeline "how it works", FAQ, final CTA, and a footer — and delete the now-unused 3D hero.

**Architecture:** Six new focused, presentational components under `src/components/landing/`, composed by a rewritten `Landing.jsx`. Each new component is self-contained (local data, no props). The existing token-migrated Pricing section is preserved. `HeroVisual` + `HeroScene` (three.js) are deleted once unreferenced.

**Tech Stack:** React 18 + Vite, Tailwind (Instrument tokens), `clsx`, `lucide-react`, `react-router-dom`. No test runner — verification is `npm run build` + `grep` + visual `npm run dev`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-23-landing-rebuild-design.md`.
- All paths under `resume-optimizer/frontend/`. Run `npm`/`grep` from there.
- Colors via tokens only — no hardcoded hex. Teal accent only on CTAs/active/gauges/links.
- Dark-text-on-teal uses `dark:text-surface` (never `dark:text-ink`).
- Fonts: `font-display` (Space Grotesk), default Inter, `font-mono` (JetBrains Mono) for numbers/eyebrows.
- No fabricated logos. Footer links only to real routes (`/login`, `/register`) or on-page anchors (`#how-it-works`, `#pricing`, `#faq`); placeholders use `href="#"`.
- Respect `prefers-reduced-motion`; preserve visible keyboard focus.
- Commit after each task. Branch: `feature/adding_agent`.
- Baseline: `npm run build` must exit 0 (note: the Linux esbuild binary is already installed in this environment).

**Parallelization note:** Tasks 1–6 each create a *distinct new file* and are independent — they may be done in parallel. If dispatched to parallel agents, agents should create their file only and must NOT run `npm run build` (concurrent Vite builds race on `dist/`) or `git commit` (race on `.git/index.lock`); the coordinator builds and commits. Tasks 7–8 are sequential and depend on 1–6.

---

### Task 1: `HeroPreview` component

**Files:**
- Create: `resume-optimizer/frontend/src/components/landing/HeroPreview.jsx`

**Interfaces:**
- Produces: `export default function HeroPreview()` — a static instrument card; no props. Consumed by `Landing.jsx` (Task 7).

- [ ] **Step 1: Create the file with this exact content**

```jsx
import { Check } from 'lucide-react';

const SUBSCORES = [
  { label: 'ATS Match',    value: 94 },
  { label: 'Impact',       value: 88 },
  { label: 'Skills Gap',   value: 90 },
  { label: 'JD Tailoring', value: 92 },
];

const STAGES = ['JD', 'Score', 'Rewrite', 'Humanize', 'Verify', 'Export'];

/** Static, presentational preview of the optimizer result (mock data). */
export default function HeroPreview() {
  return (
    <div className="bg-card border border-line rounded-card shadow-lifted p-6 w-full max-w-md mx-auto">
      <p className="font-mono text-[10px] uppercase tracking-widest text-ink-faint mb-3">Optimization complete</p>

      <div className="flex items-end gap-3 mb-5">
        <span className="font-display text-6xl font-semibold text-primary leading-none">91</span>
        <div className="mb-1">
          <span className="block text-sm text-ink-mute font-medium">/ 100 final score</span>
          <span className="block font-mono text-xs text-primary font-semibold">72 → 91</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2.5 mb-5">
        {SUBSCORES.map(({ label, value }) => (
          <div key={label} className="bg-surface-2 border border-line rounded-lg px-3 py-2.5">
            <div className="flex items-baseline justify-between mb-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-faint">{label}</span>
              <span className="font-mono text-sm font-bold text-ink">{value}</span>
            </div>
            <div className="h-1 bg-line rounded-full overflow-hidden">
              <div className="h-full bg-primary rounded-full" style={{ width: `${value}%` }} />
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center">
        {STAGES.map((s, i) => (
          <div key={s} className={i < STAGES.length - 1 ? 'flex items-center flex-1' : 'flex items-center'}>
            <div className="flex flex-col items-center">
              <div className="w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                <Check className="w-2.5 h-2.5 text-white dark:text-surface" strokeWidth={3} />
              </div>
              <span className="font-mono text-[8px] uppercase tracking-wide text-ink-faint mt-1">{s}</span>
            </div>
            {i < STAGES.length - 1 && <div className="h-px flex-1 mx-1 bg-primary/70 mb-4" />}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify no hardcoded hex**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}" src/components/landing/HeroPreview.jsx`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add src/components/landing/HeroPreview.jsx
git commit -m "feat(landing): HeroPreview instrument card"
```

---

### Task 2: `StatsRow` component

**Files:**
- Create: `resume-optimizer/frontend/src/components/landing/StatsRow.jsx`

**Interfaces:**
- Produces: `export default function StatsRow()` — no props. Consumed by `Landing.jsx`.

- [ ] **Step 1: Create the file with this exact content**

```jsx
const STATS = [
  { stat: '5',         label: 'scoring dimensions',     sub: 'ATS · Impact · Skills · Readability · JD fit' },
  { stat: 'Guarded',   label: 'never invents experience', sub: 'every claim checked against your history' },
  { stat: 'Iterative', label: 'refines until it peaks',  sub: 'loops until the score stops climbing' },
  { stat: '3',         label: 'job sources',            sub: 'Adzuna · RemoteOK · The Muse' },
];

export default function StatsRow() {
  return (
    <section className="border-y border-line bg-surface-2/40">
      <div className="max-w-5xl mx-auto px-6 py-10 grid grid-cols-2 lg:grid-cols-4 gap-8">
        {STATS.map(({ stat, label, sub }) => (
          <div key={label}>
            <div className="font-display text-2xl font-semibold text-ink mb-1">{stat}</div>
            <div className="text-sm font-medium text-ink-mute">{label}</div>
            <div className="text-xs text-ink-faint mt-1">{sub}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Verify no hardcoded hex**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}" src/components/landing/StatsRow.jsx`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add src/components/landing/StatsRow.jsx
git commit -m "feat(landing): StatsRow honest metrics"
```

---

### Task 3: `HowItWorks` component

**Files:**
- Create: `resume-optimizer/frontend/src/components/landing/HowItWorks.jsx`

**Interfaces:**
- Produces: `export default function HowItWorks()` — renders a `<section id="how-it-works">`; no props. Consumed by `Landing.jsx`.

- [ ] **Step 1: Create the file with this exact content**

```jsx
const STEPS = [
  { n: '01', title: 'Analyze the JD',    desc: 'Pull keywords, must-haves, and signals from the posting.' },
  { n: '02', title: 'Score your resume', desc: 'ATS match, impact, skills gap, readability, and JD tailoring.' },
  { n: '03', title: 'Rewrite & tailor',  desc: 'Align your bullets to what the role actually asks for.' },
  { n: '04', title: 'Humanize',          desc: 'Natural phrasing — not robotic keyword stuffing.' },
  { n: '05', title: 'Verify & guard',    desc: 'Every claim checked against your real history. Never fabricated.' },
  { n: '06', title: 'Generate',          desc: 'A clean .docx or .pdf, ready to send.' },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="max-w-5xl mx-auto px-6 py-24">
      <p className="font-mono text-[10px] uppercase tracking-widest text-ink-faint mb-3">How it works</p>
      <h2 className="font-display text-3xl font-semibold text-ink mb-12 max-w-xl">
        Six steps from raw resume to a tailored, verified draft.
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-line border border-line rounded-card overflow-hidden">
        {STEPS.map(({ n, title, desc }) => (
          <div key={n} className="bg-card p-6">
            <span className="font-mono text-xs text-primary font-semibold">{n}</span>
            <h3 className="font-display text-lg font-semibold text-ink mt-2 mb-1.5">{title}</h3>
            <p className="text-sm text-ink-mute leading-relaxed">{desc}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Verify no hardcoded hex**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}" src/components/landing/HowItWorks.jsx`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add src/components/landing/HowItWorks.jsx
git commit -m "feat(landing): HowItWorks real pipeline section"
```

---

### Task 4: `FAQ` component

**Files:**
- Create: `resume-optimizer/frontend/src/components/landing/FAQ.jsx`

**Interfaces:**
- Produces: `export default function FAQ()` — renders a `<section id="faq">` using native `<details>`; no props. Consumed by `Landing.jsx`.

- [ ] **Step 1: Create the file with this exact content**

```jsx
const FAQS = [
  { q: 'Does it make up experience I don’t have?', a: 'No. A fabrication guard checks every rewritten claim against your real history, so the draft stays truthful.' },
  { q: 'What file formats can I use?', a: 'Upload a PDF or DOCX. Download your optimized resume as DOCX or PDF.' },
  { q: 'How is the score calculated?', a: 'Five dimensions: ATS match, impact, skills gap, readability, and how well the resume is tailored to the job description.' },
  { q: 'Is my data private?', a: 'Your resume is used only to optimize your own documents.' },
  { q: 'Is there a free tier?', a: 'Yes — start free, no credit card required.' },
];

export default function FAQ() {
  return (
    <section id="faq" className="max-w-3xl mx-auto px-6 py-24">
      <p className="font-mono text-[10px] uppercase tracking-widest text-ink-faint mb-3">FAQ</p>
      <h2 className="font-display text-3xl font-semibold text-ink mb-10">Questions, answered.</h2>
      <div className="divide-y divide-line border-y border-line">
        {FAQS.map(({ q, a }) => (
          <details key={q} className="group py-4">
            <summary className="flex items-center justify-between cursor-pointer list-none font-medium text-ink focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none rounded">
              {q}
              <span className="font-mono text-primary text-lg transition-transform group-open:rotate-45">+</span>
            </summary>
            <p className="text-sm text-ink-mute leading-relaxed mt-3">{a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Verify no hardcoded hex**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}" src/components/landing/FAQ.jsx`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add src/components/landing/FAQ.jsx
git commit -m "feat(landing): FAQ section (native details, accessible)"
```

---

### Task 5: `FinalCTA` component

**Files:**
- Create: `resume-optimizer/frontend/src/components/landing/FinalCTA.jsx`

**Interfaces:**
- Produces: `export default function FinalCTA()` — no props. Consumed by `Landing.jsx`.

- [ ] **Step 1: Create the file with this exact content**

```jsx
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';

export default function FinalCTA() {
  return (
    <section className="border-y border-line bg-accent-soft/40">
      <div className="max-w-3xl mx-auto px-6 py-20 text-center">
        <h2 className="font-display text-3xl lg:text-4xl font-semibold text-ink mb-4">
          Send a sharper resume on your next application.
        </h2>
        <p className="text-ink-mute mb-8">Upload once, score on five dimensions, and download a verified draft.</p>
        <Link
          to="/register"
          className="inline-flex items-center gap-2 px-8 py-3.5 rounded-lg font-semibold text-lg text-white dark:text-surface bg-primary hover:bg-primary-dark shadow-primary transition-all active:scale-95 focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none"
        >
          Get started free <ArrowRight className="w-5 h-5" />
        </Link>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Verify no hardcoded hex**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}" src/components/landing/FinalCTA.jsx`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add src/components/landing/FinalCTA.jsx
git commit -m "feat(landing): FinalCTA band"
```

---

### Task 6: `SiteFooter` component

**Files:**
- Create: `resume-optimizer/frontend/src/components/landing/SiteFooter.jsx`

**Interfaces:**
- Produces: `export default function SiteFooter()` — no props. Consumed by `Landing.jsx`.

- [ ] **Step 1: Create the file with this exact content**

```jsx
import { Link } from 'react-router-dom';

const COLUMNS = [
  { title: 'Product', links: [
    { label: 'How it works', href: '#how-it-works', type: 'anchor' },
    { label: 'Pricing',      href: '#pricing',      type: 'anchor' },
    { label: 'Sign in',      href: '/login',        type: 'route' },
    { label: 'Get started',  href: '/register',     type: 'route' },
  ]},
  { title: 'Company', links: [
    { label: 'About', href: '#', type: 'soon' },
    { label: 'Blog',  href: '#', type: 'soon' },
  ]},
  { title: 'Legal', links: [
    { label: 'Privacy', href: '#', type: 'soon' },
    { label: 'Terms',   href: '#', type: 'soon' },
  ]},
];

function FooterLink({ link }) {
  const cls = 'text-sm text-ink-mute hover:text-ink transition-colors';
  if (link.type === 'route') return <Link to={link.href} className={cls}>{link.label}</Link>;
  return <a href={link.href} className={cls}>{link.label}</a>;
}

export default function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="max-w-5xl mx-auto px-6 py-12 grid grid-cols-2 md:grid-cols-4 gap-8">
        <div className="col-span-2 md:col-span-1">
          <div className="font-display text-lg font-semibold text-ink mb-2">Resume Optimizer</div>
          <p className="text-xs text-ink-faint leading-relaxed">Powered by Gemini · Groq · Anthropic</p>
        </div>
        {COLUMNS.map((col) => (
          <div key={col.title}>
            <div className="font-mono text-[10px] uppercase tracking-widest text-ink-faint mb-3">{col.title}</div>
            <ul className="space-y-2">
              {col.links.map((link) => (
                <li key={link.label}><FooterLink link={link} /></li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-line">
        <div className="max-w-5xl mx-auto px-6 py-4 text-xs text-ink-faint">
          © {new Date().getFullYear()} Resume Optimizer. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
```

- [ ] **Step 2: Verify no hardcoded hex**

Run: `grep -nE "#[0-9A-Fa-f]{3,6}" src/components/landing/SiteFooter.jsx`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add src/components/landing/SiteFooter.jsx
git commit -m "feat(landing): SiteFooter multi-column"
```

---

### Task 7: Rewrite `Landing.jsx` to compose the new sections

**Files:**
- Modify (full rewrite): `resume-optimizer/frontend/src/pages/Landing.jsx`

**Interfaces:**
- Consumes: `HeroPreview`, `StatsRow`, `HowItWorks`, `FAQ`, `FinalCTA`, `SiteFooter` (Tasks 1–6), plus existing `TopNav`.
- Produces: the composed Landing page.

- [ ] **Step 1: Replace the entire file with this exact content**

```jsx
import { Link } from 'react-router-dom';
import { Zap, ArrowRight, Check } from 'lucide-react';
import TopNav from '../components/layout/TopNav';
import HeroPreview from '../components/landing/HeroPreview';
import StatsRow from '../components/landing/StatsRow';
import HowItWorks from '../components/landing/HowItWorks';
import FAQ from '../components/landing/FAQ';
import FinalCTA from '../components/landing/FinalCTA';
import SiteFooter from '../components/landing/SiteFooter';

const plans = [
  { name: 'Free',       price: '$0',  period: '/mo', features: ['2 uploads / day','1 resume stored','5 AI scorers','PDF + DOCX export'],   highlight: false },
  { name: 'Pro',        price: '$9',  period: '/mo', features: ['20 uploads / day','10 resumes stored','Job matching','Usage history'],     highlight: true  },
  { name: 'Enterprise', price: '$29', period: '/mo', features: ['Unlimited uploads','Unlimited storage','API access','Priority queue'],     highlight: false },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-surface page-fade">
      <TopNav />

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-6 pt-20 pb-16 grid grid-cols-1 lg:grid-cols-2 gap-10 items-center">
        <div className="text-center lg:text-left">
          <div className="reveal reveal-1 inline-flex items-center gap-2 bg-accent-soft text-primary px-4 py-1.5 rounded-full text-sm font-medium mb-6">
            <Zap className="w-3.5 h-3.5" /> Powered by Gemini · Groq · Anthropic
          </div>
          <h1 className="reveal reveal-2 font-display text-5xl lg:text-6xl font-semibold text-ink leading-[1.1] mb-6">
            Tailored, scored,<br /><span className="text-primary">and verified — never faked.</span>
          </h1>
          <p className="reveal reveal-3 text-xl text-ink-mute mb-10 max-w-xl mx-auto lg:mx-0">
            Upload once. Score on five dimensions. Iterate until it peaks — with a guard that keeps every claim true.
          </p>
          <div className="reveal reveal-4 flex items-center justify-center lg:justify-start gap-4">
            <Link to="/register" className="inline-flex items-center gap-2 px-8 py-3.5 rounded-lg font-semibold text-lg text-white dark:text-surface bg-primary hover:bg-primary-dark shadow-primary transition-all active:scale-95 focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none">
              Get started free <ArrowRight className="w-5 h-5" />
            </Link>
            <Link to="/login" className="text-ink-mute hover:text-ink px-6 py-3.5 font-medium transition-colors">
              Sign in →
            </Link>
          </div>
        </div>
        <div className="reveal reveal-3 hidden sm:block">
          <HeroPreview />
        </div>
      </section>

      <StatsRow />

      <HowItWorks />

      {/* Pricing */}
      <section id="pricing" className="bg-surface-2 dark:bg-card py-24 border-y border-line">
        <div className="max-w-5xl mx-auto px-6">
          <h2 className="font-display text-3xl font-semibold text-ink text-center mb-4">Simple, transparent pricing</h2>
          <p className="text-ink-mute text-center mb-12">Start free. Upgrade when you need more.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {plans.map(({ name, price, period, features, highlight }) => (
              <div key={name} className="flex flex-col">
                <div className="h-7 flex items-center justify-center mb-1">
                  {highlight && <span className="bg-hilite text-surface text-xs font-bold px-3 py-1 rounded-full whitespace-nowrap">Most popular</span>}
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
                  <Link to="/register" className={`block text-center py-2.5 rounded-lg font-medium text-sm transition-colors ${highlight ? 'bg-primary hover:bg-primary-dark text-white dark:text-surface' : 'bg-surface-2 hover:bg-line text-ink'}`}>
                    Get started
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <FAQ />

      <FinalCTA />

      <SiteFooter />
    </div>
  );
}
```

- [ ] **Step 2: Verify HeroVisual import is gone and no hardcoded hex**

Run: `grep -nE "HeroVisual|#[0-9A-Fa-f]{3,6}" src/pages/Landing.jsx`
Expected: no matches.

- [ ] **Step 3: Build**

Run: `npm run build`
Expected: exits 0 (all six new components resolve and compile).

- [ ] **Step 4: Commit**

```bash
git add src/pages/Landing.jsx
git commit -m "feat(landing): compose rebuilt page with new sections"
```

---

### Task 8: Delete the unused 3D hero + final verification

**Files:**
- Delete: `resume-optimizer/frontend/src/components/HeroVisual.jsx`
- Delete: `resume-optimizer/frontend/src/components/three/HeroScene.jsx`

**Interfaces:**
- Consumes: confirmation from Task 7 that nothing imports these anymore.

- [ ] **Step 1: Confirm no remaining importers**

Run: `grep -rn "HeroVisual\|HeroScene" src/`
Expected: no matches (Task 7 removed the only import).

- [ ] **Step 2: Delete the files**

```bash
git rm src/components/HeroVisual.jsx src/components/three/HeroScene.jsx
rmdir src/components/three 2>/dev/null || true
```

- [ ] **Step 3: Build and confirm the three.js chunk is gone**

Run: `npm run build 2>&1 | grep -i "HeroScene" && echo "CHUNK STILL PRESENT" || echo "chunk gone ✓"`
Expected: `chunk gone ✓` (no `HeroScene-*.js` chunk emitted). The build itself must exit 0.

- [ ] **Step 4: Final sweep**

Run: `grep -rnE "#[0-9A-Fa-f]{3,6}" src/components/landing/ src/pages/Landing.jsx`
Expected: no matches.

- [ ] **Step 5: Visual check (dark + light)**

Run `npm run dev`, open `/`, and confirm: hero shows `HeroPreview` (score 72→91, gauges, pipeline), stats row, six-step how-it-works, pricing, FAQ (expand/collapse works, keyboard-focusable), final CTA, footer. Toggle theme; check both. Stop the dev server.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(landing): delete unused HeroVisual + HeroScene (drop three.js chunk)"
```

---

## Self-Review

**Spec coverage:**
- Hero product preview replacing abstract visual → Task 1 (HeroPreview) + Task 7 (wired in, HeroVisual removed). ✔
- Honest stats row (no logos) → Task 2. ✔
- Real-pipeline how-it-works (6 steps incl. fabrication guard) → Task 3. ✔
- FAQ, accessible → Task 4 (native `<details>`, focus ring). ✔
- Final CTA band → Task 5. ✔
- Multi-column footer, real routes + anchors + `#` placeholders → Task 6. ✔
- Pricing preserved with `id="pricing"` anchor → Task 7. ✔
- Anchors `#how-it-works`, `#pricing`, `#faq` present → Tasks 3, 7, 4. ✔
- Delete HeroVisual + HeroScene; chunk dropped → Task 8. ✔
- No hardcoded hex; tokens only → grep steps in every task. ✔
- `dark:text-surface` for teal CTAs → Tasks 1, 5, 7. ✔
- Build exits 0 → Tasks 7, 8. ✔

**Placeholder scan:** No TBD/TODO; every component task contains complete file content; every verify step has an exact command + expected result.

**Type/name consistency:** Component names and default exports match their imports in Task 7 exactly (`HeroPreview`, `StatsRow`, `HowItWorks`, `FAQ`, `FinalCTA`, `SiteFooter`). Anchor ids (`how-it-works`, `pricing`, `faq`) match the footer/nav hrefs. Pricing `plans` array updated to "5 AI scorers" to match the five-dimension copy used elsewhere.
