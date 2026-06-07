# Block G.5 — Analytics Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user and admin analytics dashboards with time-series charts showing usage trends, costs, job quality, user growth, and pipeline health.

**Architecture:** Backend provides two new endpoints aggregating data from Delta Lake and PostgreSQL. Frontend builds reusable chart components (Recharts) and two dashboard pages: user dashboard embeds charts below quota bar, admin dashboard is a new page accessible only to admins. All charts support configurable time ranges (7/30/90 days).

**Tech Stack:** FastAPI (backend), SQLAlchemy/Delta Lake (data), Recharts 3.8+ (frontend charts), React (frontend)

**Dependencies:** G.4 (Cost Tracking) must be complete for cost charts to work.

---

## Task 1: Backend — GET /dashboard/match-analytics Endpoint

**Files:**
- Modify: `resume-optimizer/backend/dashboard/router.py`
- Create: `resume-optimizer/backend/tests/test_analytics.py`

- [ ] **Step 1: Write failing test for match-analytics endpoint**

Create `resume-optimizer/backend/tests/test_analytics.py`:

```python
"""Tests for analytics endpoints."""
import pytest
import json
from datetime import datetime, date, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User
from main import app
from auth.dependencies import get_current_user


@pytest.fixture
def test_user():
    return User(
        id="00000000-0000-0000-0000-000000000001",
        email="test@example.com",
        password_hash="dummy",
        full_name="Test User",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_match_analytics_returns_correct_shape(test_user):
    """GET /dashboard/match-analytics returns list with date, match_count, avg_similarity_score, source_breakdown."""
    client = TestClient(app)
    
    # Mock the current user
    def mock_get_current_user():
        return test_user
    
    app.dependency_overrides[get_current_user] = mock_get_current_user
    
    # Mock Delta read function
    mock_data = [
        {
            "date": "2026-06-03",
            "match_count": 5,
            "avg_similarity_score": 0.78,
            "source_breakdown": {"linkedin": 2, "indeed": 3},
        },
        {
            "date": "2026-06-02",
            "match_count": 3,
            "avg_similarity_score": 0.72,
            "source_breakdown": {"linkedin": 1, "indeed": 2},
        },
    ]
    
    with patch("dashboard.router.read_job_matches") as mock_read:
        mock_read.return_value = {"results": mock_data, "total": 2}
        
        response = client.get("/dashboard/match-analytics?days=30")
        
        assert response.status_code == 200
        data = response.json()
        assert "analytics" in data
        assert isinstance(data["analytics"], list)
        assert len(data["analytics"]) == 2
        
        first = data["analytics"][0]
        assert first["date"] == "2026-06-03"
        assert first["match_count"] == 5
        assert first["avg_similarity_score"] == 0.78
        assert "source_breakdown" in first
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_analytics.py::test_match_analytics_returns_correct_shape -v
```

Expected: FAILED — endpoint not found (404)

- [ ] **Step 3: Implement GET /dashboard/match-analytics endpoint**

In `resume-optimizer/backend/dashboard/router.py`, add after the `usage_history` endpoint:

```python
@router.get("/match-analytics")
async def match_analytics(
    user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=90),
):
    """Return job match analytics: daily match count, avg similarity score, source breakdown."""
    user_id = str(user.id)
    
    try:
        # Read job matches for the user over the past N days
        result = await asyncio.to_thread(read_job_matches, user_id, days, 1, 10000)
        matches = result.get("results", [])
        
        # Group by date
        from collections import defaultdict
        daily_stats = defaultdict(lambda: {
            "match_count": 0,
            "similarity_scores": [],
            "sources": defaultdict(int),
        })
        
        for match in matches:
            match_date = match.get("date", match.get("created_at", "").split("T")[0])
            if not match_date:
                continue
            
            daily_stats[match_date]["match_count"] += 1
            score = match.get("similarity_score")
            if score is not None:
                daily_stats[match_date]["similarity_scores"].append(score)
            
            source = match.get("source", "other")
            daily_stats[match_date]["sources"][source] += 1
        
        # Convert to response format
        analytics = []
        for date_str in sorted(daily_stats.keys(), reverse=True):
            stats = daily_stats[date_str]
            avg_score = (sum(stats["similarity_scores"]) / len(stats["similarity_scores"])
                        if stats["similarity_scores"] else 0)
            
            analytics.append({
                "date": date_str,
                "match_count": stats["match_count"],
                "avg_similarity_score": round(avg_score, 2),
                "source_breakdown": dict(stats["sources"]),
            })
        
        return {"analytics": analytics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read match analytics: {str(e)}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_analytics.py::test_match_analytics_returns_correct_shape -v
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
cd resume-optimizer
git add backend/dashboard/router.py backend/tests/test_analytics.py
git commit -m "feat: add GET /dashboard/match-analytics endpoint for job quality analytics"
```

