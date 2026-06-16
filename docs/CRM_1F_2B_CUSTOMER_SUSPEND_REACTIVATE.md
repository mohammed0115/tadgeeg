# CRM-1F-2B — Customer Suspend / Reactivate (MVP via `Organization.is_active`)

## Summary
Adds CRM operations to **suspend** and **reactivate** a customer, plus the
enforcement that makes it actually take effect. Suspend sets
`Organization.is_active = False`; a small addition to
`SubscriptionRequiredMiddleware` blocks normal org users of an inactive
organization. No new subscription status, no migration, no payment/quota changes.

## Why the MVP uses `Organization.is_active`
The CRM-1F-2A audit found `Organization.is_active` was **inert** (read nowhere for
access control) and that `SubscriptionStatus` has no `suspended` value. The Hybrid
MVP reuses the existing `is_active` flag as the suspend lever and adds the missing
enforcement to the existing subscription middleware — avoiding a migration while
leaving the subscription record untouched (so reactivation is trivial and billing
state is never perturbed).

## Middleware enforcement
`apps/billing/middleware.py` → `SubscriptionRequiredMiddleware._maybe_block`: after
resolving the user's org, if `not org.is_active` the request is blocked **before**
the subscription check:
- **API** (`/api/...`): `403` JSON `{code: "account_suspended", ...}`.
- **UI**: redirect to `/billing/plans/` (reused existing destination; the message
  is intentionally generic — no dedicated suspended page yet).

This sits inside the path already guarded by `_needs_subscription_check`, so it
**does not** affect: anonymous users, staff/superusers (bypassed), or whitelisted
paths (login/logout/billing/health/admin/static). A suspended org's users can
still log out and reach billing/auth pages.

## Service design (`apps/platform_admin/services/crm_operations.py`)
```python
suspend_customer(*, actor, organization, reason, request=None)
reactivate_customer(*, actor, organization, reason, request=None)
```
Both share `_set_customer_active`, which: enforces
`can_manage_financial_crm_data(actor)`; requires a non-empty `reason`; runs in
`transaction.atomic` with `select_for_update` on the Organization row; flips ONLY
`is_active`; **rejects** a no-op (double-suspend / double-reactivate) with
`ValidationError`; and writes AuditLog + CustomerActivity. They touch no
subscription/quota/payment fields and create no PaymentTransaction.

## Permissions
`can_manage_financial_crm_data` = **Owner + Finance**. Support, Readonly, Platform
Admin (excluded by the helper), staff-without-group, customer users, and anonymous
are denied (view returns 403; anonymous → login redirect). Permission helpers were
**not** modified.

## Superadmin rule
- `is_authenticated && is_staff && is_superuser` → **allowed** (implicit Platform
  Owner), even with zero CRM groups — proven at both service and view level.
- `is_superuser && !is_staff` → **denied** (service raises PermissionDenied; view
  returns 403). Consistent with extend (CRM-1F-1B).

## UI behavior
Customer Profile → **Overview** tab → "Account Status" section, rendered only when
`can_manage_financial`:
- org active → **Suspend Customer** (red button) + required reason + warning
  *"This will suspend customer access and will be audited."*
- org inactive → **Reactivate Customer** (green button) + required reason + warning
  *"This will restore customer access and will be audited."*
CSRF-protected POST; no GET mutation; no link-based action. Support/Readonly see no
buttons. No change-plan / manual-payment / adjust-quota controls.

## Audit / activity behavior
`AuditLog` via `log_crm_action`: `details["action_type"]` ∈
{`customer_suspended`, `customer_reactivated`}, with `reason` and
`old_value`/`new_value` = `{"is_active": ...}`, `resource_type="Organization"`.
`CustomerActivity.activity_type` = literal `"customer_suspended"` /
`"customer_reactivated"` (no enum member — documented technical debt, same as
`ticket_assigned` / `subscription_extended`). The `AuditLog.Action` enum is not
extended.

## What changed
`Organization.is_active` toggled via two audited CRM services; a guard added to the
subscription middleware to enforce it; a reason-only form, two POST routes, two
views, and the Overview-tab UI.

## What did NOT change
No models, no migrations, no new subscription status, no `OrganizationSubscription`
writes, no payments, no manual payment, no change plan, no adjust quota, no email,
no permission-helper edits, no customer-facing portal.

## Tests run
`apps/platform_admin/tests/test_crm_suspend_reactivate.py` (38 tests): middleware
(inactive org blocked UI 302 / API 403; active+sub passes; staff/superuser bypass;
whitelist intact), service (suspend/reactivate + audit/activity; reason required;
double-op rejected; subscription/quota untouched; no PaymentTransaction; role
matrix; superuser±staff), view (302 + write; 405 on GET; invalid form no write;
anonymous/non-staff/Support/Readonly/Admin 403; superuser±staff; 404), UI smoke
(buttons gated by role + active state; no other financial action routes).

```
python manage.py check                              # 0 issues
python manage.py makemigrations --check --dry-run   # No changes detected
python -m pytest apps/platform_admin/tests/test_crm_suspend_reactivate.py --no-cov -q   # 38 passed
python -m pytest apps/billing/tests/ apps/platform_admin/tests/ --no-cov -q   # regression
```

## Risks / Notes
- A suspended org's UI users are redirected to `/billing/plans/` with a generic
  message — a dedicated "account suspended" page is a later improvement.
- The suspend lever is the org flag, not the subscription, so an audit reviewer
  sees the org was suspended (not the subscription). For subscription-level
  fidelity, see the long-term recommendation.
- `customer_suspended` / `customer_reactivated` activity types are literals pending
  a future enum migration.

## Long-term `suspended` status recommendation
Add a `SUSPENDED` value to `SubscriptionStatus` (migration), kept out of
`USABLE_STATUSES`. The existing middleware + `is_usable` + quota would then enforce
it automatically with no new code, and the audit trail would reflect a suspended
*subscription*. Pair it with official `billing.suspend_subscription` /
`reactivate_subscription` services. Defer until subscription-level suspension is
actually required.

## Recommended next step
**CRM-1F-3** — Manual payment MVP (add/confirm/reject), which needs a
provider/pricing decision and a migration (`provider="manual"`), and must route
through the official payment services with the same audit discipline.
