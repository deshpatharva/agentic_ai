# Block G.5 — Analytics: Design Spec
**Date:** 2026-06-03
**Branch:** backend_design
**Status:** Approved

## Overview

Add analytics dashboards for users and admins. Users see personal usage trends (pipeline runs, costs, job match quality). Admins see system-wide metrics (user growth, plan distribution, API costs, job source breakdown, pipeline health). All charts built with Recharts; data sourced from Delta Lake (time-series) and PostgreSQL (users, subscriptions). Builds on G.4 (Cost Tracking) for cost charts.

## Out of Scope

- Forecasting or predictive analytics
- Custom report building
- Data export (CSV, PDF)
- Real-time dashboards (cached daily aggregates only)

---

## Section 1: User Analytics

### Enhanced Dashboard Page

Extend existing `/dashboard` with three new chart sections below the quota bar:

**1. Usage Trends Chart**
- Time-series line chart: Daily pipeline runs (blue), uploads (green)
- X-axis: date (YYYY-MM-DD), Y-axis: count
- Query: `GET /dashboard/usage-history?days=30` (already exists)
- Toggle buttons to switch between runs/uploads/tokens views
- Responsive container, Recharts `LineChart` + `Line` components

**2. Cost Trend Chart** (requires G.4)
- Area chart: Daily cost in cents
- X-axis: date, Y-axis: cost_cents
- Query: New endpoint `GET /dashboard/usage-history?days=30` extended to return cost_cents
- Shows user's personal API spend trend
- Recharts `AreaChart` + `Area` components

**3. Job Match Quality Chart**
- Composite chart: Daily match count (bar, left axis) + avg similarity score (line, right axis)
- X-axis: date, Y-axis (left): match count, Y-axis (right): similarity 0.0–1.0
- Query: New endpoint `GET /dashboard/match-analytics?days=30` (see below)
- Shows job scraping quality over time
- Recharts `ComposedChart` with `Bar` and `Line`

### New Endpoint: `GET /dashboard/match-analytics`

Query params: `days` (1–90, default 30)

Response:
```json
{
  "analytics": [
    {
      "date": "2026-06-03",
      "match_count": 5,
      "avg_similarity_score": 0.78,
      "source_breakdown": {
        "linkedin": 2,
        "indeed": 3
      }
    }
  ]
}
```

**Data source:** Delta Lake `job_matches` table, grouped by user_id + date

---

## Section 2: Admin Analytics Dashboard

### New Page: `/admin/analytics`

System-wide metrics with 5 charts:

**1. User Growth Trend** (line chart)
- X: date, Y: cumulative user count (or daily signups)
- Data: PostgreSQL `users` table, group by created_at date
- Shows: Adoption trend over time

**2. Plan Distribution** (pie chart)
- Slices: free, pro, enterprise user counts
- Current snapshot (not time-series)
- Shows: Subscription mix

**3. Daily API Costs** (area chart, requires G.4)
- X: date, Y: total_cost_cents (sum across all users)
- Data: Delta Lake `daily_usage`, sum cost_cents by date
- Shows: Operational expense trend

**4. Top Job Sources** (bar chart)
- X: source (linkedin, indeed, etc.), Y: match count
- Data: Delta Lake `job_matches`, group by source, all-time or last 30 days
- Shows: Which job boards drive most matches

**5. Pipeline Health** (line chart)
- Dual lines: daily successful runs, daily failed runs
- X: date, Y: count
- Data: PostgreSQL `pipeline_jobs`, group by date + status
- Shows: System reliability trend

### New Endpoint: `GET /admin/analytics`

Query params: `days` (1–90, default 30)

Response:
```json
{
  "user_growth": [
    {"date": "2026-06-03", "cumulative_users": 42, "daily_signups": 2}
  ],
  "plan_distribution": {
    "free": 25,
    "pro": 12,
    "enterprise": 5
  },
  "daily_costs": [
    {"date": "2026-06-03", "cost_cents": 4500}
  ],
  "source_counts": {
    "linkedin": 150,
    "indeed": 87,
    "other": 23
  },
  "pipeline_health": [
    {"date": "2026-06-03", "successful": 120, "failed": 3}
  ]
}
```

---

## Section 3: Implementation Details

### Frontend Components

**Dashboard.jsx enhancements:**
- Add `<UsageTrendsChart />` component (line chart for runs/uploads/tokens)
- Add `<CostTrendChart />` component (area chart for costs, conditional on G.4)
- Add `<JobQualityChart />` component (composed chart for matches + similarity)
- Each fetches data from `/dashboard/*` endpoints, handles loading/error states

**New AdminAnalytics.jsx page:**
- Layout: 5 charts in 2-column grid or stacked
- Fetch `/admin/analytics` on mount, pass to 5 chart components
- Day-range selector (7/30/90 days default to 30)
- Recharts charts: LineChart, AreaChart, PieChart, BarChart, ComposedChart

**New MatchAnalytics.jsx component:**
- Reusable: can be embedded in Dashboard or as standalone page
- Props: `days`, `userId` (if user-scoped), `className`
- Renders ComposedChart with match_count + avg_similarity_score

### Backend Endpoints

**`GET /dashboard/match-analytics?days=30`**
- Query: `read_usage_last_n_days(user_id, days)` from Delta, filter to job_matches
- Group by date, compute: match_count, avg(similarity_score), source_breakdown
- Return as JSON array of daily stats
- Auth: requires user token (user scoped)

**`GET /admin/analytics?days=30`**
- Query 1: `users` table, count by created_at
- Query 2: `users` table, group by plan
- Query 3: Delta `daily_usage`, sum cost_cents by date (requires G.4 migration)
- Query 4: Delta `job_matches`, count by source
- Query 5: `pipeline_jobs`, count by date + status
- Combine into response
- Auth: requires admin token

### Data Sources

| Chart | Data Source | Table |
|-------|---|---|
| Usage Trends | Delta Lake | `daily_usage` |
| Cost Trend | Delta Lake | `daily_usage` + G.4 `provider_costs` |
| Job Quality | Delta Lake | `job_matches` |
| User Growth | PostgreSQL | `users` |
| Plan Distribution | PostgreSQL | `users` |
| API Costs | Delta Lake | `daily_usage` + G.4 |
| Top Sources | Delta Lake | `job_matches` |
| Pipeline Health | PostgreSQL | `pipeline_jobs` |

---

## Section 4: Testing

**Backend tests** (`test_analytics.py`):
- Verify `/dashboard/match-analytics` returns correct shape
- Verify `/admin/analytics` returns correct aggregations
- Verify date filtering works (days=7, 30, 90)

**Frontend tests**:
- Snapshot tests: each chart component renders without error
- Verify data loading states (spinner while fetching)
- Verify error states (network error fallback message)

---

## Files Changed

| Action | Path |
|---|---|
| Modify | `resume-optimizer/frontend/src/pages/Dashboard.jsx` |
| Create | `resume-optimizer/frontend/src/pages/AdminAnalytics.jsx` |
| Create | `resume-optimizer/frontend/src/components/MatchAnalytics.jsx` |
| Modify | `resume-optimizer/backend/dashboard/router.py` |
| Modify | `resume-optimizer/backend/admin/router.py` |
| Create | `resume-optimizer/backend/tests/test_analytics.py` |

---

## Dependencies

- **Frontend:** Recharts 3.8.0 (already installed)
- **Backend:** No new dependencies (uses existing Delta Lake + SQLAlchemy)
- **Database:** No schema changes needed (reuses existing tables)
- **Prerequisite:** G.4 (Cost Tracking) must be complete for cost charts to work