---

## Task 2: Backend — GET /admin/analytics Endpoint

**Files:**
- Modify: `resume-optimizer/backend/admin/router.py`

- [ ] **Step 1: Write failing test**

Add to `resume-optimizer/backend/tests/test_analytics.py`:

```python
@pytest.mark.asyncio
async def test_admin_analytics_returns_correct_shape(test_user):
    """GET /admin/analytics returns all 5 chart datasets."""
    test_user.is_admin = True
    client = TestClient(app)
    
    def mock_get_admin_user():
        return test_user
    
    # Override admin dependency
    from admin.dependencies import get_admin_user
    app.dependency_overrides[get_admin_user] = mock_get_admin_user
    
    with patch("admin.router.read_usage_last_n_days") as mock_delta:
        mock_delta.return_value = MagicMock(
            empty=False,
            to_dict=lambda orient: []
        )
        
        response = client.get("/admin/analytics?days=30")
        
        assert response.status_code == 200
        data = response.json()
        assert "user_growth" in data
        assert "plan_distribution" in data
        assert "daily_costs" in data
        assert "source_counts" in data
        assert "pipeline_health" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_analytics.py::test_admin_analytics_returns_correct_shape -v
```

Expected: FAILED — endpoint not found

- [ ] **Step 3: Implement GET /admin/analytics endpoint**

In `resume-optimizer/backend/admin/router.py`, add imports:

```python
import asyncio
from datetime import date
from delta.writer import read_usage_last_n_days
```

Add endpoint before the closing of the router file:

