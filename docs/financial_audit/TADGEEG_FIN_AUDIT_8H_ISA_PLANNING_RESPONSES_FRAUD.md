# TADGEEG-FIN-AUDIT-8H — ISA 300 Planning · ISA 330 Responses · ISA 240 Fraud (list-builders)

> **Phase type:** Frontend only — surfaces three existing stateless engines. **No model, no migration, no ledger writes.**
> **Date:** 2026-07-27 · **Builds on:** `6e91387` (9D).
> **Honored:** additive · auditor-only · deterministic (no AI) · advisory (not an audit opinion) · nothing persisted.

---

## 1. What was implemented
The last three deferred ISA assessment surfaces, completing the ISA track. Each is a form/list page over a **pre-existing stateless engine** — the reason they were deferred is that their inputs are *lists* (`List[AssessedRisk]`, `List[FraudRiskFactor]`) or a rich context object, so they needed a **list-builder UI** rather than the simple forms of 8E/8F.

- **ISA 300 — Planning** (`/audit/isa/planning/`): an engagement-context form (entity, period, industry, revenue base, listed/first-year/prior-modification/subsidiaries flags, known risk areas one-per-line) → `isa300_planning.build_audit_strategy` + `build_audit_plan`. Renders the overall strategy (scope, timing, direction, materiality benchmark, resourcing, communications) and the detailed procedure plan (nature / timing / extent).
- **ISA 330 — Responses** (`/audit/isa/responses/`): a **list-builder** of assessed risks (name, assertion, inherent/control risk, significant/fraud flags) → `isa330_risk_responses.map_responses`. Renders the responsive-procedure table (nature / timing / extent / staffing / rationale) with significant & fraud risks escalated per §21.
- **ISA 240 — Fraud** (`/audit/isa/fraud/`): a **list-builder** of identified fraud risk factors (name, severity, description, affected assertions, detection signal) → `isa240_fraud_response.assess_fraud_responses`. Renders factor-specific catalogue procedures **and always** the §32 management-override procedures — even with zero factors entered.

## 2. Where the code lives
All three views were appended to `apps/frontend/isa_assessment_views.py` (same module as 8E/8F). Routes added to `apps/frontend/urls.py` (`isa_planning`, `isa_responses`, `isa_fraud`). The ISA sub-nav (`templates/audit/isa/_nav.html`) now lists all six tabs in ISA order: 300 → 315 → 330 → 240 → 570 → 540. Templates: `templates/audit/isa/{planning,responses,fraud}.html`, reusing `_style.html` (extended with list-builder row + result-table styles).

## 3. List-builder mechanism (330 / 240)
Rows use **parallel-array fields** (`risk_name[]`, `assertion[]`, …). A small inline `<template>` + `addRow()` script clones a blank row client-side; a "Remove" button drops one. On POST, `_parse_rows(request, *names)` zips `request.POST.getlist("name[]")` columns into per-row dicts by index. Per-row booleans use `<select>` (yes/no) rather than checkboxes so every row always submits a value and **index alignment is preserved**. Empty-named rows are dropped. Nothing is stored — the engine runs and the result renders in the same response.

## 4. Security & guardrails
Auditor-only (`is_auditor`; junior → 403, anonymous → 302 login). Deterministic engines, **no AI**. Advisory only — every page carries the "Advisory only — not an audit conclusion or opinion" banner. **No ledger writes** (asserted in tests), no model, no migration, nothing persisted.

## 5. Tests
`apps/frontend/tests/test_isa_planning_pages.py` (11): access (login required · junior 403 · auditor render, ×3 pages); ISA 300 strategy+plan build, listed-entity PBT benchmark + EQR; ISA 330 multi-row mapping + high/low extent, significant-risk escalation (§21), empty-rows error; ISA 240 override-always-present (even empty) + factor pulls catalogue procedures; and a no-ledger-writes assertion across all three.

## 6. Intentionally NOT implemented
Persisting a strategy/plan/response-map onto the engagement row (these remain stateless aids, matching 8E/8F) · exporting the plan to PDF · auto-seeding ISA 330 rows from a stored ISA 315 risk register (entered manually for now) · wiring ISA 240 factors from live `fraud_engine` invoice signals. These are additive follow-ups.

## 7. Status
With 8H done, the **entire ISA assessment track (300/315/330/240/570/540) is now surfaced**, and the frontend roadmap (8A–8H, 9A–9D) has no remaining deferred pages. Optional enhancements only from here (PDF exports, cross-module linking, email dispatch, CSV import).
