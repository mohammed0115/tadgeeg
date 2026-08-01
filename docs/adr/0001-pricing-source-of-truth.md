# ADR 0001 — `billing.Plan` is the single source of truth for pricing

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 0-A (Admin API Surface Activation & Guardrails)

## Context

Two models describe "a plan" and they disagree.

**`apps/billing/models.py` — `Plan`.** The real one. It carries `code`,
`price`, `currency`, `invoice_limit`, `duration_days`, `is_trial`, `is_free`.
It drives:

- the public pricing page — `apps/frontend/page_views.py::pricing` reads
  `apps.billing.services.plan_service.list_purchasable_plans()` live from the
  database;
- plan selection and the upgrade/renew matrix — `apps/billing/views.py`;
- **payment authorisation** — `apps/payments/pricing.py::_subscription_resolver`
  resolves the authoritative amount from `sub.plan.price`, and a client-supplied
  amount that disagrees is rejected with `PriceMismatchError`.

**`apps/cms/models.py` — `PricingPlan`.** Marketing content. It carries
`price_monthly`, `price_annual`, `max_users`, `max_invoices`, `max_storage_gb`,
plus `PricingFeature` bullet rows. Nothing reads it for money.

The numbers conflict. `cms.PricingPlan` advertises `max_users` and
`max_storage_gb` — dimensions `billing.Plan` **does not implement at all**
(there is no seat limit or storage limit anywhere in the billing domain; the
team-invite endpoint returns `501 NOT_IMPLEMENTED`). Its `max_invoices` values
are unconstrained by the `invoice_limit` actually enforced by
`apps/billing/services/quota_service.py`.

Phase 0-A mounts `/api/platform-admin/pricing/`, which edits `cms.PricingPlan`.
Without an explicit rule, an operator could reasonably edit numbers there and
expect customers to be billed accordingly. They would not be.

## Decision

1. **`billing.Plan` is the sole source of truth** for purchasable plans, plan
   limits, and payment pricing. Every enforcement path already reads it; none
   may be moved.
2. **`cms.PricingPlan` is presentation content only.** It must never be read by
   a payment, quota, or entitlement path. It is **not deleted** — no data is
   destroyed in this phase.
3. **No prices or limits change in Phase 0-A.** `seed_billing_plans.py` is
   untouched.
4. **`apps/cms/urls.py` stays unmounted.** Its `public/pricing/` endpoint
   (`AllowAny`) would publish `cms.PricingPlan` numbers — including
   `max_users`/`max_storage_gb`, which the product cannot honour — directly to
   anonymous visitors, contradicting the live `/pricing/` page. The admin
   surface for this content is served through
   `apps/platform_management/api_urls.py` instead, which is staff-only.
5. A regression test asserts `/pricing/` still sources from `billing.Plan`.

## Consequences

- Editing `/api/platform-admin/pricing/` changes marketing copy, not billing.
  **This is a trap for operators** and the conflict should be resolved in a
  later phase — either by giving `cms.PricingPlan` a display-only projection of
  `billing.Plan`, or by retiring it.
- The seat/storage dimensions advertised by `cms.PricingPlan` remain
  unimplementable until `billing.Plan` grows those limits. Do not surface them.

## Known conflict, recorded not fixed

`seed_billing_plans.py` ships Starter 350 / Business 550 / Professional 890 SAR,
with invoice limits 100 / 500 / 1000. Product proposals circulating alongside
this work quote different figures. Reconciling them is a **commercial**
decision with live-subscriber impact — the renewal price is read from
`plan.price` at payment time — and is explicitly out of scope here.