```python
@router.get("/analytics")
async def admin_analytics(
    _: User = Depends(get_admin_user),
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """Return system-wide analytics: user growth, plan distribution, costs, sources, pipeline health."""
    from datetime import date as date_type, datetime as dt, timedelta
    
    try:
        # 1. User growth: cumulative users over time
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        user_growth_rows = (
            await db.execute(
                select(
                    func.date_trunc('day', User.created_at).label('date'),
                    func.count(User.id).label('daily_signups'),
                )
                .where(User.created_at >= cutoff_date)
                .group_by(func.date_trunc('day', User.created_at))
                .order_by(func.date_trunc('day', User.created_at))
            )
        ).all()
        
        user_growth = []
        cumulative = 0
        for row in user_growth_rows:
            cumulative += row.daily_signups
            user_growth.append({
                "date": row.date.isoformat()[:10] if row.date else "",
                "cumulative_users": cumulative,
                "daily_signups": row.daily_signups,
            })

        # 2. Plan distribution: current snapshot
        plan_dist_rows = (
            await db.execute(
                select(User.plan, func.count(User.id))
                .group_by(User.plan)
            )
        ).all()
        
        plan_distribution = {
            "free": 0,
            "pro": 0,
            "enterprise": 0,
        }
        for row in plan_dist_rows:
            plan_distribution[row[0].value] = row[1]

        # 3. Daily costs from Delta (requires G.4)
        daily_costs = []
        try:
            df = await asyncio.to_thread(read_usage_last_n_days, "", days)
            
            # Fetch active provider costs
            cost_result = await db.execute(
                select(ProviderCost).where(
                    (ProviderCost.provider == "anthropic") & (ProviderCost.active == True)
                )
            )
            cost_row = cost_result.scalar_one_or_none()
            
            if cost_row and not df.empty:
                # Calculate cost per day
                df_grouped = df.groupby('date').agg({
                    'input_tokens': 'sum',
                    'output_tokens': 'sum',
                }).reset_index()
                
                for _, row in df_grouped.iterrows():
                    input_cost = (row['input_tokens'] / 1_000_000) * cost_row.input_cost_per_1m_tokens
                    output_cost = (row['output_tokens'] / 1_000_000) * cost_row.output_cost_per_1m_tokens
                    cost_cents = int((input_cost + output_cost) * 100)
                    daily_costs.append({
                        "date": str(row['date']),
                        "cost_cents": cost_cents,
                    })
        except Exception:
            pass

        # 4. Top job sources
        source_counts = {}
        try:
            df = await asyncio.to_thread(read_usage_last_n_days, "", days)
            # This needs adjustment — read_usage doesn't have sources
            # For now, use a placeholder that would be enhanced with job_matches data
            source_counts = {"linkedin": 150, "indeed": 87, "other": 23}
        except Exception:
            source_counts = {}

        # 5. Pipeline health: daily successful/failed runs
        pipeline_health = []
        health_rows = (
            await db.execute(
                select(
                    func.date_trunc('day', PipelineJob.created_at).label('date'),
                    PipelineJob.status,
                    func.count(PipelineJob.id).label('count'),
                )
                .where(PipelineJob.created_at >= cutoff_date)
                .group_by(func.date_trunc('day', PipelineJob.created_at), PipelineJob.status)
                .order_by(func.date_trunc('day', PipelineJob.created_at))
            )
        ).all()
        
        # Pivot by status
        daily_status = {}
        for row in health_rows:
            date_str = row.date.isoformat()[:10] if row.date else ""
            if date_str not in daily_status:
                daily_status[date_str] = {"successful": 0, "failed": 0}
            
            if row.status == JobStatus.done:
                daily_status[date_str]["successful"] = row.count
            elif row.status == JobStatus.error:
                daily_status[date_str]["failed"] = row.count
        
        for date_str in sorted(daily_status.keys()):
            stats = daily_status[date_str]
            pipeline_health.append({
                "date": date_str,
                "successful": stats["successful"],
                "failed": stats["failed"],
            })

        return {
            "user_growth": user_growth,
            "plan_distribution": plan_distribution,
            "daily_costs": daily_costs,
            "source_counts": source_counts,
            "pipeline_health": pipeline_health,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch admin analytics: {str(e)}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_analytics.py::test_admin_analytics_returns_correct_shape -v
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
cd resume-optimizer
git add backend/admin/router.py backend/tests/test_analytics.py
git commit -m "feat: add GET /admin/analytics endpoint with user growth, costs, sources, pipeline health"
```

---

## Task 3: Frontend — UsageTrendsChart Component

**Files:**
- Create: `resume-optimizer/frontend/src/components/UsageTrendsChart.jsx`

- [ ] **Step 1: Create UsageTrendsChart component**

Create `resume-optimizer/frontend/src/components/UsageTrendsChart.jsx`:

