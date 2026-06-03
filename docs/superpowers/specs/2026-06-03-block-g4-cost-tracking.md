# Block G.4 — Cost Tracking: Design Spec
**Date:** 2026-06-03
**Branch:** backend_design
**Status:** Approved

## Overview

Track LLM API token usage and costs per pipeline run. Extract input/output token counts from Anthropic/Google/Groq LLM responses, calculate costs using admin-managed provider pricing, and surface costs in admin dashboard, user dashboard, and per-run pipeline responses. Costs are calculated in real-time using the latest provider pricing from the database.

## Out of Scope

- Stripe integration (deferred to billing phase)
- Hard cost limits or budget alerts
- Cost attribution by feature (e.g., "job scraping cost $X")
- Forecasting or analytics beyond totals/averages

---

## Section 1: Data Layer

### New Table: `provider_costs`

Admin-managed pricing table with one row per provider version:

```sql
CREATE TABLE provider_costs (
    id UUID PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,  -- "anthropic", "google", "groq"
    input_cost_per_1m_tokens FLOAT NOT NULL,  -- cents
    output_cost_per_1m_tokens FLOAT NOT NULL,  -- cents
    active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE(provider, active)  -- ensures only one active=true per provider; multiple inactive rows allowed
);
```

**Initial seed data** (in migration or `db.session.init_db()`):
- Anthropic: input=0.003 cents, output=0.009 cents per 1M tokens
- Google Gemini: input=0.0005 cents, output=0.0015 cents per 1M tokens
- Groq: input=0.0001 cents, output=0.0001 cents per 1M tokens

### Delta Lake: Extend `daily_usage`

Add two columns to the existing `daily_usage` table:
- `input_tokens` (int64): Sum of all input tokens that day
- `output_tokens` (int64): Sum of all output tokens that day

Keep legacy `tokens_used` column (int64 = input_tokens + output_tokens) for backwards compatibility.

### Models

**ProviderCost** ORM model in `db/models.py`:
```python
class ProviderCost(Base):
    __tablename__ = "provider_costs"

    id = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    provider = Column(String(50), nullable=False)  # anthropic, google, groq
    input_cost_per_1m_tokens = Column(Float, nullable=False)
    output_cost_per_1m_tokens = Column(Float, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
```

---

## Section 2: Token Extraction + Cost Calculation

### LLM Module Changes (`backend/llm.py`)

Modify `complete(prompt: str, model: str, ...)` to return both text and token counts:

**Old return:** `str` (just the text)

**New return:** `dict` with structure:
```python
{
    "text": "...",
    "input_tokens": 1234,
    "output_tokens": 567
}
```

**Token extraction by provider:**
- **Anthropic**: Read `response.usage.input_tokens` and `response.usage.output_tokens` directly
- **Google Gemini**: Not directly exposed in standard SDK — default to `input_tokens=0, output_tokens=0` (known limitation, can be revisited)
- **Groq**: Read `response.usage.prompt_tokens` as input, `response.usage.completion_tokens` as output

### Agent Changes

Each agent (rewriter, humanizer, scorer, etc.) now receives a `response_dict` instead of just `response_text`:

```python
response_dict = await complete(prompt, model)
text = response_dict["text"]
tokens = response_dict.get("input_tokens", 0), response_dict.get("output_tokens", 0)
```

Agents accumulate tokens and return both text and token totals:

```python
async def rewrite_resume(...) -> dict:
    accumulated = {"input_tokens": 0, "output_tokens": 0}
    ...
    response = await complete(prompt, model)
    accumulated["input_tokens"] += response["input_tokens"]
    accumulated["output_tokens"] += response["output_tokens"]
    ...
    return {"text": rewritten_text, "tokens": accumulated}
```

### Pipeline Aggregation (`backend/main.py`)

In `_run_pipeline_task()`:

1. **Thread tokens through pipeline**: Each agent returns tokens; main loop accumulates
2. **Calculate cost**:
   ```python
   # Fetch active provider costs
   costs = await db.execute(select(ProviderCost).where((ProviderCost.provider == "anthropic") & (ProviderCost.active == True)))
   rate = costs.scalar_one()
   
   cost_cents = (input_tokens / 1_000_000 * rate.input_cost_per_1m_tokens) + \
                (output_tokens / 1_000_000 * rate.output_cost_per_1m_tokens)
   ```

3. **Write to Delta Lake**:
   ```python
   await asyncio.to_thread(write_daily_usage, {
       "user_id":       str(user.id),
       "date":          date.today().isoformat(),
       "pipeline_runs": 1,
       "uploads":       1,
       "input_tokens":  input_tokens,
       "output_tokens": output_tokens,
       "tokens_used":   input_tokens + output_tokens,  # Legacy
   })
   ```

