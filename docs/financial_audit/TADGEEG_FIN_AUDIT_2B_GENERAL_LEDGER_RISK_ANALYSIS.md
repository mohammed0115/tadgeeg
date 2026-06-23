# TADGEEG-FIN-AUDIT-2B — General Ledger Risk Analysis & Candidate Findings

> **Phase type:** Additive. Deterministic GL risk analysis over 2A's staged GL → **candidate** findings, linked to the existing `AuditEngagement`. **No** materiality, **no** AI, **no** ledger writes.
> **Date:** 2026-06-23 · **Builds on:** `57f7119` (2A). · **Predecessors:** [2A](TADGEEG_FIN_AUDIT_2A_GENERAL_LEDGER_IMPORT_STAGING.md), [1B](TADGEEG_FIN_AUDIT_1B_TRIAL_BALANCE_UPLOAD_AND_ACCOUNT_MAPPING.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).

---

## 1. What was implemented

A deterministic analysis service that reads staged `GeneralLedgerRow` data for one `GeneralLedgerImport` and produces **candidate risk findings** (`GeneralLedgerRiskFinding`), plus org-scoped DRF endpoints to run/list/view them, admin, tests, docs, and migration `0016`.

## 2. Why these are *candidate* findings

They are **machine-suggested items for an auditor to review, not audit conclusions.** Each carries a `status` (`candidate → accepted / dismissed / needs_evidence / escalated`) and an `evidence_snapshot`. The system supports the auditor; it does not assert wrongdoing. Threshold-avoidance and duplicate rules are explicitly **conservative candidates, not proof of fraud**.

## 3. Model/reuse decision

`apps.audit.AuditFinding` is tied to `audit_session`/`document`/`invoice` (the invoice-validation workflow) with no engagement/GL linkage — overloading it would corrupt its meaning. **Decision: Option B — a new additive `GeneralLedgerRiskFinding`** in `apps/audit/general_ledger_models.py` (re-exported via `models.py`). No existing finding model was changed, renamed, or deleted.

**Model** (`audit_gl_risk_findings`): FK `engagement`/`organization`/`general_ledger_import` + nullable `row`; `journal_number`; `risk_code`/`risk_title`/`risk_description`; `risk_category` (12 choices); `severity` (low/medium/high/critical); `score` 0–100; `amount_impact`; `account_code`/`account_name`/`mapped_category`; `evidence_snapshot` (JSON); `fingerprint` (idempotency); `status` (5 choices); `reviewed_by`/`reviewed_at`/`reviewer_note`; timestamps. Indexes on (engagement,status), (organization,severity), (general_ledger_import,risk_code), account_code, fingerprint. `clean()` rejects org mismatch and a foreign GL import.

## 4. Risk rules implemented (deterministic, A–J)

| Code | Category | Trigger |
|---|---|---|
| GL-RISK-DESC | missing_description | description empty/`<3` chars |
| GL-RISK-UNMAPPED | unmapped_account | row has `account_code` but no `mapped_account` |
| GL-RISK-ROUND | round_amount | `|amount| ≥ 10,000` and divisible by 1,000 |
| GL-RISK-PERIODEND | period_end | date within 7 days before engagement/import `period_end` |
| GL-RISK-WEEKEND | unusual_timing | date falls on Fri/Sat (Saudi weekend); **date-based only — no time invented** |
| GL-RISK-MANUAL | manual_entry | description/source/user contains manual-journal keywords (EN+AR: manual, journal entry, adjustment, تسوية, يدوي, قيد يدوي…) |
| GL-RISK-SENSITIVE | sensitive_account | `mapped_category ∈ {cash_and_bank, revenue, vat_tax, loans, equity}` and `|amount| ≥ 10,000` |
| GL-RISK-THRESHOLD | threshold_avoidance | `|amount|` within 5% **below** 10,000 / 50,000 / 100,000 (candidate only) |
| GL-RISK-DUP | duplicate_entry | same (date, account_code, debit, credit) appears >1 in the import (conservative) |
| GL-RISK-UNBALANCED | unbalanced_journal | `journal_number` group debits ≠ credits (one finding per journal) |

