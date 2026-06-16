# CRM-1F-1A — Official Billing `extend_subscription` Service

## Summary
Adds **one** official billing service — `SubscriptionService.extend_subscription(...)` —
that moves a usable subscription's `ends_at` forward by a number of days. This is
the *billing-layer* primitive; no CRM UI/forms/routes/audit are added here (those
come in CRM-1F-1B). No models, no migrations.

## Why this is a billing service, not a CRM wrapper
The CRM-1F-A audit established that the CRM must never write to
`OrganizationSubscription` directly — all subscription state changes must go
through an official `apps/billing` service (atomic + row-locked + idempotent).
Since no extend operation existed, the billing primitive must be created **first**;
the CRM wrapper (CRM-1F-1B) will later call this and add `AuditLog` +
`CustomerActivity` + permission gating. Keeping the audit out of billing matches
the existing billing services, which log via the `logging` module but do not write
the `AuditLog` model.

## Rules
- `days` must be a **positive `int`** — `0`, negatives, non-ints, and `bool`
  (`True`/`False`) are rejected with `ValidationError`.
- Only **usable** subscriptions (`TRIALING`, `ACTIVE`) are extendable. `EXPIRED`,
  `CANCELED`, `PAYMENT_FAILED`, and `PENDING_PAYMENT` are refused with
  `SubscriptionNotExtendable`.
- A usable subscription with **no `ends_at`** is treated as a data anomaly and
  **refused** (not silently anchored to `now`) — the safest choice, surfacing the
  anomaly instead of guessing.
- Uses `@transaction.atomic` + `select_for_update()` on the subscription row.

## What fields are changed
- `ends_at` → `ends_at + timedelta(days=days)`
- `updated_at` (automatic)

## What fields are NOT changed
`starts_at`, `status`, `plan`, `invoice_limit`, `used_invoices`,
`reserved_invoices`, `payment_transaction`. No `PaymentTransaction` is created, no
payment signals are emitted, no quota is touched.

## Status validation
| Status | Extendable? |
|---|---|
| `trialing` | ✅ |
| `active` | ✅ |
| `pending_payment` | ❌ `SubscriptionNotExtendable` |
| `expired` | ❌ |
| `canceled` | ❌ |
| `payment_failed` | ❌ |
| (usable but `ends_at is None`) | ❌ |

## Signature
```python
SubscriptionService().extend_subscription(
    subscription,
    *,
    days: int,
    reason: str | None = None,   # logged for traceability; AuditLog is added by the CRM wrapper
    actor=None,                  # logged for traceability
) -> OrganizationSubscription
```
Returns the locked, updated subscription. Raises `ValidationError` (bad `days`) or
`SubscriptionNotExtendable` (bad status / missing end date).

## Tests run
File: `apps/billing/tests/test_extend_subscription.py` (15 tests) — active/trialing
extend, persistence, invalid days (0/neg/str/bool), all non-extendable statuses,
missing `ends_at`, immutability of every other field, no `PaymentTransaction`
created, and rejected-extend leaves `ends_at` unchanged.

```
python manage.py check                              # 0 issues
python manage.py makemigrations --check --dry-run   # No changes detected
python -m pytest apps/billing/tests/test_extend_subscription.py --no-cov -q   # 15 passed
python -m pytest apps/billing/tests/ apps/platform_admin/tests/ --no-cov -q   # regression
```

## Risks / Notes
- `reason`/`actor` are accepted but only **logged** here (no `AuditLog`); the CRM
  wrapper is responsible for the formal audit trail. Do not treat this service as
  audited on its own.
- This service does not enforce CRM permissions — it must only be called from a
  permission-gated CRM wrapper (CRM-1F-1B) or other trusted caller.
- Extending does not re-activate an expired/canceled subscription by design;
  reactivation is a separate future operation.

## Next step
**CRM-1F-1B** — CRM wrapper `crm_extend_subscription(actor, organization,
subscription, days, reason, request=None)` behind `can_manage_financial_crm_data`,
writing `AuditLog` (`action_type="subscription_extended"`, old/new `ends_at`,
`reason`) + `CustomerActivity`, plus the CSRF-protected POST view/form/UI.
