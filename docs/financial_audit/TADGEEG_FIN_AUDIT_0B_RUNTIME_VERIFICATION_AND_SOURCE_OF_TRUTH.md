# TADGEEG-FIN-AUDIT-0B — Runtime Verification & Canonical Source-of-Truth Map

> **Phase type:** Verification & planning **only**. No new models, no migrations, no business-code/template/URL/settings changes. This document is the sole deliverable.
> **Date:** 2026-06-23 · **Method:** direct runtime commands against the live tree (not documentation).
> **Predecessor:** corrects/confirms [TADGEEG_FIN_AUDIT_0A](TADGEEG_FIN_AUDIT_0A_DEEP_CODE_REVIEW_AND_INTEGRATION_PLAN.md) §0.

---

## 1. Executive Summary

**`AuditEngagement` is real, migrated, registered, and safe to adopt as the canonical engagement spine.** Verified at runtime: it is defined in `apps/audit/engagement_models.py:27`, imported by `apps/audit/models.py:12` (so Django discovers it), created by migration `audit/0012` (`db_table="audit_engagements"`, applied), and resolvable via `apps.get_model('audit','AuditEngagement')`. It already carries a 9-stage ISA lifecycle, 6 engagement types, 4 opinion types, and an existing FK from `AuditCase.engagement` (`related_name="cases"`).

Runtime health is good: `manage.py check` → **0 issues**; `makemigrations --check` → **No changes**; `compileall` of the six core apps → **OK**; all migrations applied; the `apps/audit` test suite → **93 passed**.

**The gap is wiring, not capability.** `AuditEngagement` is largely *unconnected* to findings, evidence, working papers, trial balance / general ledger, assertions, and misstatement accumulation. Those domains all have strong canonical homes (mapped in §4). Client-uploaded TB/GL do **not** exist yet and must arrive later as **separate, immutable, version-stamped staging tables linked to `AuditEngagement`** — never written into the internal `ledger_*` tables.

**Architecture decision: Option A — adopt `apps/audit` as the canonical financial-audit app and extend it carefully** (with an Option-C escape hatch only if import staging later makes `apps/audit` unwieldy). **Do not** create a second `AuditEngagement`; **do not** create `apps/financial_audit` now.

**Next phase: TADGEEG-FIN-AUDIT-1A — Trial Balance Import Staging linked to the existing `AuditEngagement`** (verification and TB import are intentionally *not* combined).

---

## 2. Runtime Verification Results

| Command | Result |
|---|---|
| `git status --short` | clean except untracked `docs/financial_audit/` |
| `python manage.py check` | **System check identified no issues (0 silenced)** ✅ |
| `apps.get_model('audit','AuditEngagement')` | `<class 'apps.audit.engagement_models.AuditEngagement'>`, table `audit_engagements` ✅ |
| `showmigrations audit` | 12 applied, 0 unapplied ✅ |
| `showmigrations ledger` | 3 applied ✅ |
| `showmigrations banking` | 1 applied ✅ |
| `showmigrations reports` | 1 applied ✅ |
| `showmigrations invoices` | 15 applied ✅ |
| `makemigrations --check --dry-run audit ledger banking reports` | **No changes detected** ✅ (models in sync with migrations) |
| `compileall apps/{audit,ledger,banking,reports,rule_engine,invoices}` | **OK** ✅ |
| Canonical services import (materiality, sampling, isa300, isa330, going_concern, isa700_opinion, banking.reconcile) | **all OK** ✅ |
| `pytest apps/audit/tests/` | **93 passed in 186s** ✅ |

**Honest caveats (no production-readiness claim):** these checks prove the audit subsystem *loads, migrates, and unit-tests green*. They do **not** constitute a full end-to-end financial-audit run (TB→opinion), which cannot be executed today because client TB/GL import does not exist (§10). The repo default DB is the dev configuration; a Postgres + load run is part of a later production phase, not asserted here.

---

## 3. AuditEngagement Verification (direct answers)

