# Blueprint: Platform Bug Fixes, Cost/Token Analytics & AI Observability

**Author:** Senior Backend / AI Architect
**Date:** 2026-06-13
**Status:** Execution plan / for review
**Screenshot analyzed:** `bug/image.png` (referenced in prompt as `image_b53546.png`)

---

## 0. Grounding — how this stack actually works (read first)

The prompt assumes a **LiteLLM proxy server** with its own tracking DB, webhooks, and
models like `gpt-4o` / `claude-3-5-sonnet`. The real codebase differs, and the blueprint
below conforms to reality:

| Prompt assumption | Reality in this repo |
|---|---|
| LiteLLM **proxy** backend + tracking DB | LiteLLM **Python SDK** called directly in `backend/llm.py` (`litellm.acompletion`) |
| Proxy webhooks / callback logs | SDK-level: `response.usage`, `response._hidden_params["response_cost"]`, `litellm.completion_cost()`, `litellm.success_callback` |
| `gpt-4o`, `claude-3-5-sonnet`, `llama-3-70b` | `gemini/gemini-2.5-flash-lite`, `gemini/gemini-2.5-flash`, `groq/llama-3.1-8b-instant` (see `config.py`) |
| Cost tracking missing | **Exists** at job-aggregate level: `PipelineJob.cost_usd/input_tokens/output_tokens`, Delta `daily_usage`, admin `/stats` + `/analytics` |
| Per-model breakdown | **Does not exist** — all phases summed into one bucket per job (`main.py:618-745`) |

### The unifying primitive: a per-call LLM ledger

Tasks 4, 5, 6 and all of Part 2 share one missing primitive: **there is no per-call record of
which model was invoked, by whom, with what tokens/cost/latency.** Today `llm.complete()` returns
tokens/cost to its caller, which sums them into a job total and throws away the per-call detail.

We introduce **one** new table — `llm_call_log` — written by a single instrumentation point inside
`llm.py`. Everything downstream (per-model matrix, input-vs-output totals, tracing, TTFT, cache-hit
accounting, feedback binding) reads from it. Design it once here; Tasks 4–6 and Part 2 reference it.

```python
# backend/db/models.py  (new)
class LlmCallLog(Base):
    """Per-call LLM ledger — the source of truth for cost, token, and latency analytics."""
    __tablename__ = "llm_call_log"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    trace_id       = Column(String(36), nullable=True, index=True)   # groups calls in one agentic request
    user_id        = Column(Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    job_id         = Column(Uuid(), ForeignKey("pipeline_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    model          = Column(String(100), nullable=False, index=True)  # "groq/llama-3.1-8b-instant"
    provider       = Column(String(50),  nullable=False, index=True)  # "groq" | "google" | "anthropic"
    call_kind      = Column(String(40),  nullable=True)               # "scorer" | "chat_agent" | "rewriter" ...
    input_tokens   = Column(Integer, nullable=False, default=0)
    output_tokens  = Column(Integer, nullable=False, default=0)
    cost_usd       = Column(Float,   nullable=False, default=0.0)
    cost_source    = Column(String(20), nullable=False, default="litellm")  # "litellm" | "provider_table" | "zero"
    latency_ms     = Column(Integer, nullable=True)
    ttft_ms        = Column(Integer, nullable=True)                   # streaming only
    cache_hit      = Column(Boolean, nullable=False, default=False)
    created_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    __table_args__ = (
        Index("ix_llm_call_model_created", "model", "created_at"),
    )
```

Alembic `0016_add_llm_call_log.py` (next after the `0015_add_chat_sessions` migration from the
co-pilot work). This table is **append-only and high-volume** → 90-day TTL via the existing reaper
in `main.py::_reap_stuck_jobs`.

---

# PART 1 — Bug Fixes & Features

---

## Task 1 — Identity-Linked Session Display & File Upload Pipeline

### 1.1 Root Cause & Architectural Analysis

**Visual evidence (`bug/image.png`):** the sidebar footer shows a green avatar circle with **"D"**,
the literal text **"User"**, an **admin** badge, and a "Pro Trial — 3 days left" banner.

