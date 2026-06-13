# Stage A · Phase 0 — UX Audit & Feature Triage

**Date:** 2026-06-11 · **Scope:** read-only audit, no code changed.
**Status:** ✅ Triage approved 2026-06-11 — all REMOVE items executed (7 files deleted; AppPage/pipelineStore/PipelineStep/ScoreCard/CircularProgress/UsageTrendsChart/MatchAnalytics; dead Settings buttons, fake mid-run instructions, `/dashboard/usage` route, unused deps, vite proxy). Landing copy now "Powered by Gemini · Groq · Anthropic" per approval. MOVE TO ADMIN items (token trends, match quality) land in Phase 3. Build verified green after removals.

---

## 1. Tech Stack (confirmed)

| Layer | Actual |
|---|---|
| Framework | React 18.2 (JSX, no TypeScript), Vite 4.5 |
| Routing | React Router 7.13 (`BrowserRouter`, no lazy routes) |
| Styling | Tailwind CSS 3.4 + 6 custom tokens; many inline hex values bypass the token system |
| State | Zustand 5 (`authStore`, `profileStore`, `pipelineStore`) |
| HTTP | Axios with interceptors (token inject, GET-on-5xx retry ×2, 401 logout, 429 toast) |
| Realtime | Native `EventSource` against FastAPI SSE (`/status/{job_id}`) |
| Charts | Recharts 3.8 |
| Icons / toast | lucide-react, react-hot-toast |
| Installed but **unused** | `@radix-ui/react-dialog`, `@radix-ui/react-slot`, `tailwind-merge` |
| Lint/tests | **No ESLint config, no frontend tests** |
| Deploy | Azure Static Web Apps (`staticwebapp.config.json`); backend FastAPI on App Service |

**Backend reality check:** the pipeline is **custom agents** (`agents/jd_analyzer → rewriter → humanizer → scorer → fabrication_guard`, orchestrated by `orchestration/optimizer.py`), *not* CrewAI crews (CrewAI appears only as a dependency shim comment in `main.py`). "Agent status" UX should be designed around the real SSE event types: `stage`, `iterate`, `average`, `done`, `error`.

Build health: `vite build` passes; **single 751 kB JS chunk** (no code splitting — recharts and all pages eager-loaded).

---

## 2. Page & Route Inventory

| Route | Component | Notes |
|---|---|---|
| `/` | `Landing` | hero, features, pricing |
| `/login`, `/register` | `Login` / `Register` (+`AuthLayout`) | |
| `/app` | redirect → `/optimize` | legacy |
| `/optimize` | `ChatOptimizePage` | **primary flow** (chat: JD → match → run → download) |
| `/dashboard` | `Dashboard` | stats, 2 usage charts, quota, recent resumes |
| `/dashboard/usage` | `Dashboard` (again) | duplicate route, duplicate sidebar item |
| `/dashboard/resumes` | `Resumes` | paginated table |
| `/dashboard/matches` | `JobMatches` | Pro-gated |
| `/dashboard/settings` | `Settings` | profile, plan, promo, danger zone |
| `/profiles`, `/profiles/new` | `ProfilesPage` / `ProfileNewPage` | parse / AI-interview / editor |
| `/admin` (+4 children) | `AdminLayout` → Dashboard, Users, UserDetail, PromoCodes, Analytics | dark-theme surface, `AdminRoute`-gated |
| `*` | redirect → `/` | **no 404 page** |
| *(unrouted)* | `AppPage` | imported in `main.jsx` but never rendered — dead |

---

## 3. User Flows (mapped)

1. **Optimize (core):** paste JD text/URL → (`/jd/scrape` if URL) → `/profile/match` → pick profile card or type number → optional instruction → `/profile/prepare-job` → `/user/sse-token` → open SSE `/status/{job_id}` → `/run-pipeline` → stage/iteration/score messages as chat bubbles → `/download/{id}?token=`.
2. **Profile creation:** upload → `/profile/parse` → editor; or AI interview (`/profile/ai-interview/message` → `/finish`) → editor → `POST /profiles`.
3. **Auth:** register → `/dashboard`; login → `/optimize` (inconsistent destinations); logout is client-side only (`POST /auth/logout` never called).
4. **Dashboard/Resumes/Matches/Settings:** straightforward fetch-render; promo redemption refreshes `me`.
5. **Admin:** stats cards, user search/paginate, plan/suspend/promote patches, promo-code CRUD, 5 analytics charts.

### API → UI dependency map

