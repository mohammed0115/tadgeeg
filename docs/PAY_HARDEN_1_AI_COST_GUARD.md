# PAY-HARDEN-1 — AI Cost-Access Guard

## What
A single guard, `apps/billing/ai_access.py`, that every code path must call
**before** spending money on OpenAI:

- `check_ai_access(org, *, projected_tokens=0) -> AIAccessDecision` — never raises.
- `ai_access_allowed(org, ...) -> bool` — for loops / background tasks.
- `require_ai_access(org, ...)` — raises `AIAccessDenied` (for services).
- `ai_access_response_or_none(org, ...)` — returns a DRF `Response` (402/403/429) or `None` (for views).

## Why middleware alone is not enough
`SubscriptionRequiredMiddleware` blocks unsubscribed/suspended org users at the
HTTP edge, but it does **not** cover:

- background tasks / Celery jobs / management commands (no `request`);
- an **ACTIVE** subscription that has exhausted its **daily AI token budget**
  (middleware only checks "is there a usable subscription");
- a deployment running with `SUBSCRIPTION_REQUIRED=False` (migration window).

So the guard is **defense in depth**, enforced at the call site regardless of
middleware.

## Behavior on denial
| State | Result |
|---|---|
| active + token budget OK | allowed |
| no subscription | denied · 402 `no_subscription` |
| expired subscription | denied · 402 `subscription_expired` |
| organization suspended (`is_active=False`) | denied · 403 `organization_suspended` |
| daily AI token budget exhausted | denied · 429 `ai_budget_exhausted` |
| invoice quota exhausted (active sub) | **allowed** — AI meters on token budget, not invoice quota |

HTTP returns the status above (never 500, never reaches OpenAI). Background /
service paths skip the AI call and fall back to deterministic output.

## Two different meters
- **invoice quota** = per-subscription invoice-audit units, consumed by the
  audit pipeline via `billing.quota_gate`. Not touched by this guard.
- **AI token budget** = per-org daily OpenAI token cap
  (`core/services/ai_budget.py`, `OPENAI_DAILY_TOKEN_CAP_PER_ORG`). This is the
  cost ceiling for all AI features and what the guard enforces.

## Settings switches
- `SUBSCRIPTION_REQUIRED` (default True) — the subscription wall (middleware + guard's subscription check).
- `AI_ACCESS_GUARD_ENABLED` (default True) — **independent** master switch for this guard. Kept separate so relaxing `SUBSCRIPTION_REQUIRED` during a migration window does **not** silently disable AI-spend protection. Suspension and token-budget stay enforced whenever the guard is enabled, even with `SUBSCRIPTION_REQUIRED=False`.

## Guarded call sites
- HTTP: analytics (anomaly, fraud, insights, cash-flow), reports (audit + invoice-audit narrative), assistant chat.
- Background / service: nightly anomaly scan, audit session summaries, `ai_narrative_service.build_ai_narrative` (optional `organization=`), `document_report_service`.

## Release note
Moyasar UAT (sandbox) is unblocked: the payment path was already sound and these
AI cost gaps are orthogonal to payment correctness. The guard closes the High AI
cost-leak risks raised in PAY-AUDIT-1 before broad AI exposure.