The "D" and "User" disagreement is the tell. In `Sidebar.jsx`:

```jsx
// line 92 — avatar initial
{(user?.full_name || user?.email || 'U')[0].toUpperCase()}   // → email "deshpatharva@…" → "D"
// line 95 — display name
<div className="...">{user?.full_name || 'User'}</div>        // → full_name empty → literal "User"
```

- **Backend:** `auth/router.py::_user_dict` returns `"full_name": user.full_name or ""`. Registration
  (`RegisterRequest.full_name: str = ""`) makes the name **optional** and defaults to empty. So this
  user registered with no name → `full_name == ""`.
- **Frontend inconsistency:** the avatar falls back `full_name → email → 'U'` (so it shows "D" from
  the email), but the name line falls back `full_name → 'User'` (a hardcoded string, **not** email).
  Result: identity is half-rendered and misleading.
- **Upload mapping — already solved by the data model.** The upload is a two-step flow:
  `POST /profile/parse` (`profiles/router.py:101-110`) extracts text + parses sections and returns
  `{raw_text, label, sections}` (the binary is read into memory and discarded), then
  `POST /profiles` (`create_profile`, `:27-43`) saves a `Profile` row with `user_id` (FK → identity),
  `raw_text` (full extracted text), and `sections` (structured JSON). So every uploaded resume's
  **content is already strictly mapped to the user**. The *only* thing not persisted is the original
  binary file (PDF/DOCX). For the optimizer as built — which consumes `raw_text`/`sections` and never
  the binary — that asset is dead weight, so we **deliberately do not persist it now.** (`storage.py`
  intentionally handles only pipeline **output** `.docx` files keyed by `job_id`.)

  **Deferred (future feature):** retain the original file to power a "preserve my original formatting"
  toggle on the optimized output. When that lands, the right shape is a single nullable
  `Profile.source_file_path` column (1:1 with the profile) + persisting bytes in the parse step — **not**
  a separate `UploadedAsset` table, which only earns its keep if a profile can own many independent
  assets (it can't). See §1.3-C.

### 1.2 LiteLLM Integration Strategy
N/A for identity display. For the upload pipeline, no LLM change — but the persisted asset's
`raw_text` continues to feed `_parse_sections()` via `MODEL_PROFILE_PARSER`
(`gemini/gemini-2.5-flash-lite`) exactly as today.

### 1.3 Step-by-Step Implementation Plan

**A. Fix identity display (frontend, 2 lines):**
1. Name line falls back through email's local-part before the literal:
   `user?.full_name || user?.email?.split('@')[0] || 'User'`.
2. Keep avatar logic but share one helper so the two never diverge.

**B. Make name capture explicit (backend, optional hardening):**
3. Keep `full_name` optional, but when empty, `_user_dict` should return a derived display fallback so
   *every* client is consistent (not just the sidebar). Add `"display_name"` to the dict.

**C. Upload persistence — REUSE the existing `Profile` row (no new storage now):**
4. **No change required for identity mapping.** Uploaded content is already persisted and
   user-owned via `Profile.user_id` + `raw_text` + `sections`. Adding blob storage / an
   `UploadedAsset` table now would be gold-plating — the optimizer never reads the binary.
5. The only fix `parse` genuinely needs is the input guard it currently lacks: reject oversized
   uploads (`len(contents) > MAX_UPLOAD_BYTES`) before reading/parsing.

**C-deferred. Original-file retention (only when the formatting toggle is built):**
6. Add a single nullable column `Profile.source_file_path` (1:1 with the profile). Do **not** create
   an `UploadedAsset` table and do **not** reuse `Resume.file_path` (that column belongs to the
   *optimized output* entity, not the uploaded source).
7. Extend `storage.py` with `upload_user_asset(data, *, user_id, kind, filename, email)` writing to a
   deterministic, user-partitioned key `profiles/{user_id}/{uuid}_{safe_filename}` with identity
   metadata, persist bytes in `parse`, thread the returned key through `create_profile` into
   `source_file_path`. This unlocks "optimize but keep my original formatting" on the output side.

### 1.4 Production-Grade Code Snippets

```jsx
// Sidebar.jsx — single source of truth for identity rendering
const displayName = user?.full_name?.trim() || user?.email?.split('@')[0] || 'User';
const initial = (user?.full_name || user?.email || 'U').trim()[0].toUpperCase();
// ...
<div className="w-8 h-8 rounded-full ...">{initial}</div>
<div className="text-sm font-medium truncate">{displayName}</div>
```

```python
# profiles/router.py — the ONLY immediate change: add the missing size guard.
# Identity mapping already happens downstream via Profile.user_id + raw_text + sections.
@profile_ops.post("/parse")
async def parse_profile(file: UploadFile = File(...),
                        current_user: User = Depends(get_current_user)) -> dict:
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:           # currently missing — only fix needed now
        raise HTTPException(status_code=413, detail="File too large.")
    raw_text = _extract_file_text(contents, file.filename or "")
    result = await _parse_sections(raw_text)
    result["raw_text"] = raw_text
    return result
```

**Deferred — only when the "preserve original formatting" toggle is built:**

```python
# storage.py — user-scoped asset upload with metadata tagging (NOT needed now)
import re, uuid
from datetime import datetime, timezone

_LOCAL_UPLOADS_DIR = Path(__file__).parent / "uploads"

def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "asset")[:120]

def upload_user_asset(data: bytes, *, user_id: str, kind: str, filename: str,
                      email: str | None = None) -> str:
    """Persist the original binary under a deterministic, user-partitioned key.
    Returns the storage key → store on Profile.source_file_path."""
    key = f"{kind}/{user_id}/{uuid.uuid4().hex}_{_safe_name(filename)}"
    metadata = {"user_id": str(user_id), "email": email or "", "kind": kind,
                "original_filename": filename or "",
                "uploaded_at": datetime.now(timezone.utc).isoformat()}
    if not AZURE_STORAGE_ACCOUNT_NAME:
        dest = _LOCAL_UPLOADS_DIR / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.with_suffix(dest.suffix + ".meta.json").write_text(json.dumps(metadata))
        return key
    client = _blob_service_client()
    blob = client.get_blob_client(container=OUTPUTS_CONTAINER, blob=key)
    blob.upload_blob(data, overwrite=True, metadata=metadata)  # identity tagged on the object
    return key
```
Then `parse` persists bytes and returns `asset_path`; `create_profile` writes it to the new
`Profile.source_file_path` column. Until that feature exists, none of this ships.

---

## Task 2 — Guarded User Onboarding & Profile Creation Flow

### 2.1 Root Cause & Architectural Analysis
Both operational paths **already exist** — `ProfileNewPage.jsx` toggles `view` between an
`UploadZone` (→ `POST /profile/parse`, Option A) and `InterviewChat` (→ `/profile/ai-interview/*`,
Option B). The gap is **enforcement**:
- `main.jsx` guards routes with `ProtectedRoute` (auth-only) — nothing checks profile completeness.
- Onboarding is a **dismissible, non-blocking** `OnboardingBanner` on the dashboard. A new user can
  dismiss it and roam the app with zero profiles, which is exactly what produces the empty-state
  optimize experience.

So Option A's "asynchronous background parsing" is the only genuinely new capability: today parse is
**synchronous** in the request. We make it a background job for large files.

### 2.2 LiteLLM Integration Strategy
Option A parsing uses `MODEL_PROFILE_PARSER`; Option B uses `MODEL_INTERVIEW_SYNTH` — both already
wired. For async parsing, reuse the existing `PipelineJob`/`PipelineEvent` SSE pattern so the
frontend can stream "parsing…/done" without new infrastructure.

### 2.3 Step-by-Step Implementation Plan
1. Add a backend completeness signal (see Task 3's `profile_status`) returned by `/auth/me`.
2. New `RequireProfile` route wrapper: if authenticated **and** `profile_status == "incomplete"`,
   redirect to `/onboarding` (a blocking wizard route) instead of rendering the dashboard/optimize.
3. Convert `ProfileNewPage` into the wizard target (it already has both paths); the only addition is a
   "skip"-free framing when entered via onboarding.
4. Make Option A async: `POST /profile/parse-async` creates a parse job, returns `job_id`, and a
   background task runs `_extract_file_text` + `_parse_sections`, emitting SSE events.

### 2.4 Production-Grade Code Snippets

```jsx
// components/RequireProfile.jsx — blocks core app until a profile exists
export default function RequireProfile({ children }) {
  const user = useAuthStore((s) => s.user);
  if (!user) return <Navigate to="/login" replace />;
  if (user.profile_status === 'incomplete') return <Navigate to="/onboarding" replace />;
  return children;
}
// main.jsx: wrap the gated routes
<Route path="/optimize" element={
  <ProtectedRoute><RequireProfile><ChatOptimizePage /></RequireProfile></ProtectedRoute>
} />
```

```python
# profiles/router.py — Option A as an async background parse job
@profile_ops.post("/parse-async")
async def parse_profile_async(background: BackgroundTasks,
                              file: UploadFile = File(...),
                              current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)) -> dict:
    contents = await file.read()
    asset_path = await asyncio.to_thread(upload_user_asset, contents,
        user_id=str(current_user.id), kind="profiles",
        filename=file.filename or "resume", email=current_user.email)
    job = PipelineJob(user_id=current_user.id, status=JobStatus.pending,
                      original_filename=file.filename or "resume", resume_text="")
    db.add(job); await db.commit(); await db.refresh(job)
    background.add_task(_parse_job_task, str(job.id), asset_path, file.filename)
    return {"job_id": str(job.id)}   # client subscribes to /status/{job_id}
```

---

## Task 3 — Middleware: Optimize Chat Window Profile Guardrail

### 3.1 Root Cause & Architectural Analysis
The new co-pilot route `POST /optimize/chat` (and the legacy flow) have **no profile-completeness
guard**. The co-pilot's system prompt softly tells the user to create a profile, but the endpoint
still runs, burns a Groq call, and creates a session. We need a hard backend gate returning a
structured warning payload the frontend can render as a directive.

"Incomplete" must be defined concretely. A profile is **complete** when the user owns ≥1 `Profile`
whose `sections` contain at least a non-empty `experience` (or `summary`) — not merely a row that
exists. This prevents an empty interview draft from counting.

### 3.2 LiteLLM Integration Strategy
This guard runs **before** any LiteLLM call — its entire purpose is to avoid spending a model call on
a user who can't be optimized. No LiteLLM functions involved.

### 3.3 Step-by-Step Implementation Plan
1. Add `profiles/status.py::compute_profile_status(user, db) -> Literal["complete","incomplete"]`.
2. Surface it on `/auth/me` (`_user_dict`) so the frontend `RequireProfile` (Task 2) and the chat
   page agree with the backend.
3. Add a FastAPI dependency `require_complete_profile` that raises `403` with the exact payload.
4. Apply it to `POST /optimize/chat` (and the legacy `/profile/match` entry if desired).

### 3.4 Production-Grade Code Snippets

```python
# profiles/status.py
from sqlalchemy import select
from db.models import Profile, User

async def compute_profile_status(user: User, db) -> str:
    profs = (await db.execute(select(Profile).where(Profile.user_id == user.id))).scalars().all()
    for p in profs:
        s = p.sections or {}
        exp = s.get("experience") or []
        if (isinstance(exp, list) and len(exp) > 0) or (s.get("summary") or "").strip():
            return "complete"
    return "incomplete"
```

```python
# chat/dependencies.py — hard gate, structured directive payload
from fastapi import Depends, HTTPException
from profiles.status import compute_profile_status

async def require_complete_profile(current_user: User = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_db)) -> User:
    if await compute_profile_status(current_user, db) == "incomplete":
        raise HTTPException(status_code=403, detail={
            "error": "profile_incomplete",
            "message": "Profile incomplete. You cannot use the optimization chat "
                       "window without an active profile.",
            "action": {"label": "Create your profile", "href": "/onboarding"},
        })
    return current_user

# chat/router.py
@router.post("/chat")
async def optimize_chat(body: ChatTurnRequest,
                        current_user: User = Depends(require_complete_profile),  # gate first
                        db: AsyncSession = Depends(get_db)):
    ...
```

```jsx
// ChatOptimizePage.jsx — render the directive instead of a generic error
if (res.status === 403) {
  const { detail } = await res.json();
  if (detail?.error === 'profile_incomplete') {
    updateMsg(assistantId, { content: detail.message, isError: true });
    // optionally surface detail.action as a button to detail.action.href
    return;
  }
}
```

---

## Task 4 — LiteLLM-Native Cost Reflection & Admin Audit

### 4.1 Root Cause & Architectural Analysis
Cost capture **exists but is fragile and lossy**:
- `llm.py::complete()` reads `response._hidden_params["response_cost"]` (LiteLLM-native). For Gemini
  and Groq, LiteLLM's bundled price map can return **0.0** when a model isn't in its cost table → the
  job records `cost_usd = 0` silently. The `ProviderCost` table (seeded in `db/session.py` for
  anthropic/google/groq) exists as a manual fallback but is **never consulted** — nothing recomputes
  cost from it.
- `stream_chat()` (the co-pilot) records tokens per `ChatMessage` but its cost never reaches the admin
  rollups (`/stats`, `/analytics` read only `PipelineJob.cost_usd`).
- Per-call detail is discarded (see §0).

### 4.2 LiteLLM Integration Strategy
- Primary: `litellm.completion_cost(completion_response=response)` — more reliable than digging
  `_hidden_params`, and accepts an override price map.
- Fallback: when `completion_cost` returns 0/raises, compute from the `ProviderCost` table:
  `cost = in_tok/1e6 * in_rate + out_tok/1e6 * out_rate`, tag `cost_source="provider_table"`.
- Register a `litellm.success_callback` (SDK-native, **not** a proxy webhook) as a defensive
  secondary logger; the primary write stays inline so we control the transaction.

### 4.3 Step-by-Step Implementation Plan
1. Add `utils/cost.py::resolve_cost(response, model, in_tok, out_tok, db_rates) -> (cost, source)`.
2. Instrument **one** place — `llm.complete()` and `llm.stream_chat()` — to (a) resolve cost via the
   helper, (b) write an `LlmCallLog` row. This makes every call auditable regardless of caller.
3. Cache `ProviderCost` rates in memory (refresh every N min) to avoid a DB hit per call.
4. Admin audit endpoint `GET /admin/cost-audit`: counts of `cost_source` over a window, flags the
   `zero` fraction so operators see when LiteLLM pricing is missing.

### 4.4 Production-Grade Code Snippets

```python
# utils/cost.py
import litellm

def resolve_cost(response, model: str, in_tok: int, out_tok: int,
                 rates: dict[str, tuple[float, float]]) -> tuple[float, str]:
    """Return (cost_usd, source). Tries LiteLLM native, falls back to the ProviderCost table."""
    try:
        c = litellm.completion_cost(completion_response=response)
        if c and c > 0:
            return float(c), "litellm"
    except Exception:
        pass
    provider = model.split("/", 1)[0]          # "groq/llama-3.1-8b-instant" -> "groq"
    provider = {"gemini": "google"}.get(provider, provider)
    if provider in rates:
        in_rate, out_rate = rates[provider]
        return (in_tok / 1e6) * in_rate + (out_tok / 1e6) * out_rate, "provider_table"
    return 0.0, "zero"
```

```python
# llm.py — single instrumentation point (inside complete(), after the call)
cost, source = resolve_cost(response, model, response.usage.prompt_tokens,
                            response.usage.completion_tokens, _provider_rates())
await _record_call(LlmCallLog(
    trace_id=_current_trace_id(), model=model, provider=model.split("/",1)[0],
    input_tokens=response.usage.prompt_tokens, output_tokens=response.usage.completion_tokens,
    cost_usd=cost, cost_source=source, latency_ms=latency_ms, call_kind=_current_call_kind(),
))
return {"text": ..., "input_tokens": ..., "output_tokens": ..., "cost_usd": cost}
```

> `_current_trace_id()` / `_current_call_kind()` read from a `contextvars.ContextVar` set per request
> (see Part 2 §1) — zero plumbing through every call site.

---

## Task 5 — Aggregate Platform Token Analytics (Input vs Output)

### 5.1 Root Cause & Architectural Analysis
Global input/output token sums **already live in Delta** `daily_usage`
(`input_tokens`, `output_tokens`, `tokens_used`, readable via `read_usage_last_n_days("")` with the
empty-string = all-users convention). The gap: the admin `/analytics` endpoint surfaces user growth,
daily costs, sources, and pipeline health — **but not the input-vs-output token split**. With
`llm_call_log` we can also serve this in real time without Delta latency.

### 5.2 LiteLLM Integration Strategy
Tokens originate from `response.usage.{prompt,completion}_tokens`, persisted per call in
`llm_call_log` (§0) and aggregated in Delta `daily_usage`. No proxy involved.

### 5.3 Step-by-Step Implementation Plan
1. `GET /admin/analytics/tokens?days=30` → time-bucketed `{date, input_tokens, output_tokens}` from
   `llm_call_log` (fast path) or Delta (historical), with `window ∈ {7,30,90}` filter.
2. Add totals card: `SUM(input_tokens)`, `SUM(output_tokens)`, ratio.
3. Frontend `AdminAnalytics`: stacked bar (input vs output) per day + a totals header.

### 5.4 Production-Grade Code Snippets

```python
# admin/router.py
@router.get("/analytics/tokens")
async def token_analytics(days: int = Query(30, ge=1, le=365),
                          _: User = Depends(require_admin),
                          db: AsyncSession = Depends(get_db)):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(
            func.date(LlmCallLog.created_at).label("day"),
            func.coalesce(func.sum(LlmCallLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmCallLog.output_tokens), 0).label("output_tokens"),
        ).where(LlmCallLog.created_at >= cutoff).group_by("day").order_by("day")
    )).all()
    series = [{"date": str(r.day), "input_tokens": r.input_tokens,
               "output_tokens": r.output_tokens} for r in rows]
    return {
        "window_days": days,
        "total_input_tokens":  sum(r["input_tokens"] for r in series),
        "total_output_tokens": sum(r["output_tokens"] for r in series),
        "series": series,
    }
```

---

## Task 6 — Per-Model Granular Token Matrix

### 6.1 Root Cause & Architectural Analysis
**Net-new.** `main.py:618-745` sums every phase's tokens into a single `total_input_tokens` /
`total_output_tokens` per job — model identity is erased. There is no place in the system that knows
"the scorer used `gemini-2.5-flash-lite` for X tokens vs the co-pilot used `llama-3.1-8b-instant` for
Y." The `llm_call_log.model` column (§0) is what makes this possible, because instrumentation lives
in `llm.py` where the model name is known.

### 6.2 LiteLLM Integration Strategy
The `model` string passed to `litellm.acompletion` is recorded verbatim per call. Provider is derived
from the prefix (`groq/`, `gemini/`, `anthropic/`). Cost per model uses the same `resolve_cost`
(Task 4).

### 6.3 Step-by-Step Implementation Plan
1. `GET /admin/analytics/by-model?days=30` → group `llm_call_log` by `model`.
2. Return a side-by-side matrix: per model → input tokens, output tokens, calls, cost, avg latency.
3. Frontend: a table + grouped bar chart (input vs output per model).

### 6.4 Production-Grade Code Snippets

```python
# admin/router.py
@router.get("/analytics/by-model")
async def by_model(days: int = Query(30, ge=1, le=365),
                   _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(
            LlmCallLog.model, LlmCallLog.provider,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmCallLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmCallLog.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(LlmCallLog.cost_usd), 0.0).label("cost_usd"),
            func.avg(LlmCallLog.latency_ms).label("avg_latency_ms"),
        ).where(LlmCallLog.created_at >= cutoff)
         .group_by(LlmCallLog.model, LlmCallLog.provider)
         .order_by(func.sum(LlmCallLog.cost_usd).desc())
    )).all()
    return {"window_days": days, "models": [
        {"model": r.model, "provider": r.provider, "calls": r.calls,
         "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
         "cost_usd": round(r.cost_usd, 6),
         "avg_latency_ms": round(r.avg_latency_ms or 0, 1)} for r in rows]}
```

---

# PART 2 — AI Observability Architecture

All four capabilities build on `llm_call_log` (§0) plus a per-request **trace context**.

## P2.1 — Distributed Request Tracing

### Analysis
Agentic requests fan out into many LLM calls (jd_analyzer → scorer → optimizer tools → humanizer; or
co-pilot turn → handoff → pipeline). Today nothing correlates them. We need a `trace_id` minted at
the edge and propagated to every `llm_call_log` row and SSE event.

### Integration Strategy
Use `contextvars.ContextVar` (async-safe, no threading of args) set in `LoggingMiddleware`
(`main.py` already mints a `request_id` there — promote it to `trace_id`). `llm.complete`/`stream_chat`
read it via `_current_trace_id()`. For background pipeline tasks (which leave the request scope),
pass `trace_id` into `_run_pipeline_task` explicitly and re-set the ContextVar at task entry.

### Implementation
```python
# observability/trace.py
import contextvars, uuid
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_call_kind: contextvars.ContextVar[str] = contextvars.ContextVar("call_kind", default="")

def new_trace() -> str:
    tid = uuid.uuid4().hex; _trace_id.set(tid); return tid
def current_trace() -> str: return _trace_id.get()
def set_call_kind(kind: str): _call_kind.set(kind)
```
```python
# main.py LoggingMiddleware.dispatch — reuse request_id as trace_id
from observability.trace import _trace_id
token = _trace_id.set(request.headers.get("X-Trace-ID") or str(uuid.uuid4()))
try:
    response = await call_next(request)
finally:
    _trace_id.reset(token)
response.headers["X-Trace-ID"] = _trace_id.get()
```
Every SSE event and `llm_call_log` row then carries `trace_id`, so an admin can reconstruct the full
fan-out: `SELECT * FROM llm_call_log WHERE trace_id = ? ORDER BY created_at`.

## P2.2 — Latency & Time-to-First-Token (TTFT)

### Analysis
`complete()` is non-streaming → only total latency. `stream_chat()` streams → we can measure **TTFT**
(time to first token chunk), the key signal for detecting a slow upstream/region. Neither is recorded
today.

### Integration Strategy
Wrap the call: `t0 = perf_counter()` before; record `latency_ms` after. In `stream_chat`, stamp
`ttft_ms` when the first `delta` arrives. Persist on `llm_call_log`. LiteLLM exposes the model/region
in `_hidden_params` for attribution.

### Implementation
```python
# llm.py::stream_chat — TTFT instrumentation
t0 = time.perf_counter(); ttft_ms = None
async for chunk in response:
    delta = chunk.choices[0].delta.content if chunk.choices else None
    if delta:
        if ttft_ms is None:
            ttft_ms = int((time.perf_counter() - t0) * 1000)   # first token latency
        yield {"type": "token", "text": delta}
    ...
# on completion: write LlmCallLog(ttft_ms=ttft_ms, latency_ms=int((perf_counter()-t0)*1000), ...)
```
Admin surfacing: `GET /admin/analytics/latency?days=7` → p50/p95 `ttft_ms` and `latency_ms` grouped by
`model`; alert when a model's p95 TTFT crosses a threshold.

## P2.3 — Semantic Caching & Cost Optimization

### Analysis
Identical/near-identical prompts (e.g. the same JD scored repeatedly) re-hit paid APIs. There's a
`JdScrapeCache` for scrape results but **no prompt-response cache**. Redis is **not** currently a
dependency (verified), so this is the one place worth adding it — or use LiteLLM's built-in caching.

### Integration Strategy
Two tiers:
- **Exact-match cache** (cheap, immediate): LiteLLM's native cache — `litellm.cache = Cache(type="redis", ...)` keyed on the normalized messages+model. Zero app code beyond config.
- **Semantic cache** (optional, higher hit rate): embed the prompt (cheap embedding model), nearest-neighbor lookup in Redis vector / `pgvector`; on hit above a cosine threshold, return the cached completion. Quantify savings: every cache hit writes an `llm_call_log` row with `cache_hit=true, cost_usd=0, cost_source="zero"` plus a `would_have_cost` we estimate from `resolve_cost` on the cached token counts.

### Implementation
```python
# llm.py bootstrap (exact-match, LiteLLM-native)
import litellm
from litellm.caching import Cache
if REDIS_URL:
    litellm.cache = Cache(type="redis", url=REDIS_URL)   # acompletion checks it automatically
```
Savings report: `GET /admin/analytics/cache-savings` →
`SUM(would_have_cost) WHERE cache_hit` over the window vs actual spend.

## P2.4 — Semantic Drift & Quality Evaluation Loops

### Analysis
No feedback signal is bound to prompt-response pairs. The co-pilot and the score reveal are natural
capture points (thumbs up/down on a reply, "regenerate", or accepting/rejecting the optimized resume).

### Integration Strategy
Add `llm_feedback(call_id FK → llm_call_log, signal ENUM[up,down,edit,accept,reject], note, created_at)`.
Bind feedback to the **specific** `llm_call_log` row via `trace_id` + message id, so a thumbs-down maps
to the exact model/version/prompt that produced it. Periodic eval job samples down-voted pairs and
re-scores them with an LLM-judge (reuse `MODEL_CRITIC = groq/llama-3.1-8b-instant`) to quantify drift
over time.

### Implementation
```python
@router.post("/feedback")
async def submit_feedback(body: FeedbackIn, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    db.add(LlmFeedback(call_id=body.call_id, user_id=user.id,
                       signal=body.signal, note=body.note or ""))
    await db.commit(); return {"ok": True}
```
Eval loop (scheduled): pull `signal="down"` pairs in the last week, run the critic model as judge,
store a rolling quality score per `model`; chart it next to the per-model matrix (Task 6) to catch
regressions when a model version changes.

---

## Consolidated migration & rollout order

1. **`0016_add_llm_call_log`** + `LlmCallLog` model — the shared backbone.
2. **`llm.py` instrumentation** (`resolve_cost` + `LlmCallLog` write + trace/TTFT) — unlocks Tasks 4–6 and P2.1/P2.2 at once.
3. **Identity fix** (Task 1A) — 2-line frontend change, ship immediately.
4. **`/profile/parse` size guard** (Task 1C) — one `413` check; reuses existing `Profile` persistence (no new storage). Original-file retention is **deferred** until the formatting-toggle feature.
5. **Profile status + guards** (Tasks 2, 3) — `compute_profile_status`, `require_complete_profile`, `RequireProfile`.
6. **Admin analytics endpoints** (Tasks 5, 6) + frontend charts.
7. **Observability extras** (P2.3 cache, P2.4 feedback) — additive, behind config flags.

## Risk notes
- `llm_call_log` is high-volume → enforce the 90-day TTL in the reaper; consider monthly partitions if call volume is high.
- `litellm.completion_cost` can still return 0 for unpriced models — the `provider_table` fallback and the `cost_source` audit column make that **visible** rather than silent.
- Adding Redis (P2.3) is the only new infra; keep it optional (`REDIS_URL` unset → no caching, no failure).
- Per-request `contextvars` must be reset in `finally` and re-set at background-task entry, or trace IDs leak across requests.
