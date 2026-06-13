# Resume Optimizer — Revamp Final Report

**Engagement:** two-stage designer-led revamp · **Dates:** 2026-06-11 → 2026-06-12
**Detail documents:** [stage-a-phase0-ux-audit.md](stage-a-phase0-ux-audit.md) (full Stage A log) · [stage-b-phase0-inventory.md](stage-b-phase0-inventory.md) (backend inventory + implementation record)
**State:** committed on `feature/architect_revamp` in grouped commits (admin UI · frontend Stage A · backend · tests · docs · P2 removal); not pushed.

---

## 1. Design direction & UX enhancements

**Direction: "Manila & Ink"** — chosen over "Midnight Terminal" (dark-first technical) and "Aurora Studio" (glassmorphic). The thesis: the product's object *is* a beautifully typeset paper document, so the interface borrows the trust language of fine paper and ink rather than generic SaaS gradients.

- **Token system:** every color lives as a CSS variable in `frontend/src/index.css` (`:root` = paper, `.dark` = warm ink) mapped to semantic Tailwind names (`ink`, `card`, `line`, `primary`, `hilite`, `err`…) in `tailwind.config.js`. Shadows and radii are tokens. Theming is centralized in two files.
- **Typography:** Fraunces (display serif) + Archivo (UI grotesque) + JetBrains Mono (scores/data), loaded via preconnected `<link>` (replaced a render-blocking CSS `@import` of Inter).
- **Dark mode:** class-based, persisted explicit choice, defaults to and live-tracks the OS preference, applied pre-paint by an inline script (which also fixed the legacy dark-flash FOUC). Toggle in sidebar + top nav. The admin surface is wrapped in a `.dark` token scope so it is always-ink regardless of user theme.
- **UX flow repairs:** single post-auth destination (`/optimize`), real 404 page, honest loading/empty/error states on every async surface, linkified guidance in the chat, working promo/quota displays, a11y labels on all icon-only controls, `prefers-reduced-motion` honored globally.

## 2. Features removed / moved (per approved triage)

**Removed (13 items, sign-off 2026-06-11):** orphaned `AppPage` + its dead dependency chain (`pipelineStore`, `PipelineStep`, `ScoreCard`, `CircularProgress`); duplicate `/dashboard/usage` route + nav item; duplicate dashboard usage chart; dead Settings "Upgrade — $9/mo" and placeholder "Delete account" buttons; the **fake mid-run instruction feature** (UI claimed instructions reached the optimizer; nothing was sent — input now disables during runs); unused deps (`@radix-ui/*`, `tailwind-merge`); dead Vite proxy; vendor-model marketing copy → **"Powered by Gemini · Groq · Anthropic"** (providers only, per direction).

**Moved to admin:** raw pipeline telemetry (`agent_step` events) → admin run timeline; token/cost signals → admin Overview + Analytics; aggregate match-quality monitoring → consciously deferred (needs a new Delta aggregation; logged, not approved).

## 3. Motion & 3D layer (with performance fallbacks)

Five moments, every guardrail honored:
1. **R3F hero** (`components/three/HeroScene.jsx`, three 0.169 + R3F 8.17): floating résumé sheets with ink lines and pointer parallax. Gated by `HeroVisual`: WebGL probe + low-power heuristic (`deviceMemory ≤ 4` or width < 768) + reduced-motion → **pure-CSS static paper composition**, which is also the Suspense fallback, so first paint is never blocked.
2. **Staggered hero reveal** — CSS-only, collapses to instant under reduced motion.
3. **Drop-zone tilt** (`TiltCard`) — pointer-tracked 3D tilt + drag-over lift; inert under reduced motion.
4. **Pipeline visualization** (`PipelineProgress`) — driven by the real SSE vocabulary (`jd_analysis → score → agent → humanize → generate`) with iteration badge and live score ticker.
5. **Score reveal** (`ScoreReveal`) — serif count-up, staggered sub-score bars, then the download CTA; instant under reduced motion.

