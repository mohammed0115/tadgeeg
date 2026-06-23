# TADGEEG-FIN-AUDIT-4A — SAD / Summary of Audit Differences Backbone

> **Phase type:** Additive. An engagement-level Summary of Audit Differences (ISA 450) that accumulates **human-accepted** GL findings and compares them to materiality.
> **Date:** 2026-06-23 · **Builds on:** `a0a274c` (3B). · **Predecessors:** [3B](TADGEEG_FIN_AUDIT_3B_GL_FINDING_REVIEW_WORKFLOW.md), [3A](TADGEEG_FIN_AUDIT_3A_MATERIALITY_INTEGRATION_FOR_GL_FINDINGS.md), [2B](TADGEEG_FIN_AUDIT_2B_GENERAL_LEDGER_RISK_ANALYSIS.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).
> **Honored:** `apps.audit` canonical; reuse existing engagement + materiality resolver; **no** ISA-700 opinion, **no** formal/automatic opinion, **no** AI, **no** ledger writes/adjustment postings.

---

## 1. What was implemented

- `AuditDifferenceSummary` (engagement-level accumulation) + `AuditDifferenceItem` (one line per accepted finding).
- `apps/audit/services/audit_difference_summary.py` — rebuilds the SAD from accepted GL findings and concludes against materiality.
- Org-scoped DRF endpoints (recalculate / view / detail / items), read-only admin, tests, docs, migration `0019`.

## 2. Why SAD uses accepted findings only

A SAD is the auditor's accumulation of **identified misstatements the auditor has accepted as real differences** (ISA 450). A machine candidate is *not* a difference until a human accepts it. So the service includes only `GeneralLedgerRiskFinding.status == accepted`.

## 3. Statuses excluded (and why)

- `candidate` — not yet reviewed by a human.
- `dismissed` — auditor judged it not a real difference.
- `needs_evidence` — unresolved; awaiting support.
- `escalated` — under higher-level review, not concluded.

Only `accepted` represents a concluded, real difference, so only it accumulates.

## 4. Model summary

**`AuditDifferenceSummary`** (`audit_difference_summaries`): FK `engagement`/`organization`; `source_scope` (general_ledger/mixed); `status` (draft/recalculated/reviewed/locked); totals (`total_accepted_findings`, `total_gross_misstatement`, `total_debit_impact`, `total_credit_impact`, `total_absolute_impact`); materiality snapshot (`overall_materiality`, `performance_materiality`, `trivial_threshold`, `materiality_basis`); `exceeds_performance_materiality`/`exceeds_overall_materiality`; `conclusion_status`; `summary_by_category`/`summary_by_account`/`calculation_snapshot` (JSON); `calculated_by/at`, `reviewed_by/at`, `reviewer_note`; timestamps. `clean()` enforces org == engagement.org.

**`AuditDifferenceItem`** (`audit_difference_items`): FK `summary`/`engagement`/`organization`; `source_type` (gl_risk_finding); `gl_finding` FK; account/category/risk fields; `amount_impact`/`debit_impact`/`credit_impact`; `materiality_status`/`materiality_adjusted_severity`; `is_above_trivial`/`is_above_performance_materiality`/`is_above_overall_materiality`; `management_response_status` (not_requested/pending/agreed/disagreed/adjusted/unadjusted); `auditor_conclusion`; `evidence_snapshot`; `created_at`.

## 5. Recalculation logic

