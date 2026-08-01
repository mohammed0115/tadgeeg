# ADR 0002 — Trial / Paid / Converted are derived, not stored

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 0-A (Admin API Surface Activation & Guardrails)

## Context

Upcoming work (a Trial Users Dashboard) needs to report on "Trial", "Active
Trial", "Expired Trial", "Converted" and "Paid". The obvious-looking move —
adding a status field or a `converted_at` column — would create a second source
of truth next to the subscription lifecycle that already exists and is already
automated.

What exists today, all in `apps/billing`:

- `choices.py::SubscriptionStatus` — `trialing`, `pending_payment`, `active`,
  `expired`, `canceled`, `payment_failed`.
- `choices.py::USABLE_STATUSES` — `{trialing, active}`.
- `models.py::Plan.is_trial` — marks the trial plan.
- `models.py::OrganizationSubscription` — one usable subscription per
  organisation, enforced in `subscription_service.activate_subscription`
  (the partial DB constraint does not apply on MySQL).
- `services/subscription_service.py::create_free_trial` — one trial per
  organisation, ever.
- `tasks.py::expire_subscriptions` — hourly Celery beat job flipping past-due
  rows to `expired` (`settings_canonical.py`).

The lifecycle is complete and running. Only the reporting vocabulary is missing.

## Decision

Define all five as **read-only projections** of `OrganizationSubscription`. Add
no DB field, no status value, no migration.

| Term | Derivation |
|---|---|
| **Trial** | a subscription exists whose `plan.is_trial` is true |
| **Active Trial** | `status == "trialing"` and `starts_at <= now <= ends_at` |
| **Expired Trial** | `plan.is_trial` and `status == "expired"` |
| **Paid** | `status == "active"` on a plan where `is_trial` is false |
| **Converted** | the organisation has had a trial **and** now has (or has had) a paid subscription — i.e. both of the above have been true, ordered in time |

Notes that matter:

- **"Converted" is a relationship between two rows, not a state of one.** That
  is exactly why it must not become a field: a stored flag would need
  maintaining at every activation, cancellation and refund path, and would
  silently drift.
- `expired` is set by the hourly job, so "Expired Trial" is accurate without a
  dashboard needing to compute time itself. A dashboard **may** additionally
  treat `ends_at < now` as expired to close the ≤1-hour lag, but must not write
  the status.
- `activate_subscription` supersedes any prior usable subscription by setting it
  to `canceled`. A trial that was converted therefore ends up `canceled`, not
  `expired`. Any conversion query must look at trial **history**, not the trial's
  current status.

## Consequences

- The Trial Dashboard is a selector/aggregation problem, not a schema problem.
- Conversion rate is computable retroactively over existing data — no backfill.
- Cost: conversion queries join or subquery per organisation. If that becomes
  slow, the correct fix is a **materialised read model**, refreshed from
  subscription rows — never a hand-maintained flag on the write path.

## Out of scope

Whether a self-service registrant may take repeated trials by registering a new
email — each registration creates a fresh `Organization`, and
`create_free_trial` scopes its once-only rule to the organisation. That is a
product decision, recorded here only so it is not mistaken for a reporting bug.