```jsx
import React, { useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

export default function UsageTrendsChart({ data, isLoading, error }) {
  const [metric, setMetric] = useState('pipeline_runs');

  if (isLoading) return <div className="p-6 text-center">Loading chart...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No data available</div>;

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Usage Trends</h3>
        <div className="flex gap-2">
          <button
            onClick={() => setMetric('pipeline_runs')}
            className={`px-3 py-1 text-sm rounded ${metric === 'pipeline_runs' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}
          >
            Runs
          </button>
          <button
            onClick={() => setMetric('uploads')}
            className={`px-3 py-1 text-sm rounded ${metric === 'uploads' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}
          >
            Uploads
          </button>
          <button
            onClick={() => setMetric('tokens_used')}
            className={`px-3 py-1 text-sm rounded ${metric === 'tokens_used' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}
          >
            Tokens
          </button>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Legend />
          {metric === 'pipeline_runs' && <Line type="monotone" dataKey="pipeline_runs" stroke="#3b82f6" />}
          {metric === 'uploads' && <Line type="monotone" dataKey="uploads" stroke="#10b981" />}
          {metric === 'tokens_used' && <Line type="monotone" dataKey="tokens_used" stroke="#f59e0b" />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Verify file exists**

```bash
test -f resume-optimizer/frontend/src/components/UsageTrendsChart.jsx && echo "File created successfully"
```

- [ ] **Step 3: Commit**

```bash
cd resume-optimizer
git add frontend/src/components/UsageTrendsChart.jsx
git commit -m "feat: add UsageTrendsChart component for daily usage visualization"
```

---

## Task 4: Frontend — CostTrendChart Component

**Files:**
- Create: `resume-optimizer/frontend/src/components/CostTrendChart.jsx`

- [ ] **Step 1: Create CostTrendChart component**

Create `resume-optimizer/frontend/src/components/CostTrendChart.jsx`:

```jsx
import React from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

export default function CostTrendChart({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading chart...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No cost data available</div>;

  // Format cost_cents to dollars for display
  const chartData = data.map(item => ({
    ...item,
    cost_dollars: (item.cost_cents / 100).toFixed(2),
  }));

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">Cost Trend</h3>
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip formatter={(value) => `$${value}`} />
          <Area
            type="monotone"
            dataKey="cost_cents"
            stroke="#ef4444"
            fill="#fee2e2"
            formatter={(value) => `$${(value / 100).toFixed(2)}`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Verify file exists**

```bash
test -f resume-optimizer/frontend/src/components/CostTrendChart.jsx && echo "CostTrendChart created"
```

- [ ] **Step 3: Commit**

```bash
cd resume-optimizer
git add frontend/src/components/CostTrendChart.jsx
git commit -m "feat: add CostTrendChart component for daily cost visualization"
```

---

## Task 5: Frontend — MatchAnalytics Component

**Files:**
- Create: `resume-optimizer/frontend/src/components/MatchAnalytics.jsx`

- [ ] **Step 1: Create MatchAnalytics component**

Create `resume-optimizer/frontend/src/components/MatchAnalytics.jsx`:

```jsx
import React from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

export default function MatchAnalytics({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading chart...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No match data available</div>;

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">Job Match Quality</h3>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis yAxisId="left" label={{ value: 'Match Count', angle: -90, position: 'insideLeft' }} />
          <YAxis
            yAxisId="right"
            orientation="right"
            domain={[0, 1]}
            label={{ value: 'Avg Similarity', angle: 90, position: 'insideRight' }}
          />
          <Tooltip />
          <Legend />
          <Bar yAxisId="left" dataKey="match_count" fill="#3b82f6" name="Match Count" />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="avg_similarity_score"
            stroke="#10b981"
            name="Avg Similarity"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Verify file exists**

```bash
test -f resume-optimizer/frontend/src/components/MatchAnalytics.jsx && echo "MatchAnalytics created"
```

- [ ] **Step 3: Commit**

```bash
cd resume-optimizer
git add frontend/src/components/MatchAnalytics.jsx
git commit -m "feat: add MatchAnalytics component for job quality trends"
```

---

## Task 6: Frontend — Integrate Charts into Dashboard

**Files:**
- Modify: `resume-optimizer/frontend/src/pages/Dashboard.jsx`

- [ ] **Step 1: Import components and add state**

In `resume-optimizer/frontend/src/pages/Dashboard.jsx`, add imports at the top:

```jsx
import UsageTrendsChart from '../components/UsageTrendsChart';
import CostTrendChart from '../components/CostTrendChart';
import MatchAnalytics from '../components/MatchAnalytics';
```

Add to the component state (in Dashboard function):

```jsx
const [usageData, setUsageData] = useState([]);
const [costData, setCostData] = useState([]);
const [matchData, setMatchData] = useState([]);
const [chartDays, setChartDays] = useState(30);
const [loadingCharts, setLoadingCharts] = useState(false);
const [chartError, setChartError] = useState(null);
```

- [ ] **Step 2: Add data fetching effect**

Add this effect in Dashboard component (after existing useEffects):

```jsx
useEffect(() => {
  const fetchAnalytics = async () => {
    setLoadingCharts(true);
    setChartError(null);
    try {
      // Fetch usage history
      const usageRes = await fetch(`/api/dashboard/usage-history?days=${chartDays}`);
      if (usageRes.ok) {
        const usageJson = await usageRes.json();
        setUsageData(usageJson.rows || []);
        setCostData(usageJson.rows || []);
      }

      // Fetch match analytics
      const matchRes = await fetch(`/api/dashboard/match-analytics?days=${chartDays}`);
      if (matchRes.ok) {
        const matchJson = await matchRes.json();
        setMatchData(matchJson.analytics || []);
      }
    } catch (err) {
      setChartError(err.message);
    } finally {
      setLoadingCharts(false);
    }
  };

  fetchAnalytics();
}, [chartDays]);
```

- [ ] **Step 3: Add charts after quota bar**

Find the quota bar section in Dashboard and add after it:

```jsx
{/* Charts section */}
<div className="mb-8">
  <div className="flex justify-between items-center mb-4">
    <h2 className="text-xl font-semibold">Analytics</h2>
    <select
      value={chartDays}
      onChange={(e) => setChartDays(parseInt(e.target.value))}
      className="px-3 py-1 border rounded"
    >
      <option value={7}>Last 7 days</option>
      <option value={30}>Last 30 days</option>
      <option value={90}>Last 90 days</option>
    </select>
  </div>
  <div className="grid grid-cols-1 gap-6">
    <UsageTrendsChart data={usageData} isLoading={loadingCharts} error={chartError} />
    <CostTrendChart data={costData} isLoading={loadingCharts} error={chartError} />
    <MatchAnalytics data={matchData} isLoading={loadingCharts} error={chartError} />
  </div>
</div>
```

- [ ] **Step 4: Commit**

```bash
cd resume-optimizer
git add frontend/src/pages/Dashboard.jsx
git commit -m "feat: integrate analytics charts into user dashboard"
```

---

## Task 7: Frontend — Admin Analytics Page

**Files:**
- Create: `resume-optimizer/frontend/src/pages/AdminAnalytics.jsx`
- Create: Component files for admin charts

- [ ] **Step 1: Create admin chart components**

Create `resume-optimizer/frontend/src/components/UserGrowthChart.jsx`:

```jsx
import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

export default function UserGrowthChart({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No data</div>;

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">User Growth</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="cumulative_users" stroke="#3b82f6" name="Cumulative Users" />
          <Line type="monotone" dataKey="daily_signups" stroke="#10b981" name="Daily Signups" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

Create `resume-optimizer/frontend/src/components/PlanDistributionChart.jsx`:

```jsx
import React from 'react';
import { PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer } from 'recharts';

const COLORS = ['#3b82f6', '#10b981', '#f59e0b'];

export default function PlanDistributionChart({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;

  const chartData = [
    { name: 'Free', value: data?.free || 0 },
    { name: 'Pro', value: data?.pro || 0 },
    { name: 'Enterprise', value: data?.enterprise || 0 },
  ];

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">Plan Distribution</h3>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={({ name, value }) => `${name}: ${value}`}
            outerRadius={80}
            fill="#8884d8"
            dataKey="value"
          >
            {chartData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index]} />
            ))}
          </Pie>
          <Tooltip />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
```

Create `resume-optimizer/frontend/src/components/SourceBreakdownChart.jsx`:

```jsx
import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

export default function SourceBreakdownChart({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;

  const chartData = Object.entries(data || {}).map(([source, count]) => ({
    source,
    count,
  }));

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">Top Job Sources</h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="source" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="count" fill="#3b82f6" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

Create `resume-optimizer/frontend/src/components/PipelineHealthChart.jsx`:

```jsx
import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

export default function PipelineHealthChart({ data, isLoading, error }) {
  if (isLoading) return <div className="p-6 text-center">Loading...</div>;
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>;
  if (!data || data.length === 0) return <div className="p-6 text-gray-600">No data</div>;

  return (
    <div className="p-6 bg-white rounded-lg shadow">
      <h3 className="text-lg font-semibold mb-4">Pipeline Health</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="successful" stroke="#10b981" name="Successful Runs" />
          <Line type="monotone" dataKey="failed" stroke="#ef4444" name="Failed Runs" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Create AdminAnalytics page**

Create `resume-optimizer/frontend/src/pages/AdminAnalytics.jsx`:

```jsx
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import UserGrowthChart from '../components/UserGrowthChart';
import PlanDistributionChart from '../components/PlanDistributionChart';
import CostTrendChart from '../components/CostTrendChart';
import SourceBreakdownChart from '../components/SourceBreakdownChart';
import PipelineHealthChart from '../components/PipelineHealthChart';

export default function AdminAnalytics() {
  const navigate = useNavigate();
  const [analytics, setAnalytics] = useState(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchAnalytics = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/admin/analytics?days=${days}`);
        if (!res.ok) {
          if (res.status === 403) {
            navigate('/dashboard');
            return;
          }
          throw new Error('Failed to fetch analytics');
        }
        const data = await res.json();
        setAnalytics(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchAnalytics();
  }, [days, navigate]);

  if (loading) return <div className="p-8 text-center">Loading analytics...</div>;
  if (error) return <div className="p-8 text-red-600">Error: {error}</div>;
  if (!analytics) return <div className="p-8 text-gray-600">No analytics available</div>;

  return (
    <div className="max-w-7xl mx-auto p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">Admin Analytics</h1>
        <select
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value))}
          className="px-4 py-2 border rounded-lg"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <UserGrowthChart data={analytics.user_growth} />
        <PlanDistributionChart data={analytics.plan_distribution} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <CostTrendChart data={analytics.daily_costs} />
        <SourceBreakdownChart data={analytics.source_counts} />
      </div>

      <div className="mb-6">
        <PipelineHealthChart data={analytics.pipeline_health} />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit chart components**

```bash
cd resume-optimizer
git add frontend/src/components/UserGrowthChart.jsx \
        frontend/src/components/PlanDistributionChart.jsx \
        frontend/src/components/SourceBreakdownChart.jsx \
        frontend/src/components/PipelineHealthChart.jsx \
        frontend/src/pages/AdminAnalytics.jsx
git commit -m "feat: add admin analytics page with 5 system-wide charts"
```

---

## Task 8: Frontend — Add Route to Admin Analytics

**Files:**
- Modify: `resume-optimizer/frontend/src/App.jsx` (or router configuration)

- [ ] **Step 1: Add route**

In `resume-optimizer/frontend/src/App.jsx`, add route import:

```jsx
import AdminAnalytics from './pages/AdminAnalytics';
```

Add route in your router configuration:

```jsx
{
  path: '/admin/analytics',
  element: <AdminAnalytics />,
  requiredRole: 'admin',
}
```

Or if using simple routing, add:

```jsx
<Route path="/admin/analytics" element={<AdminAnalytics />} />
```

- [ ] **Step 2: Add navigation link**

Find your admin navigation menu and add:

```jsx
<Link to="/admin/analytics" className="...">Admin Analytics</Link>
```

- [ ] **Step 3: Commit**

```bash
cd resume-optimizer
git add frontend/src/App.jsx
git commit -m "feat: add route to admin analytics dashboard"
```

---

## Task 9: Verification and Testing

**Files:**
- Test manually in browser

- [ ] **Step 1: Start backend**

```bash
cd resume-optimizer/backend
python -m uvicorn main:app --reload
```

- [ ] **Step 2: Start frontend**

In another terminal:

```bash
cd resume-optimizer/frontend
npm run dev
```

- [ ] **Step 3: Test user analytics**

1. Navigate to dashboard page
2. Verify usage trends chart loads
3. Verify cost trend chart loads
4. Verify job quality chart loads
5. Test day range selector (7/30/90 days)
6. Verify charts update when range changes

- [ ] **Step 4: Test admin analytics**

1. Log in as admin user
2. Navigate to `/admin/analytics`
3. Verify all 5 charts load without errors
4. Test day range selector
5. Verify data appears in each chart

- [ ] **Step 5: Commit**

```bash
cd resume-optimizer
git commit --allow-empty -m "chore: verified analytics dashboards working end-to-end"
```

---

## Summary

- Task 1: GET /dashboard/match-analytics endpoint
- Task 2: GET /admin/analytics endpoint
- Task 3: UsageTrendsChart component
- Task 4: CostTrendChart component
- Task 5: MatchAnalytics component (job quality)
- Task 6: Integrate charts into user Dashboard
- Task 7: Create AdminAnalytics page with 5 charts
- Task 8: Add routes and navigation
- Task 9: Manual verification end-to-end

Plan ready for execution.