One row may raise several rules → several findings (intended).

## 5. Scoring logic

`score = base(rule) + amount_bump + extra`, capped at 100.
- **base** per rule (e.g. missing_description 20 … unbalanced_journal 70).
- **amount_bump**: `|amount| ≥ 100k → +20`, `≥ 50k → +12`, `≥ 10k → +6`.
- **extra**: +10 for sensitive-account postings and period-end on sensitive accounts; +10 for large (`≥50k`) unbalanced journals.

**Why raw amounts (not materiality):** materiality integration is a later, explicitly-scoped phase. Until then we use fixed raw thresholds (10k/50k/100k), documented here as **temporary**. No `apps.audit.services.materiality` call is made in this phase.

## 6. Severity logic

`0–30 low · 31–60 medium · 61–80 high · 81–100 critical` (from the capped score).

## 7. Idempotency approach

Re-running analysis on the same import:
1. deletes that import's existing **`candidate`** findings,
2. preserves findings a reviewer already acted on (status ≠ candidate) and **does not recreate** them, matched by a deterministic `fingerprint` = `sha256(import_id | risk_code | row_id | journal_number | account_code | amount)`.

So two runs on unchanged data yield the same set, and reviewer decisions are never lost. (Verified by tests.)

## 8. API behavior

Under `/api/v1/audit/` (mirrors 1B/2A):

| Method · Path | Permission | Behavior |
|---|---|---|
| `POST /general-ledger/imports/<uuid>/analyze-risks/` | auditor+ | Org-scoped; runs `analyze_import`; returns summary (`created`, `by_severity`, `by_risk_code`, …). |
| `GET /general-ledger/risk-findings/` | authenticated | Org-scoped list (filters: `?import=`, `?engagement=`, `?severity=`). |
| `GET /general-ledger/risk-findings/<uuid>/` | authenticated | Org-scoped detail. |

Findings are **read-only** over the API in this phase (no review/update endpoint yet) — reviewer status changes can be done in admin; a safe review workflow API is deferred. No hard delete.

## 9. Tenant isolation rules

Analysis/list/detail all resolve via `organization=request.user.organization`; another org's import/finding is **404/empty**, never disclosed. `organization` is set from the engagement, never request input; the service re-asserts org == engagement.org. Tested: cross-org analyze 404, cross-org finding invisible in list.

## 10. Why materiality / AI are intentionally not used yet

- **Materiality:** belongs to a dedicated integration phase; using it now would couple scoring to an unbuilt subsystem. Raw thresholds are a clearly-labelled placeholder.
- **AI:** this phase must be fully deterministic and explainable (every finding traces to a fixed rule + `evidence_snapshot`); AI-assisted analysis is a separate, later concern.

## 11. Test results

`pytest apps/audit/tests/test_general_ledger_risk_analysis.py` — each of the 10 rules, scoring/severity + cap, low-severity case, idempotency (no duplicates) + reviewer-decision preservation, `clean()`/service cross-tenant rejection, API analyze/list/detail org scoping, cross-org analyze denial, org-scoped list, and **no ledger writes**. Full `apps/audit` suite re-run (see response §9).

## 12. Intentionally NOT implemented (out of scope)

Materiality integration · sampling · assertions matrix · SAD/misstatement accumulation · bank reconciliation · VAT reconciliation · workpaper generation · report packs · ISA-700 wording · AI analysis · any posting into the ledger · a review/update API · hard delete.

## 13. Recommended next phase

**TADGEEG-FIN-AUDIT-3A — Materiality integration:** wire `apps.audit.services.materiality` into engagement state, then re-base GL risk severity on materiality (replacing the temporary raw thresholds) and attach a materiality verdict to each candidate finding. Subsequently, a safe finding **review-workflow API** (accept/dismiss/needs-evidence/escalate with reviewer audit trail).

## 14. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no GL rows/findings into ledger tables; no `ledger.JournalEntry` change; no materiality/sampling/SAD/bank-rec/AI this phase; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no ISA-700 wording change; no production-readiness claim.
