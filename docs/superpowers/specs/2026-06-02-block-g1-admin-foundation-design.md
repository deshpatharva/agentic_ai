# Block G.1 — Admin Foundation: Design Spec
**Date:** 2026-06-02
**Branch:** backend_design
**Status:** Approved

## Overview

Block G is the admin portal for the resume optimizer. Sub-project G.1 is the foundation everything else builds on: admin authentication, user management, and a basic stats dashboard. Later sub-projects (G.2 free trials, G.3 promo codes, G.4 cost tracking, G.5 analytics) all depend on this foundation.

## Scope

- `is_admin` column on users + Alembic migration
- Bootstrap endpoint to promote the first admin
- Admin API module (`/admin/*`) with `get_admin_user` dependency
- Five backend endpoints: stats, user list, user detail, user update, bootstrap
- Frontend admin section: protected route, layout, dashboard, user list, user detail

## Out of Scope (later G sub-projects)

- Free trial grants (G.2)
- Promo / discount codes (G.3)
- Cost tracking (G.4)
- Usage analytics charts (G.5)

---

## Section 1: Data Layer

### Migration `0002_add_is_admin`

Single column added to `users`:

```sql
ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE;
```

No data migration needed — all existing users default to `False`.

### `db/models.py`

Add to the `User` class:

```python
is_admin = Column(Boolean, default=False, nullable=False)
```

### Auth response

`/auth/me` already returns the full user dict via `_user_dict()`. Add `is_admin` to the dict so the frontend can read it from `authStore` without a separate call:

```python
"is_admin": user.is_admin,
```

---

## Section 2: Backend — `backend/admin/` Module

### File structure

```
backend/admin/
  __init__.py          # empty
  dependencies.py      # get_admin_user dependency
  router.py            # all /admin/* endpoints
  schemas.py           # Pydantic request/response models
```

### `admin/dependencies.py`

```python
from fastapi import Depends, HTTPException
from db.models import User
from auth.dependencies import get_current_user

async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user
```

Every admin endpoint depends on `get_admin_user`. A non-admin authenticated user gets 403. An unauthenticated request gets 401 (from the inner `get_current_user`).

### `admin/schemas.py`

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    plan: str
    is_active: bool
    is_admin: bool
    created_at: str
    resume_count: int

class UserDetail(UserListItem):
    runs_today: int
    total_resumes: int
    last_active: Optional[str]   # ISO datetime of latest resume, or None

class UserUpdate(BaseModel):
    plan: Optional[str] = None        # "free" | "pro" | "enterprise"
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None   # True only — backend rejects False to prevent lockout

class AdminStats(BaseModel):
    total_users: int
    active_users: int          # is_active=True
    pipeline_runs_today: int
    total_resumes: int