- **Does it exist?** Yes.
- **What file defines it?** `apps/audit/engagement_models.py:27` (`class AuditEngagement(models.Model)`).
- **Included in Django model discovery?** Yes — re-exported via `from apps.audit.engagement_models import AuditEngagement  # noqa: F401` at `apps/audit/models.py:12`.
- **Migrations?** Yes — `CreateModel name='AuditEngagement'` in `apps/audit/migrations/0012_alter_auditcase_deleted_at_and_more.py:34`, `db_table='audit_engagements'`; applied (showmigrations audit = 12/12).
- **Accessible from the app registry?** Yes — `apps.get_model('audit','AuditEngagement')` resolves; table `audit_engagements`.
- **Used anywhere?** Linked from `AuditCase.engagement` FK (`apps/audit/models.py:269`, `related_name="cases"`, nullable "optional for legacy cases"). Referenced by migration `0012`. **Not** yet referenced by views/urls/services/admin → defined-but-unwired.
- **Fields/statuses/phases present:**
  - **Stage** (9): acceptance, planning, risk_assessment, fieldwork, review, eqr, reporting, archived, withdrawn.
  - **EngagementType** (6): fs (ISA), ia (IIA IPPF), review (ISRE 2400), aup (ISRS 4400), comp, fraud.
  - **OpinionType** (4): unmodified, qualified, adverse, disclaimer.
  - **Fields:** organization, engagement_code, title, description, engagement_type, period_start/end, fieldwork_start/end, expected_report_date, archival_due_date, stage, accepted_at, locked_at, engagement_partner, engagement_manager, eqr_partner, strategy, plan_procedures, materiality, risk_assessment, opinion_type, opinion_signed_at, opinion_signed_by, kams_summary, created_by, created_at, updated_at.
- **Safe to adopt as canonical spine?** **Yes.** It is migrated, registered, org-scoped, ISA-shaped, already linked to `AuditCase`, and the suite is green. No blocker.
- **Gaps before end-to-end use:** no FK to findings / evidence / working papers / TB / GL / assertions / SAD; no client TB/GL import; no engagement-scoped views/serializers/admin; opinion not yet driven by a misstatement-accumulation (SAD) feed.

---

## 4. Canonical Source-of-Truth Map

| Domain | **Canonical** | Wrap (adapter) | Leave untouched | Deprecate later | Why |
|---|---|---|---|---|---|
| **A. Engagement** | `audit.AuditEngagement` (`engagement_models.py:27`) | — | `AuditCase`/`AuditSession` (bridge *to* it) | — | Migrated, registered, ISA 9-stage; already FK'd from AuditCase |
| **B. Findings** | `audit.AuditFinding` (`models.py:99`) as the engagement-facing record | `auditing.AuditFinding` (`:111`), `rule_engine.AuditResult`, `audit_engine.AuditResult` via a `FinancialAuditFinding` adapter | rule_engine result contracts | `auditing`/`audit_engine` finding stores (gradually) | One engagement-facing finding; never copy source data, link to it |
| **C. Working papers** | `audit.WorkingPaper` (`models.py:463`, hash-chained + `WPSignature`/`WPAttachment`) | — | **hash-chain & signature logic (do not touch)** | — | Only workpaper model; ISA 230 tamper-evidence |
| **D. Ledger / journal** | `ledger.JournalEntry` (double-entry, HashChainMixin, period close) | `transactions.JournalEntry` → import-only | ledger posting/period/void logic | `transactions.JournalEntry` as an accounting source | Real double-entry + audit trail; the other is flat/legacy |
| **E. Trial Balance** | `ledger.reports.trial_balance()` (`reports.py:21`) for **internal** TB | — | — | — | **Client-uploaded TB staging is MISSING** → build in 1A, linked to engagement |
| **F. General Ledger** | `ledger.reports.general_ledger()` (`reports.py:86`) for **internal** GL | — | — | — | **Client-uploaded GL staging is MISSING** → later phase |
| **G. Bank reconciliation** | `banking` models + `banking/reconcile.py` matcher | extend to GL-aware (new run/match) | scoring shape | — | Currently invoice-based (§8); upgrade, don't replace |
| **H. Reporting** | `apps/reports` (ISA-700, KAMs, PDF/HTML/Excel) | `apps/reporting` (stub) | report templates | `apps/reporting` | Full-featured vs metadata stub |
| **I. Materiality** | `audit.services.materiality` | — | — | — | Single implementation; ISA 320/450 |
| **J. Sampling** | `audit.services.sampling` | — | — | — | Single implementation; MUS/random/systematic |
| **K. Rule / risk engine** | `apps/rule_engine` (rules + RiskEngine + anomaly) | `audit_engine` orchestration; `analytics.BenfordAnalyzer` as a separate procedure | rule/result contracts | `analytics.AuditAnalyticsService` (legacy) | 450+ rules + canonical risk; others overlap |

