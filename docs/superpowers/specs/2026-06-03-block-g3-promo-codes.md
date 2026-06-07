# Block G.3 — Promo Codes: Design Spec
**Date:** 2026-06-03
**Branch:** backend_design
**Status:** Approved

## Overview

Admins create flexible promo codes that users redeem for plan upgrades, trial extensions, or discounts. Each code has a type (upgrade/extension/discount), optional expiry date, and usage limit (e.g., "max 100 uses"). A user can redeem each code only once. On redemption, the code's effect is applied immediately: upgrade changes `user.plan` and clears the trial, extension adds days to `trial_expires_at`, discount is stored for Stripe integration (deferred).

## Out of Scope

- Stripe integration for discount codes (deferred to billing phase)
- Code templates or batch generation — admin creates individual codes
- Expiry date handling for discounts (e.g., "10% off for 3 months") — only code expiry date, not time-limited effects
- Analytics on promo effectiveness (covered in G.5)

---

## Section 1: Data Layer

### Migration `0004_promo_codes`

Creates two tables:

```sql
CREATE TABLE promo_codes (
    id UUID PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    type ENUM('plan_upgrade', 'trial_extension', 'discount') NOT NULL,
    target_plan VARCHAR(20),
    days_to_add INTEGER,
    discount_percent INTEGER,
    max_uses INTEGER NOT NULL,
    current_uses INTEGER DEFAULT 0 NOT NULL,
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    deactivated_at TIMESTAMP
);

CREATE TABLE user_promo_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    promo_code_id UUID NOT NULL REFERENCES promo_codes(id) ON DELETE CASCADE,
    redeemed_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE(user_id, promo_code_id)
);
```

### Models

**PromoCode:**
- `id` (UUID, primary key)
- `code` (String, unique, 50 chars max) — human-readable code like "SUMMER50"
- `type` (Enum: "plan_upgrade" | "trial_extension" | "discount")
- `target_plan` (String, nullable) — required if type is "plan_upgrade" (e.g., "pro")
- `days_to_add` (Integer, nullable) — required if type is "trial_extension"
- `discount_percent` (Integer, nullable) — 1–99, required if type is "discount"
- `max_uses` (Integer) — total redemptions allowed
- `current_uses` (Integer, default 0) — redemptions so far
- `expires_at` (DateTime, nullable) — NULL = no expiry
- `created_at` (DateTime)
- `deactivated_at` (DateTime, nullable) — when admin deactivated the code

**UserPromoRedemption:**
- `id` (auto-increment)
- `user_id` (UUID, FK → users)
- `promo_code_id` (UUID, FK → promo_codes)
- `redeemed_at` (DateTime)
- Unique constraint: (user_id, promo_code_id) — each user can redeem each code at most once

### Validation Rules

A code is **valid** if:
- `code` record exists in DB
- `deactivated_at` is NULL
- `expires_at` is NULL or `expires_at > now()`
- `current_uses < max_uses`
- User has not redeemed this code before (no row in `user_promo_redemptions`)

A code is **invalid** (400 response) if code text doesn't exist or is malformed.

A code is **exhausted or unavailable** (409 response) if any of the above conditions fail.

---

## Section 2: Redemption Logic

### Endpoint: `POST /user/redeem-promo-code`

Request body:
```json
{
  "code": "SUMMER50"
}
```

Response on success (200):
```json
{
  "message": "Pro plan activated!",
  "effect": "plan_upgrade",
  "target_plan": "pro",
  "user": { ...updated user object... }
}
```

Response on error:
- **400 Bad Request** — code doesn't exist or is malformed
- **409 Conflict** — code is expired, deactivated, exhausted, or already redeemed by this user (with detail explaining which)

### Redemption Process (TDD)

1. **Validate code syntax** — must be non-empty, alphanumeric + dash/underscore, max 50 chars
2. **Fetch code** — query PromoCode by code string
3. **Check validity**:
   - Code exists (else 400)
   - Not deactivated (else 409 "code deactivated")
   - Not expired (expires_at NULL or > now, else 409 "code expired")
   - Has remaining uses (current_uses < max_uses, else 409 "code exhausted")
   - User hasn't redeemed (query user_promo_redemptions, else 409 "already redeemed")
4. **Apply effect**:
   - **upgrade**: set `user.plan = code.target_plan`, set `user.trial_expires_at = NULL`
   - **extension**: add `code.days_to_add` to `user.trial_expires_at` (only if trial is active; if not, 400 "no active trial to extend")
   - **discount**: record in `user_active_discounts` table or metadata (implementation deferred to Stripe phase; for now, just increment counter)
5. **Record redemption**: insert row in UserPromoRedemption(user_id, promo_code_id)
6. **Increment counter**: `current_uses += 1`
7. **Commit** and return 200 with updated user object

---

## Section 3: Admin Endpoints

**Note:** Promo codes are immutable after creation (except for deactivation). There is no PATCH endpoint to edit type, target_plan, max_uses, etc. This prevents accidental campaign changes. If a code needs adjustment, admin must deactivate it and create a new one.

### `POST /admin/promo-codes` — Create Code

Request:
```json
{
  "code": "SUMMER50",
  "type": "discount",
  "discount_percent": 50,
  "max_uses": 100,
  "expires_at": "2026-12-31T23:59:59Z"
}
```

