# CRM-OPERATIONS-UX-A — Delivered + GAP report

## Delivered in this phase
- **Customer Operations dashboard** (`/platform-admin/crm/`): KPI cards
  (Organizations, Active subscriptions, Pending payments, Open tickets,
  Suspended), a **Payments-needing-attention** work queue, a recent-tickets
  queue, recent-activity timeline, **Quick actions**, and a professional
  **empty state** when there are no customers.
- All counts/queues read **real `Organization` / `OrganizationSubscription` /
  `PaymentTransaction`** data (no fake data). Selector:
  `get_dashboard_summary()` + `get_payments_needing_attention()`.
- No raw provider JSON / secrets / card data rendered (tested).

## Already in place (no rebuild needed)
- **Customer 360** — `customer_detail.html` is already a tabbed profile
  (Overview, Users, Subscription, Payments, Tickets, Notes, Activity, Audit)
  reading real subscription/payment/usage data via `get_crm_customer_profile`.
- **Data bridge** — registration creates an `Organization`
  (`apps/authentication/services/organization_setup.ensure_user_organization`),
  and the CRM directory reads the canonical `Organization` model. The
  "Registration data bridge" is NOT missing.
- Sensitive financial ops (extend / suspend / reactivate / manual payment
  add·confirm·reject) already go through the service layer, are CSRF-protected,
  permission-gated, require a `reason`, and write audit + activity logs.

## GAPs — proposed as separate phases (not built here, by scope control)

### GAP 1 — Add-Customer wizard → propose **CRM-DATA-BRIDGE-B**
There is **no CRM flow to create an Organization manually** (creation today is
only via the platform API `PlatformOrganizationListView`). Building a 4-step
Add-Customer wizard (company → owner user → plan/trial → review) safely requires
a new create-organization service that also provisions an owner `User` and
optionally a subscription/trial — which touches the auth/registration domain.
That is a feature, not a styling fix, so it should be its own phase with its own
tests and permission decisions. **Recommendation:** CRM-DATA-BRIDGE-B.

### GAP 2 — Multi-step financial wizards → propose **CRM-WIZARD-C**
Manual-payment add/confirm/reject and suspend/reactivate are currently inline,
single-screen POST forms inside the Customer 360 tabs. They already enforce
reason + server-side double-active / idempotency guards and are heavily tested
(517+ green). Converting them into multi-step steppers with an explicit
"impact preview" step is a UX improvement but a sizeable change that risks
regressing the verified financial flows. **Recommendation:** do it as
CRM-WIZARD-C with the steppers layered on top of the same (unchanged) service
calls, so the backend stays identical.

## Why this split
Scope-control: deliver the operations-console foundation with the least risky
change, keep the tested payment/subscription logic untouched, and stage the two
larger feature areas (org creation, multi-step wizards) as their own phases.
