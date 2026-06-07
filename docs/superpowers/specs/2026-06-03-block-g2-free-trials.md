# Block G.2 — Free Trials: Design Spec
**Date:** 2026-06-03
**Branch:** backend_design
**Status:** Approved

## Overview

Every new user automatically receives a 7-day Pro trial on registration. During the trial their effective plan is Pro (20 uploads/day, 10 stored resumes, job scraping enabled). After 7 days the free plan limits apply. Trial expiry is enforced lazily — checked at request time in `check_plan_limit`, no background job needed. The user's `plan` field stays `"free"` in the DB; trial status is a separate `trial_expires_at` column.

## Out of Scope

- Admin-granted trial extensions
- Trial for existing (pre-migration) users — they get `trial_expires_at = NULL` and no trial
- Stripe integration / billing
- G.3 promo codes, G.4 cost tracking, G.5 analytics

---

## Section 1: Data Layer

### Migration `0003_add_trial_expires_at`

```sql
ALTER TABLE users ADD COLUMN trial_expires_at TIMESTAMP;
```

Single nullable column. No server default — `NULL` means no trial (existing users and future users whose trial has expired are NULL).

### `db/models.py`

Add to `User` class:

```python
trial_expires_at = Column(DateTime, nullable=True)
```

### `config.py`

Add after `RATE_LIMIT_AUTH`:

```python
# ── Free trial ────────────────────────────────────────────────────────────────
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "7"))
```

### Registration (`auth/router.py`)

When creating a new `User`, set the trial expiry:

```python
from config import TRIAL_DAYS

user = User(
    email=body.email,
    password_hash=pwd_context.hash(body.password),
    full_name=body.full_name,
    trial_expires_at=datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
)
```

---

## Section 2: Plan Limit Check

### `auth/dependencies.py` — `check_plan_limit`

Before fetching `PlanLimit`, compute the effective plan:

```python
from datetime import datetime, timezone
from config import ..., TRIAL_DAYS   # already imported

async def check_plan_limit(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    # trial_expires_at is stored as naive UTC (SQLAlchemy DateTime column strips tzinfo).
    # Use datetime.utcnow() for a naive-vs-naive comparison — avoids TypeError.
    trial_active = (
        user.trial_expires_at is not None
        and user.trial_expires_at > datetime.utcnow()
    )
    effective_plan = "pro" if trial_active else user.plan.value

    result = await db.execute(select(PlanLimit).where(PlanLimit.plan == effective_plan))
    limits = result.scalar_one_or_none()
    ...
```

`trial_expires_at` is stored as naive UTC by the SQLAlchemy `DateTime` column. `datetime.utcnow()` is also naive UTC. Mixing with a timezone-aware datetime (e.g. `datetime.now(timezone.utc)`) would raise `TypeError` in Python — hence the `utcnow()` choice here.

No change to the rest of `check_plan_limit` (Delta Lake usage read, 429 logic).

---

## Section 3: Auth Responses

### `auth/router.py` — `_user_dict()`

Add one field:

```python
"trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
```

`/auth/login`, `/auth/register`, `/auth/me` all call `_user_dict()` — all three return `trial_expires_at` automatically.

### `admin/router.py` — `_user_dict()` and `_user_detail()`

Same addition:

```python
"trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
```

### `admin/schemas.py`

Add to both `UserListItem` and `UserDetail`:

```python
trial_expires_at: Optional[str] = None
```

---

## Section 4: Frontend — `TrialBanner`

### New component: `frontend/src/components/TrialBanner.jsx`

Reads `user` from `authStore`. Computes days remaining. Returns `null` when trial is absent or expired.

```jsx
import useAuthStore from '../store/authStore';

export default function TrialBanner() {
  const { user } = useAuthStore();
  if (!user?.trial_expires_at) return null;

  const expires = new Date(user.trial_expires_at);
  const daysLeft = Math.ceil((expires - Date.now()) / 86_400_000);
  if (daysLeft <= 0) return null;

  return (
    <div className="mx-3 mb-2 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2 text-xs text-amber-400">
      <span className="font-semibold">Pro Trial</span>
      {' — '}{daysLeft} day{daysLeft !== 1 ? 's' : ''} left
    </div>
  );
}
```

### `frontend/src/components/layout/Sidebar.jsx`

Import and mount `TrialBanner` just above the user info row at the bottom of the sidebar:

```jsx
import TrialBanner from '../TrialBanner';

// Inside the bottom <div>:
<TrialBanner />
{user?.plan === 'free' && (
  <Link to="/dashboard/settings" ...>Upgrade to Pro</Link>
)}
```

`TrialBanner` renders nothing when trial is inactive, so the "Upgrade to Pro" button shows normally after expiry.

---

## Section 5: Tests

### `backend/tests/test_trials.py`

Tests for the trial logic in `check_plan_limit`:

- **`test_new_user_gets_trial`** — register a user, verify `trial_expires_at` is set ~7 days from now
- **`test_active_trial_gives_pro_limits`** — user with `plan=free` and `trial_expires_at = now + 1 day` → `check_plan_limit` returns pro limits (daily_uploads=20)
- **`test_expired_trial_gives_free_limits`** — user with `plan=free` and `trial_expires_at = now - 1 day` → `check_plan_limit` returns free limits (daily_uploads=2)
- **`test_no_trial_gives_free_limits`** — user with `plan=free` and `trial_expires_at = None` → free limits

---

## Files Changed

| Action | Path |
|---|---|
| Create | `resume-optimizer/backend/alembic/versions/0003_add_trial_expires_at.py` |
| Modify | `resume-optimizer/backend/db/models.py` |
| Modify | `resume-optimizer/backend/config.py` |
| Modify | `resume-optimizer/backend/auth/router.py` |
| Modify | `resume-optimizer/backend/auth/dependencies.py` |
| Modify | `resume-optimizer/backend/admin/schemas.py` |
| Modify | `resume-optimizer/backend/admin/router.py` |
| Create | `resume-optimizer/backend/tests/test_trials.py` |
| Create | `resume-optimizer/frontend/src/components/TrialBanner.jsx` |
| Modify | `resume-optimizer/frontend/src/components/layout/Sidebar.jsx` |

---

## Security Notes

- Trial is set server-side at registration. Client cannot pass a `trial_expires_at` value — the registration endpoint ignores it.
- `effective_plan` is computed on every request inside `check_plan_limit` — no caching means an expired trial is blocked immediately on the next request.
- Admin cannot grant or extend trials via API (out of scope). Direct DB access required if needed.
