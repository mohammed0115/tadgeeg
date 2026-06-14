# CRM-1E — Platform CRM Support Ticketing Operations

## Summary
CRM-1E adds the first **guarded writes** to the Platform CRM: create a support
ticket, reply (public/internal), change status via safe transitions, and assign
to CRM staff. Every write goes through a service (`transaction.atomic`), enforces
`can_manage_tickets`, and records both the formal `AuditLog` and a
`CustomerActivity` timeline entry. No models, no migrations, no
billing/payments/subscription changes, no GET mutations.

## Files changed
**New**
- `apps/platform_admin/forms.py` — explicit, whitelisted ticket forms.
- `apps/platform_admin/tests/test_crm_ticket_operations.py` — 29 tests.
- `templates/platform_admin/crm/create_ticket.html`.
- `docs/CRM_1E_SUPPORT_TICKETING_OPERATIONS.md`.

**Modified**
- `apps/platform_admin/services/crm_operations.py` — expanded ticket services
  (now `actor`-based; added `change_ticket_status`, `assign_ticket`).
- `apps/platform_admin/crm_views.py` — `crm_manage_required` gate + 4 write views;
  ticket/customer views pass `can_manage`.
- `apps/platform_admin/crm_urls.py` — write routes.
- `apps/platform_admin/selectors.py` — `get_assignable_crm_staff` (read-only).
- `templates/platform_admin/crm/tickets_list.html`, `ticket_detail.html`,
  `customer_detail.html` — manager-only "New Ticket"/forms/buttons.
- `apps/platform_admin/tests/test_crm_services.py`, `test_crm_selectors.py` —
  updated to the CRM-1E service contract (see "What changed").

## What changed
- Service API standardized on `actor=` (was `created_by`/`sender`), with a
  permission check inside each service.
- Create's AuditLog `details["action_type"]` is now `support_ticket_created`
  (was `ticket_created`); the two existing tests asserting the old value were
  updated to the new contract. The `CustomerActivity` type stays `ticket_created`.
- New routes under `/platform-admin/crm/tickets/`:
  `new/` (GET form + POST), `<uuid>/message/`, `<uuid>/status/`, `<uuid>/assign/`
  (all three POST-only).

## Ticket operations
- **Create** — `create_support_ticket(actor, organization, title, category,
  priority, description, assigned_to=None, request=None)`. status defaults to
  `open`; created_by = actor; assignee must be CRM staff.
- **Message** — `add_ticket_message(actor, ticket, message, internal_only=False)`.
  Never changes status (documented decision). `internal_only` flagged in UI.
- **Status** — `change_ticket_status(actor, ticket, new_status, reason)`. Reason
  required; only safe transitions allowed (open↔pending↔resolved↔closed; resolved→
  {open,closed}; closed→open). resolved_at policy: set on resolve; set on close if
  unset; cleared on reopen (→open).
- **Assign** — `assign_ticket(actor, ticket, assigned_to, reason)`. Assignee must
  be CRM staff or None (unassign); a normal customer user is rejected.

## Permissions
- Read (all five CRM roles): Owner, Admin, Support, Finance, Readonly.
- Write (`can_manage_tickets`): **Owner, Admin, Support only**. Finance and
  Readonly cannot write tickets in this phase; anonymous/non-staff/staff-without-
  CRM-group are blocked.
- Views use `crm_manage_required`; POST-only handlers return **405** on GET (no
  GET mutations). Services independently enforce `can_manage_tickets` (defense in
  depth). All POST forms are CSRF-protected.

## Audit / activity logging
Each operation writes `AuditLog` via `log_crm_action` with
`details["action_type"]` ∈ {`support_ticket_created`, `ticket_message_added`,
`ticket_status_changed`, `ticket_assigned`} (status/assign also store
`old_value`/`new_value`/`reason`), plus a `CustomerActivity` entry. The
`AuditLog.Action` enum is **not** extended and no `PlatformAuditLog` is created.
Assign uses the literal activity type `ticket_assigned` (no enum member exists;
adding one would require a migration, which is out of scope).

## What did NOT change
No `apps/billing`, `apps/payments`, `apps/authentication/models.py`, webhooks,
subscription services, invoice/report logic, customer dashboard, models, or
migrations. No payment/subscription actions, manual payment, suspend/reactivate,
plan change, customer-facing portal, email, or attachments.

## Security notes
- Forms are explicit `forms.Form` (no open ModelForm) — `created_by`, `status`,
  `resolved_at` cannot be injected.
- Assignee choices are restricted to CRM staff at both the form (queryset) and
  service (`is_platform_crm_user`) layers.
- Read-only Auditor and Finance see tickets but no write controls render for them.

## Tests run
```
python manage.py check                              # 0 issues
python manage.py makemigrations --check --dry-run   # No changes detected
python -m pytest apps/platform_admin/tests/ --no-cov -q   # 143 passed
```
New coverage: service create/message/status/assign (incl. reason-required,
invalid-transition, reopen-clears-resolved, assign-to-non-staff rejected,
non-manager PermissionDenied); form validation; view access matrix (managers 200 /
finance+readonly+others 403 / anonymous redirect); POST create/message/status/
assign succeed + redirect; readonly/finance POST → 403; write routes GET → 405;
POST to missing ticket → 404; UI smoke (New Ticket button + reply form only for
managers; internal badge).

## Risks / Notes
- `ticket_assigned` is stored as a literal `CustomerActivity.activity_type`
  (not an enum member) to avoid a migration; its display shows the raw value. A
  future migration-bearing phase can promote it to the enum.
- Invalid status/assign POSTs surface errors via the messages framework and
  redirect back (no partial writes).

## Recommended next step
**CRM-1F — Subscription + Payment Operations** (extend/change-plan/add-confirm-
reject payment, suspend/reactivate) — higher-risk writes that touch billing/
payments and must go strictly through their existing services behind
`can_manage_financial_crm_data`, with the same audit/activity discipline.