---

## 5. Duplicate / Overlapping Components (verified)

- **Findings ×3:** `audit.AuditFinding` (`models.py:99`), `auditing.AuditFinding` (`models.py:111`) — true class-name collision — plus `rule_engine.AuditResult` / `audit_engine.AuditResult`. → unify via an additive `FinancialAuditFinding` adapter; **delete nothing now**.
- **JournalEntry ×2:** `ledger.JournalEntry` (canonical) vs `transactions.JournalEntry` (legacy/flat). → ledger is source of truth; transactions becomes import-only.
- **Reporting ×2:** `apps/reports` (canonical) vs `apps/reporting` (stub). → consolidate into reports.
- **Three audit apps:** `audit` (richest — engagement, workpapers, ISA services), `auditing` (document AI extraction), `audit_engine` (job orchestration). → `audit` canonical; wrap the other two.
- **Risk scoring:** `rule_engine.RiskEngine` (canonical) vs `analytics.AuditAnalyticsService` (legacy) vs `BenfordAnalyzer` (keep as a distinct ISA 315 analytical procedure).

---

## 6. Final Architecture Recommendation

**Option A — `apps/audit` is the canonical financial-audit app; extend it carefully.**

- `apps/audit` already owns the engagement spine, hash-chained working papers, findings, cases, and the full ISA service layer (materiality, sampling, ISA-240/300/330, going-concern, estimates, risk_decomposition, rule_dsl). Adopting it avoids creating a *fourth* audit island.
- New persistence that genuinely doesn't exist (TB/GL/bank import staging, `AccountMapping`, `AssertionAssessment`, `MisstatementAccumulation`/SAD, `EvidenceRequest`) is added **inside `apps/audit`**, each with an FK to `AuditEngagement`.
- Existing engines are **wrapped, never forked**: `rule_engine`, `apps/reports` (ISA-700, reworded later), `banking/reconcile`.

**Option-C escape hatch (documented, not chosen):** *only* if TB/GL import staging later makes `apps/audit` unwieldy may a thin `apps/financial_audit` host **import/adapter code** — but the engagement spine stays canonical in `apps/audit`. **Do not** create `apps/financial_audit` now; if a future phase proposes it, it must stop and justify it explicitly.

**Hard rule honored:** no second `AuditEngagement` — the existing one is usable.

---

## 7. Engagement Wiring Plan (plan only — do not implement)

Add FKs to `AuditEngagement` (all org-scoped, indexed) so the top-down audit flow connects end-to-end:

```
AuditEngagement (EXISTS)
 ├─ FinancialDataUpload (NEW)  kind ∈ {TRIAL_BALANCE, GENERAL_LEDGER, BANK_STATEMENT}
 │    ├─ TrialBalanceImport → TrialBalanceRow      (→ AccountMapping → ledger.Account codes)
 │    ├─ GeneralLedgerImport → GeneralLedgerRow
 │    └─ BankStatementImport → BankStatementTransaction
 ├─ materiality (FIELD exists) ← audit.services.materiality
 ├─ AssertionAssessment (NEW)  per material FS account → planned procedures (materiality + risk)
 ├─ AuditSamplePlan/Item (NEW) ← audit.services.sampling
 ├─ FinancialAuditFinding (NEW adapter) → links to audit/auditing/rule_engine sources; carries materiality verdict + assertion
 │    ├─ EvidenceRequest (NEW)  finding → requested file → uploaded FinancialDataUpload/Document
 │    └─ WorkingPaper (REUSE audit.WorkingPaper via FK)
 ├─ MisstatementAccumulation / SAD (NEW)  findings + sample-error projection → vs materiality
 ├─ Reports (REUSE apps/reports)  engagement report pack
 ├─ Auditor review (REUSE existing review/EQR stages on the engagement)
 └─ Management letter (REUSE KAMs/Findings services → report)
```

Flow: **TB → FS lines (reuse IAS 7) → assertions → planned procedures → execution (samples/tests) → SAD → opinion** (drive `isa700_opinion_service` from SAD). Auditor review uses the existing `review`/`eqr` stages.

---

## 8. TB / GL Staging Recommendation

**Use separate, immutable, version-stamped staging/import tables for client-uploaded TB & GL, linked to `AuditEngagement` — never write into `ledger_*`.** Reasons (code-evidenced):

