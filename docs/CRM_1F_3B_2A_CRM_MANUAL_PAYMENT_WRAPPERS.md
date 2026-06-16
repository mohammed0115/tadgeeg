# CRM-1F-3B-2A — CRM Manual Payment Service Wrappers

## Summary
Adds three **service-layer** CRM wrappers for manual (offline / bank-transfer)
payments — `crm_add_manual_payment`, `crm_confirm_manual_payment`,
`crm_reject_manual_payment` — on top of the official billing + payment services
from CRM-1F-3B-1. **No UI, forms, routes, views, templates, models, migrations,
or commit.**

## What wrappers were added (`apps/platform_admin/services/crm_operations.py`)
```python
crm_add_manual_payment(*, actor, organization, plan, amount, currency, reference, reason, request=None)
crm_confirm_manual_payment(*, actor, organization, payment, reason, request=None)
crm_reject_manual_payment(*, actor, organization, payment, reason, request=None)
```

## Why no UI yet
This phase delivers only the guarded, audited service layer so it can be tested
in isolation. The forms / routes / views / Payments-tab UI come in CRM-1F-3B-2B.

## How `add` works
1. Gate: `can_manage_financial_crm_data`; `reason` + `reference` required.
2. Defense-in-depth guards: reject if the org has a usable subscription, or
   already has a pending manual payment.
3. Inside `transaction.atomic`: create a **pending** subscription via the official
   `SubscriptionService.create_pending_paid_subscription`, then a **pending**
   manual payment via `PaymentService.create_manual_payment` (no gateway, no
   signal, no activation). Writes AuditLog + CustomerActivity.
4. Never writes `PaymentTransaction` / `OrganizationSubscription` directly.
   Billing/payment errors are converted to `ValidationError`.

## How `confirm` works
Gate + `reason`. Validates the payment belongs to the org, is `provider=manual`,
`status=pending`, `purpose=subscription`, linked to a subscription. Calls
`PaymentService.mark_paid`, which fires the existing
`payment_paid → subscription activation` signal chain. Double-confirm is rejected
(status check + `mark_paid` returning `False`) with no duplicate audit. No gateway,
no webhook, no direct status write.

### Confirm-time double-active guard (hardening)
Between `add` and `confirm` the organization may have **gained a usable
subscription** (e.g. a hosted payment completed in the meantime). Confirming then
would `mark_paid → activate` this pending subscription and hit the
one-usable-per-org constraint — potentially leaving the payment **PAID with no
active subscription**. To prevent that, `crm_confirm_manual_payment` re-checks
**inside `transaction.atomic`, under `select_for_update`**, BEFORE calling
`mark_paid`:

- the linked subscription still exists for the org and is still
  `PENDING_PAYMENT`;
- the org has **no other** `active`/`trialing` (usable) subscription.

If another usable subscription now exists, it raises a clear `ValidationError`
and: **does not call `mark_paid`**, the payment **remains `pending`**, the linked
subscription **stays `pending_payment`**, and **no** `manual_payment_confirmed`
AuditLog or CustomerActivity is written.

## How `reject` works
Gate + `reason`. Validates org ownership, `provider=manual`, `status=pending`
(paid payments cannot be rejected). Calls `PaymentService.mark_canceled` — which
does **not** activate the subscription. Writes AuditLog + CustomerActivity.

## Permission behavior
Allowed: Platform Owner, Finance Officer, and `superuser + is_staff` (even outside
CRM groups). Denied: Platform Admin (excluded by the helper), Support Agent,
Readonly Auditor, staff-without-group, customer users, anonymous, and
`superuser without is_staff`. Permission helpers were **not** modified.

## Superadmin rule
`is_staff && is_superuser` → allowed (implicit owner); `is_superuser && !is_staff`
→ denied. Verified for add/confirm/reject (consistent with extend / suspend).

## Audit / activity behavior
`AuditLog` via `log_crm_action`: `details["action_type"]` ∈
{`manual_payment_added`, `manual_payment_confirmed`, `manual_payment_rejected`},
with `reason` and `old_value`/`new_value`. `CustomerActivity.activity_type` uses
the matching literals (documented technical debt). The `AuditLog.Action` enum is
not extended. `PaymentLog` is written by the underlying payment services.

## Secret redaction
`old_value`/`new_value`/activity-metadata are built by `_manual_payment_safe`,
which exposes only: `payment_id, provider, status, amount, currency, reference
(=provider_reference), subscription_id, plan_id`. It **never** includes
`raw_request/raw_response/raw_webhook/provider_payment_id/checkout_url/
idempotency_key` or any secret. A test asserts none of those keys appear.

## Tests run
`apps/platform_admin/tests/test_crm_manual_payment_operations.py` (29): add
(creates pending sub+payment, not activated, audit/activity, no secrets, role
matrix incl. superuser±staff + customer, reason/reference/amount/usable-sub/
duplicate guards); confirm (activates via signal chain, paid, audit/activity, role
matrix, wrong-org, non-manual, double-confirm rejected); reject (cancels without
activation, audit/activity, wrong-org, paid-cannot-be-rejected, role matrix).
```
python manage.py check                              # 0 issues
python manage.py makemigrations --check --dry-run   # No changes detected
python -m pytest apps/platform_admin/tests/test_crm_manual_payment_operations.py --no-cov -q  # 29 passed
python -m pytest apps/payments/tests/test_manual_payment.py apps/billing/tests/ apps/platform_admin/tests/ --no-cov -q  # regression
```

## Risks / Notes
- **Resolved:** the add→confirm "double-active" race is now blocked by the
  confirm-time guard above (row-locked re-check before `mark_paid`); the payment
  stays `pending` instead of becoming a PAID-without-activation orphan.
- Amount is forced to the plan price (no partial/discount) — matches hosted.
- `manual_payment_*` activity types are literals pending a future enum migration.

## Next step
**CRM-1F-3B-2B** — UI/forms/routes/views: an "Add Manual Payment" form +
Confirm/Reject buttons in the Customer Profile → Payments tab, behind
`can_manage_financial_crm_data`, CSRF-protected POST-only, calling these wrappers.
