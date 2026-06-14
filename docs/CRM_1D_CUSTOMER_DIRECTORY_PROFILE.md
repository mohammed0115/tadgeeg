# CRM-1D — Customer Directory + Customer Profile (Read-only Expansion)

## Summary
CRM-1D enriches the existing read-only Platform CRM with a stronger **Customer
Directory** (search, filters, per-row signals) and a tabbed **Customer Profile**
(Overview, Users, Subscription, Payments, Tickets, Notes, Activity, Audit). It is
**read-only**: no models, no migrations, no forms, no mutations, and no
billing/payments/subscription writes. Subscription + payment data are read through
existing models only and are gated behind the CRM-1B financial permission.

## Files changed
- `apps/platform_admin/selectors.py` — added directory + profile read selectors.
- `apps/platform_admin/crm_views.py` — `customers_list` and `customer_detail`
  rewired to the new selectors with financial gating.
- `templates/platform_admin/crm/customers_list.html` — richer table + filters.
- `templates/platform_admin/crm/customer_detail.html` — 8 read-only tabs.
- `apps/platform_admin/tests/test_crm_directory_profile.py` — new tests (30).
- `docs/CRM_1D_CUSTOMER_DIRECTORY_PROFILE.md` — this file.

## What changed
- New selectors: `list_crm_customers`, `enrich_customer_rows`,
  `get_customer_users`, `get_customer_primary_contact`,
  `get_customer_subscription_summary`, `get_customer_payment_summary`,
  `get_customer_ticket_summary`, `get_customer_activity_timeline`,
  `get_customer_audit_timeline`, `get_crm_customer_profile`.
- Directory rows enriched (batched, no N+1): user count, last login, primary
  contact email, open-ticket count, and — for financial roles — active plan +
  subscription status.
- Profile shows all eight tabs from real model data, with safe fallbacks.

## What did NOT change
No changes to `apps/billing`, `apps/payments`, `apps/authentication/models.py`,
subscription/payment services or webhooks, invoice/report logic, the customer
(vendor) dashboard, scoring, settings, or `crm_urls.py`/permissions. No migrations.

## Read-only guarantee
- All views are GET/HEAD only; any other method returns **405** (the
  `crm_read_required` gate from CRM-1C).
- Filter forms use `method="get"`; there is no CRM `method="post"` form.
- Selectors perform reads only — no `save()/update()/delete()`, and they never
  call billing/payments state-changing services (no `activate`, `mark_paid`, etc.).
- Payment data is read via `.only(<safe fields>)`; **raw_request/raw_response/**
  **raw_webhook, checkout_url, idempotency_key, provider_payment_id are never
  surfaced** in selectors or templates.

## Customer Directory features
Search across English/Arabic name, VAT, CR, and linked user email; filters for
account status (active/inactive), country, and (financial roles) subscription
presence. Table columns: customer (EN/AR), country, status badge, users count,
primary contact, plan + subscription status (financial), open-ticket count, last
user login, and an "Open" link. Responsive with horizontal scroll, empty state,
and pagination.

## Customer Profile tabs
1. **Overview** — name/AR, country, currency, VAT, CR, industry, created_at,
   primary contact, users count (missing fields render `—`).
2. **Users** — full name, email, role, staff badge, active status, last login.
3. **Subscription** *(financial)* — plan, status, starts/ends, invoice_limit,
   used/reserved, remaining (read-only property); empty state when none.
4. **Payments** *(financial)* — recent transactions: provider, purpose, amount,
   status, created/paid; counts. No confirm/reject/manual payment.
5. **Tickets** — title, category, priority, status, assignee, updated; links to
   the existing ticket detail. No create.
6. **Notes** — category, author, date, text. No add.
7. **Activity** — `CustomerActivity` timeline (type, description, actor, time).
8. **Audit** — `AuditLog` scoped to the org, showing `details["action_type"]` and
   `reason` only — never the full payload.

## Security / permissions
- Reuses CRM-1B permissions unchanged. `crm_read_required` = `login_required` +
  `can_view_crm` (is_staff + CRM group, superuser implicit).
- Anonymous → login redirect; non-staff → 403; staff without CRM group → 403;
  all five CRM roles can view.
- **Financial gating:** Subscription and Payments tabs/columns are rendered only
  when `can_view_financial_crm_data` is true (Owner/Admin/Finance/Readonly).
  Support Agent does not see them, and the financial selectors are not even called
  for that role (defense in depth).
- Read-only Auditor sees everything but no write controls exist anywhere.

## Tests run
```
python manage.py check                              # 0 issues
python manage.py makemigrations --check --dry-run   # No changes detected
python -m pytest apps/platform_admin/tests/ --no-cov -q   # 114 passed
```
New tests cover: directory listing/search (name + user email)/filters
(active/inactive/country/subscription), row enrichment + financial gating,
subscription/payment summaries (including the no-data path), the profile bundle +
financial gate, access matrix (anonymous/non-staff/no-group/all roles), 404 for
missing org, 405 on POST, financial visibility difference between Support and
Finance, and the no-CRM-POST-form guarantee.

Note on locale: the test database renders in Arabic, so assertions target
language-independent tokens (DB plan name, Alpine `tab==='…'` markers) rather than
translated labels or locale-formatted numbers.

## Risks / Notes
- `invoice_limit` is a frozen snapshot on the subscription (by billing design);
  the profile reads it from the subscription, not the plan — correct and intended.
- The directory enriches only the current page's rows; sorting/searching by
  enriched values (e.g., plan) is not supported yet (would need annotations).
- No sidebar link was added (project menu pattern not in scope for this phase).

## Recommended next step
**CRM-1E — Support Ticketing operations** (status transitions, internal/public
messages) — the first phase to introduce guarded, audited **writes** via the
CRM-1B services, behind `can_manage_tickets`, with CSRF-protected POST flows.