- **`ledger` is internal accounting truth, not a staging area:** `ledger.JournalEntry` is double-entry, **HashChainMixin** (tamper-evident, immutable once posted), guarded by `AccountingPeriod` open/closed/locked state. Client uploads would be blocked by period close and would pollute the platform's own books.
- **Audit data must be immutable & import-versioned:** a client TB is *evidence of what the client reported*; corrections must produce a new versioned import (old marked superseded), not in-place edits — exactly what hash-chained ledger entries forbid mid-workflow.
- **Mapping without contamination:** staging rows carry the client's raw `account_code`; an `AccountMapping` table maps each to a canonical `ledger.Account` code (chart of accounts) **for classification/reporting only**. The ledger chart is read as a reference; no rows are inserted into `ledger_*`.

Mirror the proven `apps/documents` upload pattern (SHA-256 integrity, async parse, bulk-job chunking, per-row validation incl. Σdebits = Σcredits).

---

## 9. Bank Reconciliation Upgrade Recommendation

**Current (verified):** `banking/services.py:161 run_reconciliation()` matches *recent debit `BankTransaction`s to outstanding `Invoice`s* (imports `apps.invoices.models.Invoice` at `:169`) via the weighted scorer in `reconcile.py` (amount/date/reference/counterparty, 0–100). It is **invoice-based**; `confirm_reconciliation` does **not** post a GL leg.

**Missing for GL-aware reconciliation:** a GL bank-account line to match against, direction (debit/credit) matching, split/aggregate (many-to-one / one-to-many), and explicit unmatched/timing/duplicate buckets.