`recalculate_for_engagement(engagement, actor=None)`:
- selects accepted GL findings for the engagement+org;
- resolves materiality via the **existing** `gl_finding_materiality.resolve_materiality` (engagement profile);
- sums gross misstatement, absolute impact, and debit/credit impact (debit/credit taken from each finding's linked GL `row` when present);
- rolls up `summary_by_category` and `summary_by_account`;
- concludes (see §6) and sets `exceeds_*` flags;
- keeps **one current summary per engagement** (`get_or_create`), and **deletes+recreates its items** each run → fully idempotent;
- writes a `calculation_snapshot` carrying an explicit *"not a final audit opinion"* note.
- Does **not** modify findings, never uses AI, never writes to the ledger.

## 6. Materiality comparison behavior

Using accumulated `total_absolute_impact` vs the engagement profile:
- no accepted findings → `no_accepted_differences`
- no usable materiality → `not_assessed`
- `≤ trivial_threshold` → `below_trivial`
- `> trivial and < performance` → `below_performance_materiality`
- `≥ performance and < overall` → `above_performance_materiality`
- `≥ overall` → `above_overall_materiality`

Per-item `is_above_*` flags are set against the same thresholds. **Wording is deliberately non-conclusive** — "accepted audit differences / accumulated differences / requires auditor evaluation". The system never states the financial statements are misstated.

## 7. API behavior

Under `/api/v1/audit/`:

| Method · Path | Permission | Behavior |
|---|---|---|
| `POST engagements/<uuid>/sad/recalculate/` | auditor+ | Org-scoped rebuild; returns the summary. |
| `GET engagements/<uuid>/sad/` | authenticated | The engagement's current summary (404 if none yet). |
| `GET sad/<uuid>/` | authenticated | SAD detail (org-scoped). |
| `GET sad/<uuid>/items/` | authenticated | SAD line items (org-scoped, read-only). |

No hard delete; no locking transition in this phase (no safe existing pattern yet); items are read-only.

## 8. Tenant isolation rules

Recalculate/view resolve the engagement scoped to `request.user.organization` (other org → 404); detail/items filter the summary by org. Items inherit org/engagement from the summary; the import entrypoint re-asserts org == engagement.org. Tested: cross-org recalculate 404 (no summary created), cross-org detail 404.

## 9. Why this is not a formal audit opinion

The SAD is an **auditor working schedule** that *accumulates and contextualises* accepted differences against materiality. It produces a `conclusion_status` for the auditor to evaluate — **not** an ISA-700 opinion. No opinion is generated, and the existing ISA-700 wording is untouched. The final opinion remains the licensed auditor's, formed outside this backbone.

## 10. Why the ledger is not modified

Accepted differences here are *proposed/identified* audit differences, not management-approved adjustments. Posting them would alter the client's (or platform's) books — out of scope and unsafe. A test asserts zero new `ledger.Account`/`JournalEntry`/`JournalLine` rows after recalculation.

## 11. Why evidence / workpapers are intentionally not implemented yet

Evidence upload (binding files to `needs_evidence`/findings) and workpaper generation (formal schedules referencing the SAD) are separate phases with their own storage, permissions, and review semantics. This phase delivers only the accumulation backbone so those can build on a stable SAD.

## 12. Test results

`pytest apps/audit/tests/test_audit_difference_summary.py` — accepted-only inclusion, exclusion of candidate/dismissed/needs_evidence/escalated, no-accepted result, all conclusion tiers, not-assessed without materiality, by-category/by-account rollups + exceeds flags, idempotency (single summary, no duplicate items), findings-not-modified, summary `clean()` org check, item creation, API recalculate/view/detail/items org-scoped, cross-org denial, and no ledger writes. Full `apps/audit` suite re-run (see response §9).

## 13. Recommended next phase

**TADGEEG-FIN-AUDIT-4B — SAD management-response & adjustment tracking** (per-item `management_response_status` workflow + proposed-adjustment capture, auditor+, audit-trailed, still no ledger posting), then **TADGEEG-FIN-AUDIT-5A — Opinion worksheet** that consumes the SAD conclusion into an auditor-edited, "auditor review required" worksheet (never an automatic licensed opinion; ISA-700 wording reworked separately).

## 14. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no formal/ISA-700 opinion or wording change; no evidence upload / workpaper this phase; no ledger writes or adjustment postings; no `ledger.JournalEntry` change; no AI; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no production-readiness claim.