4. **Return in response**: Include cost in pipeline completion response

---

## Section 3: Admin + User Dashboards

### Admin Dashboard (`GET /admin/stats`)

Extend `AdminStats` schema with cost metrics:

```python
class AdminStats(BaseModel):
    # ... existing fields ...
    total_cost_cents_today: int         # Sum of all runs today
    total_cost_cents_month: int         # Sum since 1st of month
    total_tokens_today: int             # Sum of input_tokens + output_tokens
    avg_cost_per_run: float             # total_cost_today / pipeline_runs_today (or 0)
```

**Query logic:**
```sql
SELECT 
  SUM(CAST(input_tokens AS FLOAT)/1000000 * ic + CAST(output_tokens AS FLOAT)/1000000 * oc) as cost
FROM daily_usage du
JOIN provider_costs pc ON du.provider = pc.provider AND pc.active = true
WHERE du.date >= DATE_TRUNC('day', NOW())
```

### User Dashboard (`GET /dashboard/usage-history`)

Extend response rows with cost column:

```python
{
    "date": "2026-06-03",
    "pipeline_runs": 5,
    "uploads": 5,
    "input_tokens": 12000,
    "output_tokens": 4000,
    "tokens_used": 16000,
    "cost_cents": 45     # Calculated on-the-fly using current provider rates
}
```

**Cost calculation:** Fetch active provider costs, multiply tokens by current rates (not stored in Delta, recomputed on read for freshness).

### Per-Run Response (`POST /pipeline/run`)

When pipeline completes, response includes:

```json
{
    "status": "done",
    "result": {...resume optimization data...},
    "cost_cents": 12,
    "tokens": {
        "input": 5432,
        "output": 2100
    }
}
```

---

## Section 4: Admin Endpoints for Pricing

### `POST /admin/provider-costs`

Create or update pricing for a provider. Request:

```json
{
    "provider": "anthropic",
    "input_cost_per_1m_tokens": 0.003,
    "output_cost_per_1m_tokens": 0.009
}
```

Logic:
- Mark current active row for provider as inactive
- Create new active row with new rates

Response (201): created row with `id`, `created_at`, `updated_at`

### `GET /admin/provider-costs`

List all pricing rows (active and inactive). Response:

```json
{
    "providers": [
        {
            "provider": "anthropic",
            "input_cost_per_1m_tokens": 0.003,
            "output_cost_per_1m_tokens": 0.009,
            "active": true,
            "updated_at": "2026-06-03T10:00:00Z"
        },
        ...
    ]
}
```

---

## Section 5: Tests

**TDD tests** (`backend/tests/test_cost_tracking.py`):

1. **Token extraction**: Mock Anthropic/Google/Groq responses → verify input/output tokens extracted correctly
2. **Cost calculation**: Given tokens and provider rates → verify cost_cents calculated correctly
3. **Pipeline integration**: Run full pipeline → verify tokens and cost flow through correctly
4. **Admin endpoints**: POST new pricing → GET returns it; old pricing marked inactive
5. **Dashboard**: Verify cost_cents appears in `/admin/stats` and `/dashboard/usage-history`
6. **Per-run response**: Verify pipeline response includes cost_cents and tokens
7. **Provider switch**: Switch provider → verify new rates used for next run
8. **Fractional costs**: Tokens < 1M → verify fractional cents calculated correctly
9. **Zero tokens (Google)**: Verify cost=0 when provider doesn't expose token counts

---

## Files Changed

| Action | Path |
|---|---|
| Create | `resume-optimizer/backend/alembic/versions/000X_add_cost_tracking.py` |
| Modify | `resume-optimizer/backend/db/models.py` |
| Modify | `resume-optimizer/backend/llm.py` |
| Modify | `resume-optimizer/backend/agents/*.py` (all agents) |
| Modify | `resume-optimizer/backend/main.py` |
| Modify | `resume-optimizer/backend/config.py` (cost helpers) |
| Modify | `resume-optimizer/backend/admin/schemas.py` |
| Modify | `resume-optimizer/backend/admin/router.py` |
| Modify | `resume-optimizer/backend/dashboard/router.py` |
| Create | `resume-optimizer/backend/tests/test_cost_tracking.py` |

---

## Security & Accuracy Notes

- Provider pricing is stored in DB and queryable by any authenticated user (fine; it's not secret)
- Costs are calculated fresh on each dashboard read (reflects current rates, not historical rates)
- Token counts from LLM responses are trusted (no validation); if provider lies about token usage, cost reflects that
- No audit trail of pricing changes (admin updates are not logged separately) — acceptable for internal use, would need audit log if exposed to customers
