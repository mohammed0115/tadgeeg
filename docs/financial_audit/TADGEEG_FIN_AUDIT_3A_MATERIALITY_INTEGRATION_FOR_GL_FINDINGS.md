# TADGEEG-FIN-AUDIT-3A — Materiality Integration for GL Candidate Findings

> **Phase type:** Additive. Classifies 2B's GL candidate findings against engagement-level materiality (ISA 320/450) while **preserving** the original deterministic score/severity.
> **Date:** 2026-06-23 · **Builds on:** `ad4fb33` (2B). · **Predecessors:** [2B](TADGEEG_FIN_AUDIT_2B_GENERAL_LEDGER_RISK_ANALYSIS.md), [2A](TADGEEG_FIN_AUDIT_2A_GENERAL_LEDGER_IMPORT_STAGING.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).
> **Honored:** `apps.audit` canonical; reuse existing `AuditEngagement` + materiality service; **no** AI, **no** SAD, **no** review workflow, **no** ledger writes, **no** ISA-700 wording change.

---

## 1. What was implemented

A materiality overlay on `GeneralLedgerRiskFinding`: new `materiality_*` fields, a service that classifies each finding's `amount_impact` against engagement materiality and records a *separate* materiality-adjusted score/severity, plus an org-scoped apply endpoint and a `?materiality_status=` filter. Tests, docs, migration `0017`.

## 2. Reused materiality service

`apps.audit.services.materiality.calculate(...)` (ISA 320/450 calculator → `MaterialityResult.to_dict()`) is **reused, not duplicated**. The service can compute a profile from a `benchmark_amount`/`benchmark_key` (e.g. revenue, profit_before_tax) and persist it to the engagement.

## 3. Model/profile decision

**No new profile model.** The existing `AuditEngagement.materiality` JSONField already exists to hold the engagement profile, so this phase reuses it (additive *use*) plus a per-finding `materiality_snapshot`. Materiality assessment fields were added **directly to `GeneralLedgerRiskFinding`** (additive migration). This keeps the schema minimal and avoids a parallel profile table; a versioned snapshot model can be introduced later if audit-trail history is required.

## 4. Materiality fields & statuses (on `GeneralLedgerRiskFinding`)

Added (originals preserved): `materiality_status`, `materiality_basis`, `materiality_overall`, `materiality_performance`, `materiality_trivial_threshold`, `amount_to_overall_materiality_ratio`, `amount_to_performance_materiality_ratio`, `materiality_adjusted_score`, `materiality_adjusted_severity`, `materiality_assessed_at`, `materiality_snapshot`.

`materiality_status` ∈ `not_assessed · trivial · below_performance_materiality · above_performance_materiality · above_overall_materiality · unknown_amount`.

## 5. Service behavior

`apps/audit/services/gl_finding_materiality.py`:
- `apply_materiality_to_import(gl_import, *, materiality=None, benchmark_amount=None, benchmark_key=…, persist_profile=True)`.
- **Materiality source order:** (1) `benchmark_amount` → compute via the materiality service (and persist to `engagement.materiality`); (2) explicit `materiality` dict; (3) existing `engagement.materiality`. If none resolves → all findings `not_assessed`.
- Enforces `import.organization == engagement.organization` (raises `ValidationError`).
- Classifies each finding's `amount_impact`, computes ratios, sets adjusted score/severity, writes a snapshot — via a single `bulk_update`.
- **Idempotent** (recompute overwrites the same deterministic values; no rows created). Finding `status` and original `score`/`severity` are never touched. No AI, no ledger writes.
- Returns `{assessed, materiality_available, by_materiality_status, by_adjusted_severity, import_id}`.

## 6. Classification & adjusted-scoring rules (deterministic)

Classification by `amount_impact`: `≤0 → unknown_amount`; `≤ trivial → trivial`; `< performance → below_performance`; `< overall → above_performance`; `≥ overall → above_overall`. (If only `overall` is supplied, `performance` defaults to 75% and `trivial` to 5%.)

