# CRM-1C — Platform CRM Read-only Dashboard Shell

## Summary
CRM-1C adds a **read-only** Platform CRM dashboard shell under `/platform-admin/crm/`.
It lets platform CRM staff browse customers (Organizations), support tickets,
internal notes, and the activity/audit trail — with **zero** create/update/delete
surface and **no** billing/payments/subscription access. No models or migrations
were added or changed.

## Scope
- Read-only views, selectors, templates, URLs, and tests only.
- Reuses CRM-1B models (`SupportTicket`, `TicketMessage`, `CustomerNote`,
  `CustomerActivity`) and CRM-1B permissions.
- The "customer" is the existing `authentication.Organization` (no new model).

## Files changed
**New**
- `apps/platform_admin/selectors.py` — read-only query layer.
- `apps/platform_admin/crm_views.py` — GET-only views + `crm_read_required` gate.
- `apps/platform_admin/crm_urls.py` — `platform_admin:crm` URL namespace.
- `templates/platform_admin/crm/` — `_nav.html`, `_badges.html`, `dashboard.html`,
  `customers_list.html`, `customer_detail.html`, `tickets_list.html`,
  `ticket_detail.html`, `notes_list.html`, `activities_list.html`.
- `apps/platform_admin/tests/test_crm_views_access.py`
- `apps/platform_admin/tests/test_crm_selectors.py`

**Modified (1 line of routing)**
- `apps/platform_management/urls.py` — mounts `crm/` → `apps.platform_admin.crm_urls`.

**Not changed:** no models, no migrations, no settings (beyond CRM-1B's already-committed
INSTALLED_APPS entry), no billing/payments/auth/invoice/report/webhook code.

## Routes added (namespace `platform_admin:crm`)
| Name | Path | View |
|------|------|------|
| `dashboard` | `/platform-admin/crm/` | `crm_dashboard` |
| `customers` | `/platform-admin/crm/customers/` | `customers_list` |
| `customer_detail` | `/platform-admin/crm/customers/<uuid>/` | `customer_detail` |
| `tickets` | `/platform-admin/crm/tickets/` | `tickets_list` |
| `ticket_detail` | `/platform-admin/crm/tickets/<uuid>/` | `ticket_detail` |
| `notes` | `/platform-admin/crm/notes/` | `notes_list` |
| `activities` | `/platform-admin/crm/activities/` | `activities_list` |

## Views added
All GET/HEAD-only (the decorator returns 405 on any other method), all decorated
with `crm_read_required`. No view writes to the database.

## Selectors added (`apps/platform_admin/selectors.py`)
`get_dashboard_summary`, `get_recent_tickets`, `get_recent_activities`,
`get_recent_crm_audits`, `list_tickets`, `list_customers`, `list_notes`,
`list_activities`, `get_customer`, `get_customer_tickets/notes/activities/audits`,
`get_ticket`, `get_ticket_messages`, `get_ticket_audits`, `paginate`.
Filters from GET (`q`, `status`, `priority`, `assigned_to`, date range, `category`,
`activity_type`) are validated against real model choices / UUID format before
hitting the ORM; invalid values are ignored, never raised. `select_related` is used
throughout; lists are paginated (25/page).

### Dashboard content (only real model fields)
- Total customers + active count → `Organization` count / `is_active`.
- Open / unresolved / high-priority tickets → `SupportTicket.status` + `priority`.
- Customer-note and activity totals → `CustomerNote` / `CustomerActivity` counts.
- Recent tickets, recent activity, recent CRM audit trail (AuditLog scoped to CRM
  `resource_type` values).

## Templates added
Extend `layouts/base_platform_admin.html` (existing platform layout, Tailwind +
Alpine + Lucide, Arabic/English RTL-aware via `{% trans %}`). Responsive, with
breadcrumb/title, a "Read-only" badge, status/priority badges, empty states,
pagination, and back-links on detail pages. No edit/delete/status buttons.

## Permission model used
`crm_read_required` (in `crm_views.py`) layers on the CRM-1B helpers:
`login_required` + `can_view_crm` (which itself requires `is_staff` **and** a CRM
group, with superuser as implicit owner). It is **stricter** than the legacy
`platform_admin_required` (is_staff only). Readonly Auditor passes (read access);
Support/Finance/Admin/Owner pass. Detail views additionally 404 on missing objects.

Note: `NamespaceAccessControlMiddleware` is present in the codebase but is **not**
enabled in `MIDDLEWARE`; the project guards platform pages with decorators. CRM-1C
follows that pattern and does not change middleware.

## Read-only confirmation
- No forms POST; filter forms use `method="get"`.
- `crm_read_required` returns **405** for any non-GET/HEAD method.
- No create/update/delete views, no service mutation calls, no status transitions.
- Test `test_post_is_method_not_allowed` and `test_post_does_not_mutate` enforce this.

## Forbidden areas confirmation
No changes to `apps/billing/`, `apps/payments/`, `apps/authentication/models.py`,
payment webhooks, invoices, subscription logic, reports, or production settings.
Verified via `git status` (only `apps/platform_admin/*`, `templates/platform_admin/crm/*`,
and the single `apps/platform_management/urls.py` routing line changed).

## Tests run
`python manage.py check` → 0 issues.
`python manage.py makemigrations --check --dry-run` → "No changes detected".
`python -m pytest apps/platform_admin/tests/ --no-cov -q` → **84 passed**
(31 from CRM-1B + 53 new). Coverage gate disabled with `--no-cov` because a
single-folder run cannot meet the global `--cov-fail-under=45`.

Coverage includes: access permissions (anonymous/non-staff/staff-without-group/
CRM-user) across all list + detail routes, dashboard/list rendering, empty states,
related-record rendering on detail pages, 404 handling, pagination, selector
filtering/validation, and the no-mutation (405) guarantee.

## Risks / follow-up
- The platform sidebar (`navigation/platform_menu.py`) was intentionally **not**
  edited; CRM is reached by direct URL or in-page tabs. Adding a sidebar entry is a
  low-risk follow-up.
- `NamespaceAccessControlMiddleware` is dormant; if it is ever enabled, non-staff
  users would be redirected (302) instead of 403 — both block access. The access
  tests assert the current decorator behavior.
- Usage/financial tabs (payments, subscriptions) are deliberately absent — they
  belong to later phases and require the service layer, not direct reads.

## Next recommended phase
**CRM-1D** — extend the customer profile and directory (richer overview, users tab,
read-only subscription/payment summaries via selectors that call the existing
billing/payments **read** APIs), still without mutations. Operational write actions
remain deferred to CRM-1E (ticketing) and CRM-1F (subscription/payment ops).