**Target (later phase):** `BankStatementTransaction ↔ GL bank-account line ↔ Invoice/Payment (if available)`, persisted in new `BankReconciliationRun/Match` tables (engagement-scoped). Matching dimensions: **amount · date proximity · reference similarity · counterparty similarity · direction · many-to-one · one-to-many · unmatched bank items · unmatched GL items · timing differences · suspected duplicates.** Reuse the existing 0–100 scorer shape; seed candidate links from `rule_engine.CrossDocumentLink`. **Do not auto-post to the internal ledger** (these are the client's books under audit).

---

## 10. Legal & Report Wording Safety Review (document only — no change this phase)

**Confirmed risk:** `apps/reports/services/isa700_opinion_service.py` emits a **formal auditor opinion**, verbatim:
- `:447` — *"In our opinion, the financial statements and audited invoices present fairly, ..."* (unmodified)
- `:457-458` — *"In our opinion, except for the matters ... present fairly, in all material respects, ..."* (qualified)
- `:468-469` — *"In our opinion, due to the significance ... do not present fairly in all material respects ..."* (adverse)

Exposed in templates: `templates/reports/partials/_isa700_opinion.html`, `executive_report.html`, `invoice_audit_report.html`, `index.html`.

**Recommended rewording (later, reviewed phase):** reframe as **"Audit Readiness Assessment / AI-assisted audit findings"**; replace "In our opinion … present fairly" with "matters for the auditor's consideration"; add a banner on every report: **"This is an AI-assisted analysis. The final opinion must be approved by a licensed auditor. The system supports, but does not replace, the auditor — auditor review required."** Keep the ISA-700 structure as an auditor *worksheet/draft*, never auto-issued. **Not changed in 0B.**

---

## 11. End-to-End Verification Plan (smallest real scenario, for a later phase)

| Step | Exists today? |
|---|---|
| Create/choose an engagement | ✅ `AuditEngagement` (needs views/serializers) |
| Import Trial Balance | ❌ build in 1A |
| Import General Ledger | ❌ later phase |
| Import Bank Statement | ⚠️ `banking` ingests statements; not engagement-linked |
| Run validation | ✅ `rule_engine` (needs TB/GL adapters) |
| Run materiality | ✅ `audit.services.materiality` (needs finding wiring) |
| Run risk checks | ✅ `rule_engine.RiskEngine` |
| Create findings | ✅ models exist (need `FinancialAuditFinding` adapter) |
| Request evidence | ❌ `EvidenceRequest` to build |
| Link to working paper | ✅ `audit.WorkingPaper` (need engagement FK) |
| Auditor review | ✅ engagement `review`/`eqr` stages |
| Export audit-readiness report | ✅ `apps/reports` (after wording rework) |

**Verdict:** the engine and reporting ends exist; the *connective tissue* (TB/GL import, assertions, SAD, evidence requests, engagement FKs) is the build. No end-to-end run is possible until TB import (1A) lands — so **no production-readiness is claimed**.

---

## 12. Testing Roadmap (minimum before implementation)

1. **App-registry test** — `apps.get_model('audit','AuditEngagement')` resolves; table = `audit_engagements`.
2. **Migration/model-availability test** — `makemigrations --check` clean; engagement fields/stages present.
3. **Source-of-truth regression test** — assert canonical models importable; legacy ones not silently re-canonicalized.
4. **Organization-isolation tests** — engagement & future staging querysets filter by org, `.none()` for outsiders.
5. **Permission tests** — create-engagement (admin/cao), upload (auditor+), review (compliance+), export (senior+).
6. **Trial Balance staging tests** — parse, Σdebits=Σcredits, unmapped-account flagging, version supersede.
7. **General Ledger staging tests** — entry balance, GL↔TB reconciliation deltas, duplicate entry_no.
8. **Bank reconciliation algorithm tests** — amount/date/ref/counterparty/direction, many-to-one, unmatched buckets.
9. **Findings adapter tests** — `FinancialAuditFinding` links to each source without copying data.
10. **Materiality integration tests** — every finding carries a materiality verdict.
11. **Sampling integration tests** — seeded reproducibility; strata coverage.
12. **Report wording-safety tests** — rendered reports do **not** assert a formal/licensed opinion; carry the auditor-review banner.

Plus a **regression guard**: `apps/billing`, `apps/payments`, `apps/platform_admin`, `apps/invoices`, `apps/reports` suites stay green.

---

## 13. Recommended Next Implementation Phase

**TADGEEG-FIN-AUDIT-1A — Trial Balance Import Staging linked to the existing `AuditEngagement`.**
Add `TrialBalanceImport` + `TrialBalanceRow` (org-scoped, FK to `AuditEngagement`) **inside `apps/audit`**, an upload+parse service mirroring `apps/documents` (SHA-256, async, per-row validation incl. Σdebits=Σcredits, version supersede), and `AccountMapping` → `ledger.Account` codes — **staging only, never `ledger_*`**. Reuse permissions `IsAuthenticated + RequiresOrganization + CanRunAudit`. No payments/CRM/Moyasar/reports/rule_engine-contract changes. Tests per §12 (1–6); run `check`, `makemigrations --check`, new tests; keep billing/payments/platform_admin green. Commit; no push. **(Verification 0B and TB import 1A are deliberately separate phases.)**

---

## 14. What NOT to Change

- **Do not** create a second `AuditEngagement` — the existing one is canonical and usable.
- **Do not** create `apps/financial_audit` now (Option A chosen). A future phase may only host *import/adapter* code there, and must stop to justify it.
- **Do not** create migrations or models in this phase (none created).
- **Do not** write client TB/GL into `ledger_*`; use separate immutable staging.
- **Do not** touch the `WorkingPaper`/`JournalEntry` hash-chain, signatures, or period-close logic.
- **Do not** delete or rename any `audit`/`auditing`/`audit_engine`/`reporting` model.
- **Do not** reword the ISA-700 output in this phase (documented only).
- **Do not** change payments, subscriptions, CRM, Moyasar/manual payments, authentication, legal/public pages, templates, URLs, settings, secrets, or deployment files.
- **Do not** claim production readiness — no end-to-end run has been performed.

---

## 15. Commands Run & Results

| # | Command | Result |
|---|---|---|
| 1 | `git status --short` | clean (only untracked `docs/financial_audit/`) |
| 2 | `python manage.py check` | 0 issues ✅ |
| 3 | `apps.get_model('audit','AuditEngagement')` | resolves; table `audit_engagements`; 30 fields ✅ |
| 4 | `showmigrations audit/ledger/banking/reports/invoices` | all applied (12/3/1/1/15), 0 unapplied ✅ |
| 5 | `makemigrations --check --dry-run audit ledger banking reports` | No changes detected ✅ |
| 6 | `compileall apps/{audit,ledger,banking,reports,rule_engine,invoices}` | OK ✅ |
| 7 | import check of 7 canonical services | all OK ✅ |
| 8 | `pytest apps/audit/tests/` | **93 passed** (186s) ✅ |
| 9 | grep ISA-700 wording / TB-GL / banking reconcile | risks & gaps confirmed (§8–§10) |

**No command failed.** No environment/dependency blocker encountered.