**Performance:** route-level code splitting cut the initial bundle **749 kB → 239 kB (80 kB gzip)**; recharts (341 kB) loads only on chart routes; the 3D chunk (821 kB) loads only on capable landing visits. DPR capped at 1.75, `powerPreference: low-power`, 3 meshes + 2 lights.

## 4. Admin monitoring dashboard

Reorganized to **Overview · Pipeline Runs (new) · Users · Promo Codes · Analytics**, auth-gated (`AdminRoute` + backend `get_admin_user`), invisible to non-admins, mobile-ready.
- **Overview:** users/active/runs/stuck-jobs cards + previously-unsurfaced spend (today, month, ~$/run), 14-day health chart, live recent-runs feed.
- **Pipeline Runs:** paginated, status-filterable table (user, score, iterations, cost, duration) with expandable per-run **event timeline** — per-stage timing computed from `PipelineEvent` timestamps, errors inline, raw agent telemetry visible.
- **Analytics:** user growth, plan distribution, **LLM spend in real dollars** (cents-axis bug fixed), job sources, pipeline health, and the previously-unconsumed provider-pricing endpoint rendered as a table.

## 5. Stage A backend touches (complete log)

Exactly **one**: read-only `GET /admin/pipeline-runs` + `GET /admin/pipeline-runs/{id}/events` added to `admin/router.py` for run observability. Everything else in the admin dashboard consumes endpoints that already existed.

## 6. Stage B optimizations (approved P1 scope) with expected impact

| Item | Change | Impact |
|---|---|---|
| B1 | Scrape persistence batched into one Delta transaction (was up to ~150) | ~100× fewer commits; no tiny-file proliferation; faster all future reads |
| B2 | `/dashboard/summary` dropped both per-load Delta scans (usage scan removed; unread via count-only pruned read) | Biggest user-facing latency win — summary fires on every login |
| B3 | Year/month **partition** pushdown + column pruning in match reads (`raw_description` no longer read/returned) | Bounded I/O instead of full-table scans |
| B4 | Cached `BlobServiceClient`/credential | Removes per-call token negotiation from download paths |
| B5 | 120 s LLM timeout + one transient retry | Hung provider calls no longer stall runs for 15 min |
| B6 | `fabrication_guard` + JD HTML parse moved off the event loop | API stays responsive under concurrent pipeline load |

**Verification:** targeted backend suites 41/41 (9 new tests; 3 stale tests repaired); adjacent suites identical to pristine code (pre-existing Windows test-infra failures, proven via `git stash` comparison). Frontend: production build green; Playwright-verified across 4 breakpoints and 32 route×theme combos with zero console errors.

## Addendum — P3 reliability + E1 (approved & implemented 2026-06-12)

**E1:** the backend test suite is green for the first time — **205/205** (112/191 on pristine). Root cause was import-time `app.dependency_overrides` leaking across test modules; fixing isolation also unmasked and fixed **three real production bugs**: naive/aware datetime comparisons in promo redemption (SQLite), Postgres pool kwargs crashing SQLite engines, and Postgres-only constructs in migration 0013.

**P3:** filter-aware pagination in job matches (R1), working download fallback via PipelineJob (R2), LRU-bounded result cache (R3), robust LLM-JSON recovery in profile matching with clean 502s (R4), per-run token persistence — migration 0014 + admin Runs "Tokens" column (R5), and no more internal-error leakage in API details (R6). Seven new regression tests cover all of it.

## Addendum — P2 dead-code removal (approved & implemented 2026-06-12)

The endpoints orphaned by the Stage A frontend (`/upload`, `/analyze-jd`, `/generate-doc`), the consumer-less `/dashboard/match-analytics`, and the never-called scorer helper (whose removal also drops scikit-learn and a duplicate spaCy model load — faster cold start, less memory) are gone, along with their 11 orphaned tests. Suite green at **194/194**.

## Not done (explicitly unapproved — awaiting sign-off if ever wanted)

Stage B inventory group **P4** (LLM-JSON parser consolidation) — benefit estimate in the inventory doc.
