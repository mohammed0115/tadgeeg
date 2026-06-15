# CRM-1F-1B — CRM Extend Subscription Wrapper + UI

## Summary
Adds the first **financial** CRM operation: extend a customer's subscription from
**Customer Profile → Subscription tab**. The CRM wrapper delegates the actual
date change to the official `billing.extend_subscription` service (CRM-1F-1A) and
owns the permission gate, tenant check, reason requirement, and the AuditLog +
CustomerActivity trail. Only **Extend** is implemented — no suspend/reactivate/
change-plan/manual-payment. No models, no migrations.

## Files changed
- `apps/platform_admin/services/crm_operations.py` — `crm_extend_subscription()`.
- `apps/platform_admin/forms.py` — `ExtendSubscriptionForm` (+ `MAX_EXTEND_DAYS`).
- `apps/platform_admin/crm_views.py` — `crm_financial_required` gate +
  `subscription_extend` view; `customer_detail` passes `can_manage_financial`.
- `apps/platform_admin/crm_urls.py` — POST-only extend route.
- `apps/platform_admin/selectors.py` — `get_subscription_for_customer()` (tenant-scoped).
- `templates/platform_admin/crm/customer_detail.html` — flash messages + extend
  form in the Subscription tab.
- `apps/platform_admin/tests/test_crm_financial_operations.py` — new tests.
- `docs/CRM_1F_1B_CRM_EXTEND_SUBSCRIPTION.md` — this file.

## CRM wrapper design
```python
crm_extend_subscription(*, actor, organization, subscription, days, reason, request=None)
```
1. `can_manage_financial_crm_data(actor)` → else `PermissionDenied`.
2. `reason` required (stripped, non-empty); `days` a positive `int` (bools rejected).
3. `subscription.organization_id == organization.id` → else `ValidationError`
   (tenant ownership; the view also scopes the lookup, so cross-tenant ids 404).
4. Captures `old_ends_at`, calls **`SubscriptionService().extend_subscription(...)`**
   (the official, atomic, row-locked service) — never writes `ends_at` directly.
5. Wraps the call + audit + activity in one `transaction.atomic` so they commit
   together; the billing service's row lock is held through the audit writes.
6. Writes `AuditLog` and `CustomerActivity`; returns the updated subscription.
   Creates no `PaymentTransaction`, emits no signals, changes nothing but `ends_at`.

## Permission model
Uses the existing CRM-1B helpers unchanged.
- **Can extend** (`can_manage_financial_crm_data` = Owner + Finance).
- **Cannot**: Support Agent, Readonly Auditor, Platform Admin (excluded by the
  current helper — left as-is), staff without a CRM group, customer users,
  anonymous. View returns **403** for authenticated-but-unauthorized, **302→login**
  for anonymous.

## UI behavior
- The Subscription tab is visible to financial **viewers** (Owner/Admin/Finance/
  Readonly). The **Extend form** renders only when `can_manage_financial` **and**
  the subscription `is_usable` (active/trialing).
- Fields: `days` (1–730), `reason` (required). Warning copy: *"This action changes
  the subscription end date and will be audited."* CSRF-protected POST; no GET
  mutation; no link-based action. Support/Readonly see no write controls (Support
  doesn't even see the financial tab). No suspend/reactivate/change-plan/manual
  buttons are rendered.

## Audit / activity behavior
- `AuditLog` via `log_crm_action`: `details["action_type"]="subscription_extended"`,
  `reason`, `old_value={"ends_at": <old iso>}`, `new_value={"ends_at": <new iso>,
  "days": <n>}`, `resource_type="OrganizationSubscription"`, `resource_id=<sub id>`.
  The `AuditLog.Action` enum is not extended.
- `CustomerActivity`: literal `activity_type="subscription_extended"` (no enum
  member — documented technical debt, same approach as `ticket_assigned`), with
  `days`/`old_ends_at`/`new_ends_at`/`subscription_id` in metadata.

## What changed
A subscription's `ends_at` (via the billing service) plus an audit + activity row.

## What did NOT change
plan, status, `invoice_limit`, `used_invoices`, `reserved_invoices`,
`payment_transaction`, `starts_at`. No payments, no signals, no models, no
migrations, no permission-helper edits, no billing-service edits.

## Tests run
`apps/platform_admin/tests/test_crm_financial_operations.py` covers: service
(Owner/Finance extend + audit/activity; Support/Readonly/Admin/no-group denied;
reason required; invalid days; cross-tenant; delegates to billing via mock; no
PaymentTransaction; only `ends_at` changes), form (valid; days 0/neg/>max; blank
reason), view (Finance/Owner 302+extend; Support/Readonly/Admin 403; anonymous
login redirect; non-staff 403; GET 405; cross-tenant/missing 404; invalid form no
write; redirect target), and UI smoke (form visible for Finance, hidden for
Readonly/Support; no other financial action routes rendered).

```
python manage.py check                              # 0 issues
python manage.py makemigrations --check --dry-run   # No changes detected
python -m pytest apps/platform_admin/tests/test_crm_financial_operations.py \
                apps/billing/tests/test_extend_subscription.py \
                apps/platform_admin/tests/ --no-cov -q
```

## Known pre-existing failure note
`apps/billing/tests/test_ui.py::UsagePageTests::test_usage_page_pagination_when_many_rows`
fails on an English assertion (`"Page 1 of 3"`) vs the Arabic UI (`"صفحة 1 من 3"`).
It is **pre-existing** (fails on CRM-1E without any of these changes), locale-
related, and **out of scope** — not fixed here.

## Risks / Notes
- `MAX_EXTEND_DAYS = 730` (2 years) is an operational safety cap on a single
  action; larger extensions require repeated deliberate actions.
- The wrapper enforces permissions itself (defense in depth) in addition to the
  view gate.
- `subscription_extended` activity type is a literal pending a future enum
  migration.

## Recommended next step
**CRM-1F-2** — `change_plan` / `adjust_invoice_limit` (and/or suspend/reactivate),
each first adding the official billing primitive, then the CRM wrapper + UI behind
`can_manage_financial_crm_data`. Manual payment (CRM-1F-3) remains last (needs a
provider/pricing decision + migration).