- **Live UI uses:** `/auth/login|register|me(GET,PUT)`, `/user/sse-token`, `/user/redeem-promo-code`, `/profiles` CRUD, `/profile/parse|match|prepare-job|ai-interview/*`, `/jd/scrape`, `/run-pipeline`, `/status/{id}` (SSE), `/download/{id}`, `/dashboard/summary|usage-history|match-analytics|resumes|job-matches`, `/admin/stats|analytics|users(+patch)|promo-codes(+patch)`.
- **Used only by dead `AppPage`:** `POST /upload`, `POST /analyze-jd`, `POST /generate-doc`.
- **Backend endpoints with no frontend consumer:** `POST /admin/bootstrap`, `GET /admin/promo-codes/{id}/stats`, `GET|POST /admin/provider-costs`, `POST /scrape-jobs`, `POST /auth/logout`, `GET /health`. ← several of these are ready-made feeds for the Phase 3 admin dashboard (provider costs, promo stats) — no new backend needed for those.

---

## 4. Feature Triage — KEEP / MOVE TO ADMIN / REMOVE

> Default-to-removal applied. **Nothing is deleted until this table is approved.**

### KEEP (serves the end user's core job)

| Item | Justification |
|---|---|
| `ChatOptimizePage` chat flow (JD/URL input, profile match cards, SSE progress, download CTA) | The core job; plan docs name it the primary UI |
| `ProfilesPage`, `ProfileNewPage` + `ProfileEditor`, `BulletEditor`, `SkillChips`, `InterviewChat` | Profile is the input asset for every optimization |
| Dashboard: greeting, 4 stat cards, daily-quota card, recent-resumes table, `OnboardingBanner` | At-a-glance "where am I" for the user |
| Dashboard: ONE usage chart (the 30-day area chart, given the day-range selector) | Users care about their own usage vs quota |
| `Resumes` page (history + downloads) | Users retrieve past work |
| `JobMatches` + Pro gate | User-facing value; match % per job is decision-relevant |
| `Settings`: profile form, plan display, promo redemption | Account management |
| `Landing`, `Login`, `Register`, `AuthLayout` | Acquisition + auth |
| `Sidebar`, `TopNav`, `TrialBanner`, UI kit in use (`Button`, `Card`, `Badge`, `QuotaBar`) | Chrome and design system seeds |
| Entire admin surface (rebuilt in Phase 3): stats, users, user detail, promo codes, analytics | Ops needs it; becomes the Phase 3 foundation |

### MOVE TO ADMIN

| Item | Justification |
|---|---|
| `UsageTrendsChart` **"Tokens" metric** (user Dashboard) | Token counts are cost/ops telemetry, not user value — belongs beside admin cost charts |
| `MatchAnalytics` chart (avg similarity over time, user Dashboard) | Aggregate match-quality is pipeline diagnostics; users already see per-job match % |
| SSE raw "live log" concept (currently only on dead `AppPage`) | Raw agent logs are admin observability; users get the designed pipeline animation in Phase 2 instead |

### REMOVE

| Item | Justification |
|---|---|
| `AppPage.jsx` (orphaned) + its import in `main.jsx` | Unrouted; plan doc explicitly says ChatOptimizePage replaced it |
| `pipelineStore.js` | Only consumer is dead AppPage |
| `PipelineStep.jsx` | Only consumer is dead AppPage (Phase 2 builds a new pipeline viz) |
| `ScoreCard.jsx`, `CircularProgress.jsx` | Currently dead; *flagged*: likely resurrected in the Phase 2 score-reveal — confirm remove vs. park |
| `/dashboard/usage` route + "Usage" sidebar item | Renders the identical Dashboard component; pure duplication |
| One of Dashboard's two usage charts (`UsageTrendsChart` runs/uploads duplicate the inline area chart) | Same data charted twice on one page |
| Settings "Upgrade to Pro — $9/mo" button | No onClick, no payment integration — a dead CTA every free user is funneled to |
| Settings "Delete account" button | Placeholder that toasts "coming soon" — an error-toast button in a danger zone erodes trust |
| Fake mid-run instruction handling in ChatOptimizePage | Claims "optimizer will apply it next iteration" but **sends nothing to the backend** — deceptive; disable input or wire it for real |
| Unused deps: `@radix-ui/react-dialog`, `@radix-ui/react-slot`, `tailwind-merge` | Dead weight (Phase 1 may re-add radix deliberately) |
| Vite `/api` proxy block | Client calls `VITE_API_URL` directly; proxy is never hit |
| `/upload`, `/analyze-jd`, `/generate-doc` frontend calls | Die with AppPage (backend routes themselves are Stage B inventory) |
| "Powered by Gemini 2.5 + Claude" + "Gemini 2.5 Flash rewrites…" copy on Landing | Vendor implementation details as marketing; rewritten in Phase 1 (copy change, not feature removal) |