Adjusted score = original score + delta, capped 0–100; adjusted severity derived via the 2B bands (`≤30 low · ≤60 medium · ≤80 high · else critical`):
- `above_overall → +25` · `above_performance → +12` · `below_performance → +0`.
- `trivial →` cap at **medium (≤60)**, **except**: original `critical` is preserved, and sensitive codes (`GL-RISK-SENSITIVE/UNBALANCED/DUP`) keep up to **high (≤80)** — documented exception so a small-amount sensitive item is not understated.
- `not_assessed / unknown_amount →` unchanged (adjusted == original).

Ratios: `amount/overall` and `amount/performance` (4 dp), null when materiality absent.

## 7. Why original score/severity are preserved

The 2B deterministic score/severity is an explainable, amount-agnostic risk signal; materiality is a *separate* lens. Keeping both lets reviewers see the raw risk and its materiality context independently, and lets a later phase re-base or combine them without losing the original. The adjusted values live in clearly separate `materiality_adjusted_*` fields.

## 8. Why findings remain candidates

This phase only *classifies*; it never accepts/dismisses/escalates. `status` is untouched (verified by test, incl. a pre-`accepted` finding). The accept/dismiss/needs-evidence/escalate **review workflow is explicitly out of scope** (next phase). Materiality classification does **not** assert a material misstatement — these are still candidate findings for auditor judgement.

## 9. API behavior

Under `/api/v1/audit/`:

| Method · Path | Permission | Behavior |
|---|---|---|
| `POST /general-ledger/imports/<uuid>/apply-materiality/` | auditor+ | Org-scoped; body optional `materiality` dict or `benchmark_amount`+`benchmark_key`; returns summary. |
| `GET /general-ledger/risk-findings/?materiality_status=…` | authenticated | Existing list, now filterable by materiality status (also `?import=`/`?engagement=`/`?severity=`). |

Materiality results are **read-only** over the API (no review/update). No hard delete.

## 10. Tenant isolation rules

Apply resolves the import via `organization=request.user.organization` (other org → 404, no disclosure); the service re-asserts org == engagement.org. Findings inherit org from their import. Tested: cross-org apply 404 (and that org's findings stay `not_assessed`), org-scoped list filter.

## 11. Why SAD / review workflow are intentionally not implemented yet

- **SAD (misstatement accumulation):** aggregating accepted misstatements vs materiality to inform the opinion is a distinct, later phase; doing it now would require the review workflow and an aggregation model not yet designed.
- **Review workflow:** accept/dismiss/needs-evidence/escalate with a reviewer audit trail is its own phase (permissions, transitions, history). This phase deliberately keeps findings read-only so materiality classification can't be conflated with a review decision.

## 12. Test results

`pytest apps/audit/tests/test_gl_finding_materiality.py` — every classification tier, ratios, adjusted-vs-original separation, trivial caps + critical/sensitive exceptions, benchmark compute + profile persistence, idempotency, candidate-status preservation, cross-tenant rejection (service + API), `?materiality_status` filter, and no ledger writes. Full `apps/audit` suite re-run (see response §9).

## 13. Recommended next phase

**TADGEEG-FIN-AUDIT-3B — GL finding review workflow API** (accept / dismiss / needs-evidence / escalate with `reviewed_by`/`reviewed_at`/`reviewer_note` and an immutable transition audit trail, auditor+ permissions, org-scoped), then **TADGEEG-FIN-AUDIT-4A — SAD / misstatement accumulation** aggregating accepted findings against materiality to feed the (reworded) opinion worksheet.

## 14. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no overwrite of original GL score/severity; no review workflow / SAD / sampling this phase; no AI; no ledger writes; no `ledger.JournalEntry` change; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no ISA-700 wording change; no production-readiness claim.