Response (201):
```json
{
  "id": "uuid",
  "code": "SUMMER50",
  "type": "discount",
  "discount_percent": 50,
  "target_plan": null,
  "days_to_add": null,
  "max_uses": 100,
  "current_uses": 0,
  "expires_at": "2026-12-31T23:59:59Z",
  "created_at": "2026-06-03T...",
  "deactivated_at": null
}
```

**Validation:**
- `code`: required, unique, alphanumeric + dash/underscore, 1–50 chars
- `type`: required, one of "plan_upgrade" | "trial_extension" | "discount"
- `target_plan`: required if type is "plan_upgrade"; must be "pro" or "enterprise"
- `days_to_add`: required if type is "trial_extension"; must be 1–365
- `discount_percent`: required if type is "discount"; must be 1–99
- `max_uses`: required, 1+
- `expires_at`: optional, must be in future if provided

### `GET /admin/promo-codes` — List Codes

Query params:
- `status=active|expired|deactivated` (default: all)
- `type=upgrade|extension|discount` (default: all)
- `limit=50` (default 50, max 500)
- `offset=0`

Response (200):
```json
{
  "total": 42,
  "codes": [
    {
      "id": "uuid",
      "code": "SUMMER50",
      "type": "discount",
      "max_uses": 100,
      "current_uses": 47,
      "expires_at": "2026-12-31T23:59:59Z",
      "created_at": "2026-06-03T...",
      "status": "active",
      "days_until_expiry": 212
    },
    ...
  ]
}
```

### `PATCH /admin/promo-codes/{code_id}` — Deactivate Code

Request body:
```json
{}
```

Sets `deactivated_at = now()`. Code becomes invalid immediately; any attempted redemptions fail with "code deactivated".

Response (200): updated code object with `deactivated_at` set.

### `GET /admin/promo-codes/{code_id}/stats` — Code Statistics

Response (200):
```json
{
  "code": "SUMMER50",
  "type": "discount",
  "discount_percent": 50,
  "max_uses": 100,
  "current_uses": 47,
  "remaining_uses": 53,
  "redeemed_by_plan": {
    "free": 30,
    "pro": 12,
    "enterprise": 5
  },
  "last_redeemed_at": "2026-06-02T14:32:15Z",
  "first_redeemed_at": "2026-05-28T08:00:00Z"
}
```

---

## Section 4: Frontend + Tests

### Frontend: Redeem Code Form

New section in `/dashboard/settings`:
- Input field label "Promo Code"
- Text input (placeholder "Enter code")
- "Redeem" button (disabled while loading)
- Success toast: "Pro plan activated!" / "Trial extended 7 days" / "Discount applied"
- Error toast: displays server error detail

Component is optional (doesn't render if user has enterprise plan).

### Tests (`backend/tests/test_promo_codes.py`)

TDD: write tests first, verify they fail, implement.

1. **`test_redeem_upgrade_code`** — User with free plan redeems "upgrade to pro" code → plan becomes pro, trial_expires_at clears
2. **`test_redeem_extension_code`** — User with active trial redeems "extend trial" code → trial_expires_at increases by days_to_add
3. **`test_extension_without_active_trial`** — User with no active trial redeems extension code → 400 "no active trial"
4. **`test_redeem_discount_code`** — User redeems discount code → counter incremented, discount recorded
5. **`test_code_exhausted`** — Code with max_uses=1, already redeemed once, user tries again → 409 "code exhausted"
6. **`test_code_expired`** — Code with expires_at in past → redemption attempt returns 409 "code expired"
7. **`test_code_already_redeemed`** — Same user redeems same code twice → second attempt returns 409 "already redeemed"
8. **`test_code_invalid`** — Redeem non-existent code → 400 "invalid code"
9. **`test_admin_create_code`** — Admin POSTs to /admin/promo-codes with valid params → code created
10. **`test_admin_list_codes`** — Admin GETs /admin/promo-codes → returns paginated list with correct status/type
11. **`test_admin_deactivate`** — Admin PATCHes code → deactivated_at set, redemption fails
12. **`test_admin_stats`** — Admin GETs stats → shows redeemed_by_plan breakdown and last_redeemed_at

---

## Files Changed

| Action | Path |
|---|---|
| Create | `resume-optimizer/backend/alembic/versions/0004_promo_codes.py` |
| Modify | `resume-optimizer/backend/db/models.py` |
| Modify | `resume-optimizer/backend/auth/router.py` |
| Modify | `resume-optimizer/backend/admin/schemas.py` |
| Modify | `resume-optimizer/backend/admin/router.py` |
| Create | `resume-optimizer/backend/tests/test_promo_codes.py` |
| Modify | `resume-optimizer/frontend/src/pages/Settings.jsx` |

---

## Security Notes

- Code string is case-sensitive (e.g., "SUMMER50" != "summer50") — admin responsibility
- No rate limiting on redemption attempts (could add per-IP limit later if needed)
- Deactivation is soft (sets timestamp) — allows audit trail; hard deletion not supported
- User can see only codes they've redeemed (via /dashboard/summary or user object); can't list all codes
- Admin can list all codes and see redemption patterns