```

### `admin/router.py` — Endpoints

#### `POST /admin/bootstrap`

Promotes a user to admin. Only works when `COUNT(*) WHERE is_admin=TRUE == 0`. Body: `{"email": "you@example.com"}`. Returns the updated user dict. Returns 403 if any admin already exists. No auth required on this endpoint (chicken-and-egg: you can't be admin yet to call it).

Security: the endpoint self-destructs after first use by returning 403 forever once any admin exists.

#### `GET /admin/stats`

Returns `AdminStats`. Reads counts directly from PostgreSQL:
- `total_users` — `COUNT(*) FROM users`
- `active_users` — `COUNT(*) FROM users WHERE is_active=TRUE`
- `total_resumes` — `COUNT(*) FROM resumes`
- `pipeline_runs_today` — `COUNT(*) FROM pipeline_jobs WHERE created_at >= today AND status='done'`

No Delta Lake call. Stays fast.

#### `GET /admin/users`

Paginated user list. Query params: `page` (default 1), `per_page` (default 20, max 100), `search` (optional — filters where `lower(email) LIKE lower(search) || '%'` for PostgreSQL/SQLite portability).

Returns `{total, page, per_page, results: [UserListItem]}`.

`resume_count` is a subquery count per user — included in the list response to avoid N+1 on the detail page.

#### `GET /admin/users/{user_id}`

Returns `UserDetail`. In addition to list fields:
- `runs_today` — pipeline_jobs for this user created today with status=done
- `total_resumes` — resume count for this user
- `last_active` — `MAX(created_at)` from resumes for this user

#### `PATCH /admin/users/{user_id}`

Accepts `UserUpdate` (partial — all fields optional). Updates `plan`, `is_active`, and/or `is_admin`. Returns updated `UserDetail`.

Rules enforced server-side:
- `plan` must be one of `"free"`, `"pro"`, `"enterprise"`.
- `is_active=False` is rejected if the target user is an admin (prevents lockout).
- `is_admin=False` is rejected — demotion via API is blocked. Demotion requires direct DB access to prevent accidental self-lockout.
- Calling admin cannot suspend themselves.

### Register router in `main.py`

```python
from admin.router import router as admin_router
app.include_router(admin_router)
```

---

## Section 3: Frontend

### Files

```
src/components/AdminRoute.jsx
src/pages/admin/AdminLayout.jsx
src/pages/admin/AdminDashboard.jsx
src/pages/admin/UserList.jsx
src/pages/admin/UserDetail.jsx
```

### `AdminRoute.jsx`

Reads `user` from `authStore`. If not authenticated → redirect to `/login`. If authenticated but `!user.is_admin` → redirect to `/`. Otherwise renders children.

```jsx
export default function AdminRoute({ children }) {
  const { user, token } = useAuthStore();
  if (!token) return <Navigate to="/login" replace />;
  if (user && !user.is_admin) return <Navigate to="/" replace />;
  return children;
}
```

### `AdminLayout.jsx`

Wraps all admin pages. Distinct dark-header styling to make admin context visually clear. Contains a minimal sidebar:
- Dashboard (`/admin`)
- Users (`/admin/users`)

Renders `<Outlet />` for child routes.

### `AdminDashboard.jsx`

Four stat cards calling `GET /admin/stats`:
- Total Users
- Active Users
- Pipeline Runs Today
- Total Resumes

Simple grid layout. Shows loading skeletons while fetching.

### `UserList.jsx`

Calls `GET /admin/users?page=N&search=Q`.

Table columns: Email, Full Name, Plan (badge coloured by plan tier), Status (Active / Suspended chip), Joined date, Resumes count.

Search input debounced 300ms — updates `search` query param.

Pagination controls at the bottom.

Clicking a row navigates to `/admin/users/:id`.

### `UserDetail.jsx`

Calls `GET /admin/users/:id`.

Shows:
- Profile card: email, full name, joined, `is_admin` badge if true
- Stats row: resumes stored, pipeline runs today, last active
- Plan selector dropdown (free / pro / enterprise) → calls `PATCH /admin/users/:id` on change
- Suspend / Reactivate toggle button → calls `PATCH /admin/users/:id` on click
- Back link to `/admin/users`

Optimistic UI: updates local state immediately, shows error toast and reverts on failure.

Does not show Suspend toggle for `is_admin=true` users (safety guard mirroring the backend).

### Route wiring in `main.jsx`

```jsx
import { Route } from 'react-router-dom';
import AdminRoute from './components/AdminRoute';
import AdminLayout from './pages/admin/AdminLayout';
import AdminDashboard from './pages/admin/AdminDashboard';
import UserList from './pages/admin/UserList';
import UserDetail from './pages/admin/UserDetail';

// Inside the router:
<Route path="/admin" element={<AdminRoute><AdminLayout /></AdminRoute>}>
  <Route index element={<AdminDashboard />} />
  <Route path="users" element={<UserList />} />
  <Route path="users/:id" element={<UserDetail />} />
</Route>
```

### `authStore` — expose `is_admin`

`is_admin` is returned by `/auth/me` and `/auth/login` once the column exists. The existing `authStore` stores the full user object from the API response — no store changes needed, just ensure the API returns `is_admin` (covered in Section 1).

---

## Files Changed

| Action | Path |
|---|---|
| Create | `resume-optimizer/backend/alembic/versions/0002_add_is_admin.py` |
| Modify | `resume-optimizer/backend/db/models.py` |
| Modify | `resume-optimizer/backend/auth/router.py` (`_user_dict` adds `is_admin`) |
| Create | `resume-optimizer/backend/admin/__init__.py` |
| Create | `resume-optimizer/backend/admin/dependencies.py` |
| Create | `resume-optimizer/backend/admin/schemas.py` |
| Create | `resume-optimizer/backend/admin/router.py` |
| Modify | `resume-optimizer/backend/main.py` (register admin router) |
| Create | `resume-optimizer/backend/tests/test_admin.py` |
| Create | `resume-optimizer/frontend/src/components/AdminRoute.jsx` |
| Create | `resume-optimizer/frontend/src/pages/admin/AdminLayout.jsx` |
| Create | `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx` |
| Create | `resume-optimizer/frontend/src/pages/admin/UserList.jsx` |
| Create | `resume-optimizer/frontend/src/pages/admin/UserDetail.jsx` |
| Modify | `resume-optimizer/frontend/src/main.jsx` (add admin routes) |

---

## Security Notes

- Every `/admin/*` endpoint (except `/admin/bootstrap`) depends on `get_admin_user`
- `/admin/bootstrap` is self-disabling: returns 403 once any admin exists
- `PATCH /admin/users/{id}` prevents suspending yourself or other admins (backend-enforced)
- `is_admin` can be set to `True` via `PATCH /admin/users/{id}` (promotes a user). Setting to `False` is rejected (demotion requires direct DB access to prevent accidental lockout).
- Admin routes are behind the same HTTPS-only App Service config as the rest of the API

## Bootstrap Flow (first-time setup)

1. Deploy with Block G.1
2. Call `POST /admin/bootstrap` with `{"email": "your@email.com"}` — this user must already exist
3. Log in as that user — you now see the Admin link in the nav
4. Promote additional admins via `PATCH /admin/users/{id}` with `{"is_admin": true}` from the admin UI UserDetail page
