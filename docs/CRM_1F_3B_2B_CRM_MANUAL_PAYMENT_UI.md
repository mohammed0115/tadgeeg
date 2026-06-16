# CRM-1F-3B-2B — CRM Manual Payment UI / Forms / Routes / Views

## Summary
Adds the CRM **UI layer** for manual (offline / bank-transfer) payments inside
Customer Profile → Payments tab: an **Add Manual Payment** form plus **Confirm**
and **Reject** actions on pending manual payments. The views are thin and call
only the CRM-1F-3B-2A wrappers — no direct PaymentTransaction/Subscription
writes, no payment-service/provider changes, no migrations.

## Routes added (`platform_admin:crm:*`, all POST-only)
| Name | Path |
|------|------|
| `manual_payment_add` | `/platform-admin/crm/customers/<org_id>/payments/manual/add/` |
| `manual_payment_confirm` | `/platform-admin/crm/customers/<org_id>/payments/<payment_id>/confirm/` |
| `manual_payment_reject` | `/platform-admin/crm/customers/<org_id>/payments/<payment_id>/reject/` |

GET on any of them returns **405**; all forms are CSRF-protected; every view
redirects back to the Customer Profile.

## Forms added (`apps/platform_admin/forms.py`)
- `ManualPaymentAddForm` — whitelisted: `plan` (ModelChoiceField over
  `get_purchasable_plans()`), `amount`, `currency`, `reference`, `reason`. No
  status/provider/user/raw fields. `reference`/`reason` required.
- `FinancialReasonForm` (existing, reused) — reason-only for confirm/reject.

The authoritative `amount == plan.price` / `currency == plan.currency` rule is
enforced **server-side by the payment service**; the form validates shape only.

## UI behavior (Payments tab)
- **Add Manual Payment** section renders only for `can_manage_financial_crm_data`
  (Owner/Finance/superuser+staff). Warning: *"This will create a pending manual
  payment and will be audited."*
- Payments table shows safe fields only: provider, amount+currency, status badge,
  **reference** (`provider_reference`), created, paid. An **Actions** column
  (financial managers only) shows **Confirm** (green) + **Reject** (red) — each
  with a required reason input — **only** when `provider == manual` and
  `status == pending`. Confirm/Reject warnings are on the buttons.
- **Never rendered:** `raw_request/raw_response/raw_webhook/provider_payment_id/
  checkout_url/idempotency_key` (a test asserts their absence).

## Permission behavior
Allowed: Platform Owner, Finance Officer, `superuser + is_staff` (even outside CRM
groups). Denied (403 / hidden): Platform Admin (excluded by the helper), Support
Agent, Readonly Auditor, staff-without-group, customer users, anonymous (→ login),
and `superuser without is_staff`. Permission helpers were **not** modified; views
use the existing `crm_financial_required` gate.

## Superadmin rule
`is_staff && is_superuser` → allowed (add/confirm/reject); `is_superuser &&
!is_staff` → denied (403). Verified by tests.

## Add flow
View → `ManualPaymentAddForm` (valid?) → `crm_add_manual_payment(...)` which
creates a pending subscription + pending manual payment via the official
services. Errors (`ValidationError`) become a flash message; nothing is written.
Redirect to the profile.

## Confirm flow
View → `FinancialReasonForm` → `crm_confirm_manual_payment(...)` →
`PaymentService.mark_paid` → existing signal chain activates the subscription. The
wrapper's confirm-time double-active guard keeps the payment **pending** with a
safe error if the org gained a usable subscription meanwhile. Double-confirm is a
safe no-op error.

## Reject flow
View → `FinancialReasonForm` → `crm_reject_manual_payment(...)` →
`PaymentService.mark_canceled` (no activation). Paid payments cannot be rejected.

## Secret redaction
The payments selector fetches `.only(PAYMENT_SAFE_FIELDS)` (now including
`provider_reference`), and the template renders only those safe fields. No raw
payloads, provider ids, checkout urls, or idempotency keys reach the HTML or any
flash message. Error messages surface only the wrappers' safe `ValidationError`
text (no stack traces, no secrets).

## What changed
- `apps/platform_admin/forms.py` — `ManualPaymentAddForm`.
- `apps/platform_admin/crm_urls.py` — 3 POST routes.
- `apps/platform_admin/crm_views.py` — 3 thin views (+ `manual_payment_plans` in
  the profile context).
- `apps/platform_admin/selectors.py` — `get_payment_for_customer` (tenant-scoped),
  `get_purchasable_plans`, and `provider_reference` added to `PAYMENT_SAFE_FIELDS`.
- `templates/platform_admin/crm/customer_detail.html` — Payments tab Add form +
  reference column + Confirm/Reject actions.
- `apps/platform_admin/tests/test_crm_manual_payment_ui.py` — new tests.

## What did NOT change
No models, no migrations, no payment service/provider/webhook changes, no receipt
upload, no partial payment / discount / change-plan / adjust-quota, no
Docker/Tailwind/frontend, no permission-helper edits, no direct writes in views,
no commit.

## Tests run
`apps/platform_admin/tests/test_crm_manual_payment_ui.py` (34): visibility (add
form per role; confirm/reject only for pending manual; not for hosted/terminal; no
secrets), add view (create by Owner/Finance/superuser; denied roles incl.
superuser-no-staff; anonymous redirect; GET 405; invalid form / amount mismatch /
usable-sub → no write), confirm view (paid + activates; superuser; denied roles;
wrong-org 404; GET 405; reason missing; double-active guard keeps pending; double
confirm), reject view (cancels without activation; paid cannot be rejected;
wrong-org 404; GET 405; reason missing).
```
python manage.py check                              # 0 issues
python manage.py makemigrations --check --dry-run   # No changes detected
python -m pytest apps/platform_admin/tests/test_crm_manual_payment_ui.py --no-cov -q  # 34 passed
python -m pytest apps/payments/tests/ apps/billing/tests/ apps/platform_admin/tests/ --no-cov -q  # regression
```

## Risks / Notes
- Finance enters `amount` manually; a mismatch with the plan price is rejected
  server-side (no write) and shown as a flash error. A future enhancement could
  auto-fill the amount from the chosen plan via the template.
- Confirm/Reject use a per-row reason input; the existing `FinancialReasonForm`
  validates it server-side.

## Next step
CRM-1F-3B is feature-complete (provider + service + wrappers + UI). A natural
follow-up is **CRM-1F-3C** hardening/QA (e.g. back-dated `paid_at`, a dedicated
"manual payments" review queue) or promoting the literal activity types to the
`CustomerActivity.ActivityType` enum via a consolidated migration.