---

## 5. Frontend Bug List

**Broken / incorrect behavior**
1. **FOUC/dark flash:** `index.html` hardcodes `background:#0f172a` (dark slate) while the app is light `#FAFAF8` — dark flash on every load; stale base styles.
2. **Missing favicon:** `/vite.svg` referenced; no `public/` directory exists → 404 on every page load.
3. **Settings quota always full:** `QuotaBar used={user?.limits?.daily_uploads} total={user?.limits?.daily_uploads}` — used === total by construction ([Settings.jsx:87](resume-optimizer/frontend/src/pages/Settings.jsx#L87)).
4. **Fake instruction ack** during a running pipeline (no API call) — [ChatOptimizePage.jsx:115-119](resume-optimizer/frontend/src/pages/ChatOptimizePage.jsx#L115-L119).
5. **EventSource leak:** in `startPipeline`, if `POST /run-pipeline` throws after SSE opened, the catch never closes `esRef` ([ChatOptimizePage.jsx:96-105](resume-optimizer/frontend/src/pages/ChatOptimizePage.jsx#L96-L105)).
6. **Logout never hits `POST /auth/logout`** — token blocklist infra exists server-side but tokens stay valid after "logout".
7. **CostTrendChart axis lies:** plots `cost_cents` on the Y-axis but tooltip divides by 100 (dollars); also computes an unused `cost_dollars` and passes an invalid `formatter` prop to `<Area>`.
8. **Misleading empty states:** Dashboard, Resumes, JobMatches, UserList, AdminDashboard have no `.catch` — a failed fetch renders "No data yet" + unhandled promise rejection.
9. **InterviewChat dead-end:** if `/ai-interview/finish` fails, error is swallowed; user is stuck on "generating your profile…" with the input hidden and no retry.
10. **Double messaging on 429:** axios interceptor toasts the upgrade message *and* page-level catches show generic failures.

**Inconsistencies / UX debt**
11. Register lands on `/dashboard`, Login lands on `/optimize`.
12. Stale `/app` links (Dashboard empty state, Resumes CTA) ride a redirect hop.
13. Greeting says "Create one at /profiles/new" as plain text, not a link.
14. Dashboard fires two overlapping `usage-history` requests on mount (two effects, two state vars).
15. `localStorage.user` goes stale (plan/admin changes invisible until re-login; `fetchMe` only runs from Settings).
16. No 404 page — bad URLs silently land on marketing page even when authenticated.
17. AuthLayout advertises scorers "ATS, Impact, Skills, **Structure**" but actual scorers are ATS / Impact / Skills Gap / **Readability**.
18. JobMatches uses array index as React key.
19. `AdminAnalytics.jsx` lives in `pages/` while its four siblings live in `pages/admin/`.

**Responsive & a11y (feeds Phases 4–5)**
20. Fixed `w-60` sidebar with no collapse — app is unusable at 360 px; admin (`w-56`) same; tables have no overflow containers.
21. Icon-only buttons lack `aria-label` (logout, send, password-eye, bullet edit/delete, promo copy).
22. Heavy use of `text-gray-400`/`text-[10px]` on white — likely WCAG AA contrast failures.
23. No `prefers-reduced-motion` handling anywhere (Phase 2 prerequisite).
24. Admin charts use default recharts palette (#3b82f6 blue) — off-brand vs `#7F77DD`; user-facing `UsageTrendsChart`/`MatchAnalytics` use raw `bg-blue-500` buttons and `rounded-lg shadow` cards that ignore the design system.

**Build**
25. Single 751 kB chunk; no `React.lazy`/route splitting; Google Fonts via render-blocking CSS `@import`.

---

## 6. Phase 1 — Design Direction (decided & implemented 2026-06-11)

**Chosen direction: "Manila & Ink"** (warm editorial; selected over "Midnight Terminal" and "Aurora Studio").
The resume-as-fine-paper metaphor: paper/ink surfaces, deep editorial green accent (`#1A6B52` light / `#4DB892` dark), amber highlight, Fraunces display serif + Archivo UI + JetBrains Mono for data.

Implementation:
- **Tokens:** RGB-triplet CSS variables in `src/index.css` (`:root` = paper, `.dark` = warm ink), mapped to semantic Tailwind names in `tailwind.config.js` (`surface`, `card`, `surface-2`, `ink/-mute/-faint`, `line`, `primary/-dark`, `accent-soft`, `hilite/-soft`, `err/-soft`); shadows are token-driven too. Legacy aliases (`teal`, `amber`, `muted`) keep old class names working.
- **Dark mode:** `darkMode: 'class'`; pre-paint inline script in `index.html` (kills the FOUC bug); `useTheme` hook (`src/theme.js`) — explicit choice persisted in `localStorage('theme')`, follows OS otherwise; `ThemeToggle` in Sidebar + TopNav.
- **Fonts:** Google Fonts `<link>` with preconnect (replaces render-blocking CSS `@import`).
- **Sweep:** all user-facing pages/components tokenized. Sidebar is a fixed "book spine" (ink in both themes); auth brand panel + landing pricing band are fixed ink/green. Admin pages intentionally untouched (Phase 3 rebuild).
- **Bugs fixed in passing:** FOUC dark-flash, missing favicon (`public/favicon.svg`), Settings dead buttons, AuthLayout scorer copy, JobMatches index-as-key, `prefers-reduced-motion` base styles added, themed toast styling, stale `/app` links → `/optimize`.
- **Verified:** `vite build` green; Playwright screenshots of landing + login in both themes, no console errors.

## 7. Phase 2 — Motion & 3D (implemented 2026-06-12)

Five motion moments, each with non-negotiable guardrails honored (reduced-motion static fallbacks, lazy 3D, no blocked paint, no delayed user actions):
1. **Landing hero (R3F):** floating résumé-sheet scene (`components/three/HeroScene.jsx`, three 0.169 + @react-three/fiber 8.17 for React 18) with pointer parallax; `HeroVisual.jsx` gates it — WebGL probe + low-power heuristic (deviceMemory ≤ 4 or width < 768) + `prefers-reduced-motion` all fall back to a pure-CSS static paper composition (also the Suspense fallback, so first paint is never blocked).
2. **Staggered hero reveal:** CSS-only `.reveal` classes; collapsed to instant under reduced motion.
3. **Drop-zone tilt:** `TiltCard.jsx` pointer-tracked 3D tilt + drag-over lift on the profile upload zone; inert under reduced motion.
4. **Pipeline visualization:** `PipelineProgress.jsx` on `/optimize`, driven by real SSE stages (`jd_analysis → score → agent → humanize → generate`), with iteration badge + live score ticker. `agent_step` telemetry deliberately ignored (admin material).
5. **Score reveal:** `ScoreReveal.jsx` — serif count-up (`useCountUp`), staggered sub-score cards, then the download CTA. Uses `done.final_score`/`iterations` + last `average.scores`.

Infrastructure: route-level code splitting (React.lazy for every page) — **initial bundle 749 kB → 239 kB (80 kB gzip)**; recharts (341 kB) loads only on dashboard/admin; the 3D chunk (821 kB) only on capable landing visits. Findings fixed en route: dead `iterate` SSE handler removed (iteration rides `average` events), EventSource leak on failed `/run-pipeline` closed.

Verified: build green; Playwright shots — 3D hero light/dark, reduced-motion fallback, 360 px mobile (no horizontal scroll, zero console errors).

## 8. Phase 3 — Admin Monitoring Dashboard (implemented 2026-06-12)

Admin is wrapped in a `.dark` token scope (always-ink, independent of user theme) and reorganized: **Overview · Pipeline Runs (new) · Users · Promo Codes · Analytics**.

- **Overview:** stat cards now include the previously-unsurfaced `/admin/stats` cost fields (spend today/month, ~$/run) plus stuck-jobs alerting; 14-day pipeline-health chart; live recent-runs feed.
- **Pipeline Runs (new page):** paginated, status-filterable run table (user, score, iterations, cost, duration, started) with expandable per-run **event timeline** (stage-by-stage timing computed from `PipelineEvent` timestamps, error messages inline). Raw `agent_step` telemetry is visible here — completing the "live log moves to admin" triage item.
- **Analytics:** moved into `pages/admin/Analytics.jsx` (fixes the stray-file inconsistency); 5 generic chart components replaced by brand-palette charts with proper loading/error/empty states; **cost chart now plots dollars (cents-axis bug fixed)**; the unconsumed `GET /admin/provider-costs` endpoint now renders an LLM provider pricing table.
- **Cost & quota signals:** per-run `cost_usd` in the runs table; aggregate spend on Overview + Analytics. Note: per-run token counts only exist transiently in the `done` SSE event (visible in the run timeline ≤ 24 h); durable token persistence is a Stage B candidate.
- **Deferred:** admin-wide match-quality chart needs a new Delta Lake aggregation (slow read, modest value) — logged for Stage B instead of forcing it into Stage A.

Verified: build green; Playwright screenshots with stubbed admin API (overview, runs + expanded timeline, analytics) — no console errors. Backend admin tests: 2 pass / pre-existing fixture failures (`KeyError: 'user'` + Windows SQLite teardown locks) reproduce identically on pristine code — not introduced by the new endpoints.

## 9. Phase 4 — Mobile-First Responsive Pass (implemented 2026-06-12)

- **`AppShell`** (`components/layout/AppShell.jsx`): shared authenticated frame — desktop sidebar ≥ lg, mobile ink top bar + slide-over drawer below (overlay click + Escape close, auto-close on navigation). Sidebar refactored to export `SidebarContent` shared by both. All 6 user pages migrated; the chat page uses `scroll={false}` to keep its pinned-input column layout.
- **Admin:** same pattern inside `AdminLayout` (desktop aside / mobile top bar + drawer).
- **Tables:** Dashboard recent-resumes, Resumes, admin Users/Promo Codes/Pipeline Runs wrapped in `overflow-x-auto` with sensible `min-w`.
- **Density fixes:** page paddings `px-4 sm:px-8`, ProfileEditor contact + PromoCodes form grids collapse to one column on xs, TopNav tightened (Sign in hidden < sm).
- **Verified:** Playwright sweep at **360/768/1024/1440** across dashboard, optimize, and admin runs — zero horizontal scroll, zero page errors; drawer interaction screenshot at 360.

## 10. Phase 5 — Zero-Bug Pass (implemented 2026-06-12) · **STAGE A COMPLETE**

Fixes in this pass (everything else on the bug list was already fixed in Phases 1–4):
- **401 interceptor no longer clobbers login/register failures** (bad credentials used to trigger a redirect-reload that ate the error toast).
- **Logout now revokes server-side** — `POST /auth/logout` (token blocklist) fired with the captured token before clearing local state.
- **Stale cached user fixed** — `AppShell` refreshes `/auth/me` once per app load, so plan/admin changes appear without re-login.
- **Settings quota bar shows real usage** (fetches `today.runs` from `/dashboard/summary`; previously used === total by construction).
- **Honest error states** for Dashboard / Resumes / Job Matches (failed fetches no longer masquerade as "no data yet").
- **OnboardingBanner fetches profiles itself** — no longer tells users with profiles to create one just because the store was cold.
- **InterviewChat dead-end fixed** — a failed `/ai-interview/finish` now shows an error with a working "Try again", instead of an eternal "generating…".
- **429 handling** in chat shows the upgrade message instead of a generic failure.
- Register now lands on `/optimize` (was `/dashboard`, inconsistent with login); chat greeting links to `/profiles/new`; **404 page** added (was a silent redirect); remaining icon-only buttons got `aria-label`s (bullet edit/remove, skill remove, promo copy, interview send).

**Final verification:** production build green; Playwright sweep of **16 routes × 2 themes = 32 combos with ZERO console/page errors**; dark mode visually verified on dashboard/settings/404.

## 11. Stage A Backend-Touch Log

| Date | Touch | Reason |
|---|---|---|
| 2026-06-12 | `backend/admin/router.py`: added read-only `GET /admin/pipeline-runs` (paginated list w/ status filter, score, cost, duration) and `GET /admin/pipeline-runs/{id}/events` (event timeline). Also added `PipelineEvent` to the models import. | Phase 3 pipeline observability — no existing endpoint exposed run-level status/timing. Read-only, permitted under the Stage A constraint. |

Pre-identified likely touches for later phases (read-only unless noted):
- Phase 3 can consume existing `GET /admin/provider-costs` and `GET /admin/promo-codes/{id}/stats` (already built, never consumed).
- Phase 3 may need a read-only "recent pipeline runs" admin endpoint (per-stage timing currently only in `PipelineEvent` rows).
- Phase 2 pipeline visualization needs no backend change — SSE already emits `stage/iterate/average/done/error`.
