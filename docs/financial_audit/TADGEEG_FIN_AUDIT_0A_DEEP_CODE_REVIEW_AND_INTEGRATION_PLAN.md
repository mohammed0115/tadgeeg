# TADGEEG-FIN-AUDIT-0A — Deep Code Review & Financial Audit Integration Plan

> **Phase type:** Assessment & planning **only**. No code, models, migrations, or behavior changes were made. This document is the sole deliverable.
> **Date:** 2026-06 · **Scope:** turning the existing Tadgeeg system into a real financial-audit platform by *connecting* existing components, not rebuilding them.
> **Verification:** `python manage.py check` → 0 issues. `python -m compileall apps/audit apps/ledger apps/banking apps/reports apps/rule_engine` → OK. Inventory below carries `file:line` references confirmed against the live tree.

---

## 0. Correction Notice (verified 2026-06-23, direct code read)

A first pass of this report claimed **"no `AuditEngagement` model exists."** That was **wrong** — caused by an exploration that grepped only `apps/audit/models.py` and missed **`apps/audit/engagement_models.py`**. Direct verification:

- **`AuditEngagement` EXISTS** ([apps/audit/engagement_models.py:27](../../apps/audit/engagement_models.py#L27)) with a full **9-state ISA lifecycle**: `acceptance → planning → risk_assessment → fieldwork → review → eqr → reporting → archived (+ withdrawn)`, plus `eqr_partner`, `materiality`, and `risk_assessment` fields. The ISA standard apparatus is also present: `services/isa300_planning.py`, `isa330_risk_responses.py`, `isa240_fraud_response.py`, `going_concern.py`, `materiality.py`, `sampling.py`, `estimates.py`, `risk_decomposition.py`, `rule_dsl.py`.

**The real gap is not a missing spine — it is an _unwired_ spine.** `AuditEngagement` has **no FK to findings, evidence, workpapers, trial balance, or assertions** (verified: no such relations in `engagement_models.py`). The pieces exist as **disconnected islands**; top-down audit flow (TB → FS lines → assertions → planned procedures → execution → misstatement accumulation/SAD → opinion) is **not connected end-to-end**.

Consequently the architecture recommendation shifts from *"build a new spine"* to **"consolidate under `apps/audit` (the richest app) and WIRE the existing engagement to evidence"**, with new persistence limited to what genuinely doesn't exist (client TB/GL import + staging, assertions matrix, SAD accumulation). Sections below are corrected accordingly; the original Option-D framing is narrowed in §6.

Also: **`COMPREHENSIVE_GAP_ANALYSIS.json` (repo root, Mar 2026) is stale and misleading** — its "critical blockers" (ZATCA QR, Benford, IAS 7 cash flow) are now implemented. Archive it; do not build on it.

---

## 1. Executive Summary

Tadgeeg today is **closer to a financial-document analysis platform + risk-rule engine + scattered audit tooling** than to an end-to-end financial-audit system — exactly the framing in the user's plan. The raw material is unusually strong:

- A mature **rule engine** (`apps/rule_engine`, 450+ seeded rules, pipeline, risk + anomaly engines) that already produces `AuditRun → AuditResult → AuditEvidence` with `RiskScoreSummary` and `CrossDocumentLink`.
- A **canonical reporting stack** (`apps/reports`) with bilingual PDF/HTML/Excel, a findings register, KAMs, and a full **ISA 700 opinion service**.
- A real **double-entry ledger** (`apps/ledger`): `Account / JournalEntry (hash-chained) / JournalLine / AccountingPeriod`.
- **Materiality** and **sampling** services already implemented (`apps/audit/services/materiality.py`, `sampling.py`).
- A **bank reconciliation** engine (`apps/banking/reconcile.py`) with a weighted 4-signal matcher.
- A reusable **document-upload substrate** (`apps/documents.Document`: SHA-256, async pipeline, bulk-upload jobs).

**The gap is integration, not capability.** Ten concrete gaps (mapped to the user's plan in §22):

1. **The `AuditEngagement` spine exists but is unwired.** `AuditEngagement` ([apps/audit/engagement_models.py:27](../../apps/audit/engagement_models.py#L27)) has the full 9-state ISA lifecycle, but **no FK to findings/evidence/workpapers/TB/assertions** — so findings, evidence, and the ledger still hang off *documents/organizations*, not the engagement. The fix is **wiring**, not building. (See §0.)
2. **No Trial Balance import.** TB is only *computed* from the internal ledger ([apps/ledger/reports.py:21](../../apps/ledger/reports.py#L21)); there is no client-uploaded TB.
3. **No General Ledger import.** Same — GL is internal-only ([apps/ledger/reports.py:86](../../apps/ledger/reports.py#L86)).
4. **Bank reconciliation is invoice-based, not GL-based** ([apps/banking/reconcile.py:66-177](../../apps/banking/reconcile.py#L66)).
5. **Materiality is not embedded in findings.** The service exists but findings don't carry materiality verdicts.
6. **Sampling is invoice-focused, not risk-based** across GL/bank/VAT strata.
7. **Findings are fragmented across three models** (`audit.AuditFinding`, `auditing.AuditFinding` — a true name collision — and `audit_engine.AuditResult` / `rule_engine.AuditResult`).
8. **No Evidence Request workflow** (PBC list) linking findings → client uploads → workpapers.
9. **Workpapers cover documents only**, not TB/GL/bank/VAT/revenue/expense testing.
10. **Reporting can assert a formal audit opinion automatically** — a legal exposure that must be reworded to "audit readiness / AI-assisted, auditor review required."

**Headline recommendation (corrected — see §0):** **consolidate under `apps/audit`** (it already holds the engagement spine + materiality + sampling + ISA-240/300/330 + going-concern + rule-DSL) and **wire the existing `AuditEngagement` to evidence/findings/TB**. Add *new* persistence only for what genuinely doesn't exist — **client TB/GL import + staging tables, an assertions matrix, and a misstatement/SAD accumulation table** — as modules inside `apps/audit` (or a thin companion app) — while **wrapping** the canonical engines (rule engine, reports/ISA-700, banking matcher) through adapters. **Do not fork** the rule engine or reports; **do not write client uploads into the internal ledger**; **do not delete** any existing finding model.

---

## 2. Current Architecture Findings

| Layer | Canonical home | State |
|---|---|---|
| Rule execution | `apps/rule_engine` | **Strong** — pipeline + 450+ rules + risk/anomaly engines |
| Risk scoring | `apps/rule_engine/risk/risk_engine.py` | **Strong, canonical** (RiskEngine + RiskAggregator) |
| Document upload | `apps/documents.Document` | **Strong** — SHA-256, async, bulk jobs |
| Internal accounting | `apps/ledger` | **Strong** — double-entry, hash-chained, period close |
| Bank reconciliation | `apps/banking` | **Medium** — invoice-based only |
| Materiality | `apps/audit/services/materiality.py` | **Present**, not wired into findings |
| Sampling | `apps/audit/services/sampling.py` | **Present**, invoice-focused |
| Workpapers | `apps/audit.WorkingPaper` (hash-chained) | **Strong but document-scoped** |
| Reporting | `apps/reports` | **Strong, canonical** (ISA-700, PDF/HTML/Excel) |
| Engagement spine | `apps/audit/engagement_models.py:27` | **Present (9-state ISA lifecycle) but UNWIRED** to findings/evidence/TB |
| TB / GL import | — | **Missing** (TB only computed from internal ledger) |
| Assertions matrix / SAD accumulation | partial in services | **Not connected** per-account to the engagement |
| Evidence requests | — | **Missing** |

**Three overlapping "audit" apps** and **two "reporting" apps** are the principal sources of confusion (detailed in §5).

---

## 3. Existing Components Inventory

### 3.1 `apps/rule_engine` — rule execution core (REUSE, do not modify)
| Component | file:line | Purpose | Action |
|---|---|---|---|
| `RuleDefinition` / `RuleDefinitionTranslation` | `models/rule_definition.py:37,128` | Canonical rule registry (bilingual), 450+ seeded | REUSE |
| `AuditRun` / `AuditResult` / `AuditEvidence` | `models/audit_execution.py:8,113,192` | Per-run rule outcomes + granular evidence | REUSE |
| `RiskScoreSummary` | `models/risk.py:8` | Denormalized per-document risk snapshot | REUSE |
| `CrossDocumentLink` | `models/cross_document.py:6` | PO↔Invoice↔GRN, Invoice↔Payment relationships | REUSE (basis for GL-aware rec) |
| `RuleResult` / `NormalizedDocument` | `rules/base.py:55,113` | Dataclass contract for all rules | REUSE (do not change shape) |
| `RiskEngine` / `RiskAggregator` | `risk/risk_engine.py`, `risk/risk_aggregator.py` | Composite weighted risk | REUSE |
| `DocumentAnomalyDetector` | `risk/anomaly_engine.py:71` | z-score/IQR/IsolationForest anomalies | REUSE |

**Risk if modified:** all audits and reports consume these contracts; a shape change is a system-wide break.

### 3.2 `apps/audit` — audit workflow (REUSE services, EXTEND models cautiously)
| Component | file:line | Purpose | Action |
|---|---|---|---|
| `AuditSession` | `models.py:15` | Closest existing "engagement-like" container | EXTEND/WRAP (candidate spine anchor) |
| `AuditFinding` | `models.py:99` | Workflow-level findings | WRAP (one of three finding models) |
| `AuditCase` | `models.py:187` + `CaseComment:318` | ISA 230 case management | REUSE |
| `CustomRuleDefinition` | `models.py:333` | Org custom rules | REUSE |
| `WorkingPaper` (+ `WPSignature:596`, `WPAttachment:645`) | `models.py:463` | **Hash-chained** workpapers (ISA 230) | REUSE, **LEAVE hash/signature logic UNTOUCHED** |
| `services/materiality.py` | — | Benchmark-based materiality | REUSE (wrap into findings) |
| `services/sampling.py` | — | Sampling (seeded, reproducible) | REUSE (extend to risk-based strata) |

### 3.3 `apps/audit_engine` — job orchestration (WRAP)
`AuditJob` / `AuditResult` (`models.py:72`) / `AuditIssue` + `tasks.py`. Mid-tier file-parsing + job lifecycle. **WRAP** behind the engagement; do not make it the canonical findings store.

### 3.4 `apps/auditing` — document AI extraction (WRAP, rename-on-paper)
`AuditFinding` (`models.py:111`) — **name collision** with `audit.AuditFinding`. OCR/AI extraction findings. **WRAP**; in the unification adapter treat it as `ExtractedFinding` conceptually (do **not** rename the class now — that's a later migration).

### 3.5 `apps/ledger` — internal double-entry GL (REUSE; do NOT import client data here)
`Account:46`, `ExchangeRate:112`, `JournalEntry:154` (**HashChainMixin**, idempotency key, period guard), `JournalLine:285`, `AccountingPeriod:333`. Services: `post_entry`, `post_invoice_to_gl`, `post_bank_payment_to_gl`, `close_period`. **Internal books of record — not a staging area.**

### 3.6 `apps/banking` — reconciliation (EXTEND)
`BankConnection:27`, `BankAccount:93`, `BankTransaction:123`, `Reconciliation:169`. Matcher `reconcile.py:66-177` (amount/date/reference/counterparty, 0–100). `run_reconciliation` / `confirm_reconciliation` in `services.py:161,214`. **Invoice-based; missing GL leg.**

### 3.7 `apps/documents` — upload substrate (EXTEND — the import base)
`Document:8-87` (`file_sha256`, `document_type` incl. `BANK_STATEMENT`/`LEDGER`, `processing_status`). `services/integrity.capture_file_hash:31`. `tasks.process_document_task:25` (retry/backoff/atomic). `BulkUploadJob`/`BulkUploadItem` (`bulk_upload_models.py`). **Best pattern to mirror for TB/GL/bank-statement imports.**

### 3.8 `apps/reports` — reporting (CANONICAL, EXTEND)
`Report:5` + services: `ISA700OpinionService` (`services/isa700_opinion_service.py:43`), `InvoiceAuditReportService`, `FindingsService`, `KAMsService`, `GAAPService`, `ReportDataService`. Templates + partials (`_isa700_opinion.html`, `_key_audit_matters.html`, `_failed_rules_table.html`). Async `tasks.py:21,113` with PDF cache.

### 3.9 Supporting
`apps/data_export` (ZIP/CSV exporters), `apps/core_engine` (EngineRouter), `apps/analytics` (`BenfordAnalyzer` — ISA 315 analytical procedure; `ias7_cashflow_service`), `apps/compliance` (`ZATCAQRService`, `ComplianceRule/Violation`), `apps/zatca` (e-invoicing — LEAVE UNTOUCHED), `apps/procurement` (`ThreeWayMatchResult`).

---

## 4. Reusable Components (the "do-not-rebuild" list)

1. **Rule engine + risk + anomaly** (`rule_engine`) — call via adapter.
2. **Materiality service** (`audit/services/materiality.py`).
3. **Sampling service** (`audit/services/sampling.py`).
4. **Hash-chained WorkingPaper** (`audit.WorkingPaper`) — the workpaper substrate.
5. **Reports + ISA-700 + findings/KAMs services + templates** (`apps/reports`).
6. **Document upload + integrity + bulk jobs** (`apps/documents`).
7. **Bank matcher** (`banking/reconcile.py`) — extend, don't replace.
8. **Permission framework** (`core/permissions.py`, `authentication/permissions.py`, `audit_engine/permissions.py`).
9. **Ledger reporting helpers** (`ledger/reports.py`) — pattern for TB/GL math.
10. **CrossDocumentLink** — seed for GL-aware reconciliation relationships.

---

## 5. Duplicate / Overlapping Concepts

| Concept | Definitions found | Canonical | Others → |
|---|---|---|---|
| **AuditFinding** | `audit.AuditFinding` (`:99`), `auditing.AuditFinding` (`:111`) — **true name collision** | Introduce a **unifying adapter** (`FinancialAuditFinding`) | wrap both; deprecate gradually |
| **AuditResult** | `rule_engine.AuditResult` (`audit_execution.py:113`), `audit_engine.AuditResult` (`:72`) | `rule_engine.AuditResult` | `audit_engine` → wrap |
| **AuditEngagement** | `audit.AuditEngagement` (`engagement_models.py:27`) — **exists, 9-state ISA lifecycle** | `audit.AuditEngagement` — **wire it** to findings/evidence/TB | `AuditSession`/`AuditCase` bridge to it |
| **WorkingPaper** | `audit.WorkingPaper` (hash-chained) | `audit.WorkingPaper` | — (single, keep) |
| **Report generator** | `apps/reports` (full), `apps/reporting` (stub) | `apps/reports` | `apps/reporting` → deprecate/wrap |
| **Reconciliation** | `banking.Reconciliation` (bank↔invoice), `erp.ReconciliationDiff`, `procurement.ThreeWayMatchResult` | `banking.Reconciliation` (extend to GL) | others stay domain-specific |
| **Risk scoring** | `rule_engine.RiskEngine` (canonical), `analytics.AuditAnalyticsService` (legacy), `BenfordAnalyzer` (specialized) | `rule_engine.RiskEngine` | Benford = keep as separate procedure; analytics legacy = deprecate |
| **Document upload** | `documents.Document` (canonical), `invoices.Invoice` (domain), `storage_management.AuditFile` | `documents.Document` | others domain-specific |
| **JournalEntry** | `ledger.JournalEntry` (real double-entry), `transactions.JournalEntry` (flat/JSON) | `ledger.JournalEntry` | `transactions` → legacy, do not post audit data into it |
| **VAT check** | `compliance.ZATCAQRService` (QR/TLV), `invoices.Invoice` VAT properties, `rule_engine` VAT rules | rule-engine VAT rules + Invoice math | `ZATCAQRService` = wrap for QR only |

---

## 6. Recommended Canonical Architecture

**Decision (corrected): Option B-primary — consolidate under `apps/audit` and wire the existing spine; add only the genuinely-missing persistence there.**

- **`apps/audit` is the canonical home.** It already owns `AuditEngagement` (the 9-state spine), `WorkingPaper` (hash-chained), `AuditFinding`, `AuditCase`, and the ISA service layer (materiality, sampling, ISA-240/300/330, going-concern, estimates, risk_decomposition, rule_dsl). Building elsewhere would create a *fourth* audit island.
- **Wire, don't rebuild.** Add FKs/links so `AuditEngagement` connects to: findings, evidence requests, trial-balance/GL imports, an assertions matrix, and a misstatement/SAD accumulation table → then to the existing ISA-700 opinion service.
- **New persistence, scoped to what's truly absent:** `TrialBalanceImport/Row`, `GeneralLedgerImport/Row`, `BankStatementImport`, `AccountMapping`, `AssertionAssessment` (per account), `MisstatementAccumulation` (SAD), `EvidenceRequest`. House these as new modules **inside `apps/audit`** (or a thin companion app sharing its migrations cadence) — not as a parallel audit app.
- **Existing engines are wrapped, never forked:** `rule_engine` (rules/risk/anomaly), `apps/reports` (rendering + ISA-700 reworded), `banking/reconcile` (matcher).
- **Internal ledger stays internal.** Client TB/GL land in the new staging tables, never in `ledger_*`.

**Why B over the earlier D ("new `financial_audit` app"):** the spine + ISA services already live in `apps/audit`; a new app would duplicate the engagement noun and deepen the 3-audit-app fragmentation that Phase 1 must *reduce*. A new app is only justified for import/staging if `apps/audit` becomes unwieldy — a judgment call deferred to implementation, not a reason to fork the spine now.

---

## 7. Proposed Integration Backbone (model design only — do NOT create yet)

All models carry `organization` FK (indexed) and follow the existing manual org-scoping pattern (§18). Arrows = FK. **`AuditEngagement` already exists** ([engagement_models.py:27](../../apps/audit/engagement_models.py#L27)); the work is adding the links/children below to it, plus the top-down audit chain **TB → FS lines → assertions → planned procedures → execution → SAD → opinion**.

```
AuditEngagement (EXISTS — wire these children to it)
  ├─ organization, client/period, framework, status (9-state ISA lifecycle), eqr_partner, materiality, risk_assessment
  ├─ (optional) audit_session → audit.AuditSession   # bridge to existing workflow
  │
  ├─ FinancialDataUpload (NEW base; mirrors documents.Document)
  │     kind ∈ {TRIAL_BALANCE, GENERAL_LEDGER, BANK_STATEMENT}
  │     file, file_sha256, status, row_count, validation_errors(JSON)
  │     ├─ TrialBalanceImport → TrialBalanceRow (account_code, debit, credit, py_balance)
  │     ├─ GeneralLedgerImport → GeneralLedgerRow (entry_no, date, account_code, debit, credit, ref, counterparty)
  │     └─ BankStatementImport → BankStatementTransaction (date, amount, direction, ref, counterparty)
  │
  ├─ AccountMapping (NEW)  client account_code → canonical class (asset/liab/equity/rev/exp) + FS line
  │
  ├─ AssertionAssessment (NEW)  per material FS account: existence/completeness/valuation/
  │     rights&obligations/presentation → planned procedures (from materiality + risk services)
  │
  ├─ AuditProcedureRun (NEW)  wraps rule_engine.AuditRun for engagement-level procedures
  │     └─ FinancialAuditFinding (NEW, unifying adapter)
  │           source_kind + source_id (→ AuditResult / audit.AuditFinding / auditing.AuditFinding / TB/GL row)
  │           severity, amount_impact, materiality_verdict(JSON), status, assertion → AssertionAssessment
  │           ├─ EvidenceRequest (NEW)  status, requested_from, due, → uploaded FinancialDataUpload/Document
  │           └─ WorkingPaper (REUSE audit.WorkingPaper via FK/bridge)
  │
  ├─ MisstatementAccumulation / SAD (NEW)  collects corrected+uncorrected misstatements from
  │     findings & sample-error projection → compares to overall/performance materiality → feeds opinion
  │
  ├─ AuditSamplePlan (NEW) → AuditSampleItem (NEW)   wraps audit/services/sampling.py
  │
  ├─ BankReconciliationRun (NEW) → BankReconciliationMatch (NEW)
  │     match across BankStatementTransaction ↔ GL bank-account line ↔ Invoice/Payment
  │     (seeded by banking/reconcile.py + rule_engine.CrossDocumentLink)
  │
  └─ AuditReportPack (NEW)  bundles apps/reports outputs for the engagement
```

**Key design rules:** staging rows are *immutable after validation* (re-import = new upload, old marked superseded); `FinancialAuditFinding` **links to** source objects rather than copying them; `materiality_verdict` is computed at finding creation and stored.

---

## 8. Trial Balance Import Plan

- **Required columns:** `account_code`, `account_name`, (`debit` & `credit`) **or** signed `balance`.
- **Optional:** `prior_year_balance`, `account_type`, `cost_center`, `currency`, `note`.
- **Mapping workflow:** upload → parse → `AccountMapping` UI maps each `account_code` → canonical class + FS line (persist mapping per org for reuse).
- **Validation:** numeric/format checks; unknown columns flagged; duplicate account codes; **Σdebits = Σcredits** (balance check, tolerance e.g. SAR 0.01); every code mapped before "validated".
- **Account classification:** asset/liability/equity/revenue/expense via mapping; flag unclassified.
- **Prior-year comparison:** variance % vs `prior_year_balance`; large swings → candidate findings.
- **Materiality integration:** each line tagged material / immaterial / trivial against overall & performance materiality (§10).
- **Findings generated:** TB out of balance; unmapped/unknown accounts; material YoY variance; negative balances in normally-positive accounts; rounding anomalies.

## 9. General Ledger Import Plan

- **Required:** `entry_no`, `entry_date`, `account_code`, (`debit`/`credit`), `description`.
- **Optional:** `reference`, `counterparty`, `source_module`, `user`, `posting_time`, `cost_center`, `currency`.
- **Mapping workflow:** reuse `AccountMapping` from TB.
- **Validation:** each entry balances; dates within period; account codes exist in TB/mapping; duplicate `entry_no` detection.
- **Link to TB:** GL aggregated by account must reconcile to TB balances (report the deltas).
- **Journal-entry risk scoring (via `rule_engine`):** weekend/holiday/after-hours postings; round-number amounts; manual top-side entries; entries by unexpected users; rare account pairings; just-below-approval-threshold amounts.
- **Suspicious-entry detection:** entries to sensitive accounts (cash, revenue, suspense, related-party); reversing pairs near period-end; one-sided clearing.
- **Period-end testing:** cut-off window analysis; spike in manual entries in last/first days.
- **Sensitive-account testing:** configurable watch-list of account codes → always sampled.
- **Findings:** unbalanced entry; GL-vs-TB delta; high-risk JE; cut-off exception; sensitive-account posting.

## 10. Bank Reconciliation Upgrade Plan

**Current:** `banking/reconcile.py:66-177` matches `BankTransaction` ↔ `Invoice` only; `confirm_reconciliation` does **not** post to GL.

**Target (GL-aware):** `BankStatementTransaction ↔ GL bank-account line ↔ Invoice/Payment (if available)`.

**Matching algorithm (extend the existing weighted matcher):**
- amount match (with tolerance) · date proximity · reference similarity · counterparty similarity · **direction match (debit/credit)** ·
- **many-to-one & one-to-many** (split/aggregate) support ·
- buckets: **unmatched bank items**, **unmatched GL items**, **timing differences** (in-transit), **duplicate/suspicious transfers**.

**Reuse:** keep the 0–100 scoring shape; feed candidate links from `CrossDocumentLink`; persist results in `BankReconciliationRun/Match` (new) — **do not auto-post to the internal ledger** (these are client books under audit, not Tadgeeg's books).

## 11. Materiality Integration Plan

Wrap `apps/audit/services/materiality.py` so **every `FinancialAuditFinding` stores a `materiality_verdict`** containing: `amount_impact`, `benchmark` (e.g. revenue/total assets/PBT), `overall_materiality`, `performance_materiality`, `trivial_threshold`, `is_material` (bool), and a `severity_adjustment` (e.g. immaterial → cap severity; material+critical → escalate). Computed at finding creation; recomputed if benchmark changes (versioned).

## 12. Sampling Integration Plan

Extend `apps/audit/services/sampling.py` from invoice-focused to **risk-based** via `AuditSamplePlan`:
- strata: **GL entries, bank transactions, revenue accounts, expense accounts, VAT items**, payroll & fixed assets (if present);
- selection: **high-value** (top N by amount), **high-risk** (by `rule_engine` score), plus **random/systematic** for coverage;
- keep the existing **fixed seed** for reproducibility; persist each pick as `AuditSampleItem` with selection reason (audit trail).

## 13. Findings Unification Plan

- **Do not delete** `audit.AuditFinding`, `auditing.AuditFinding`, or `audit_engine`/`rule_engine` `AuditResult`.
- Introduce **`FinancialAuditFinding`** as an **adapter/overlay**: it references the source finding (`source_kind`, `source_id`) and adds engagement linkage, materiality verdict, evidence requests, and unified status.
- Existing reports keep reading their current sources; new engagement reports read `FinancialAuditFinding`. Migration is *additive*, reversible, and non-breaking to invoice analysis.

## 14. Evidence Request (PBC) Workflow

- A finding (or planned procedure) **raises an `EvidenceRequest`** (description, account/area, due date, requested_from).
- **Client/uploader** satisfies it by uploading a `FinancialDataUpload`/`Document`; the file links back to the request.
- **Statuses:** `OPEN → SUBMITTED → ACCEPTED / REJECTED (reviewer comment) → CLOSED`.
- Accepted evidence **links to a WorkingPaper**; every transition writes to the existing `AuditLog` (audit trail, §18).

## 15. Workpaper Integration Plan

Reuse hash-chained `audit.WorkingPaper`; add engagement-scoped **templates**: Trial Balance Review · General Ledger Testing · Journal Entry Testing · Bank Reconciliation · VAT Review · Revenue Testing · Purchases/Expenses Testing · Sampling Results · Management Letter Points. Each template = a structured `WorkingPaper` payload + linked findings/evidence/sample items. **Leave the hash-chain/signature logic untouched.**

## 16. Reports Plan

Build each as a new `apps/reports` service + template (reusing `_report_header`, `_failed_rules_table`, `_key_audit_matters`, ISA-700 partial **reworded**): Audit Summary · Trial Balance Review · General Ledger Risk · Bank Reconciliation · VAT Exception · Audit Findings · Evidence Request (PBC) status · Workpaper Export · Management Letter (draft). All bilingual, PDF/HTML/Excel via the existing async + PDF-cache path.

---

## 17. Legal & Wording Safety (priority)

**Finding:** `apps/reports/services/isa700_opinion_service.py` **generates a formal auditor opinion** (`unqualified / qualified / adverse / disclaimer`, with management/auditor responsibility paragraphs and a signature block). Risky strings include the opinion paragraphs and `auditor_signature_block` asserting an ISA-700 opinion produced by the system.

**Recommendation (planning):**
- Reframe system output as **"Audit Readiness Assessment / AI-assisted audit findings"** — explicitly **not** an audit opinion.
- Every report (esp. the ISA-700 section) must carry a banner: **"This is an AI-assisted analysis. The final audit opinion belongs to a licensed auditor. Auditor review required."**
- Keep the ISA-700 *structure* as an **auditor worksheet/draft** the licensed auditor edits and signs — never auto-issued. Replace "we express an opinion" phrasing with "matters for the auditor's consideration."
- This rewording is a **later, explicitly-scoped change** (it touches `apps/reports`, which is out of scope for this assessment phase). Flagged here; not done now.

---

## 18. Permission & Tenant-Isolation Plan

**Mechanism today:** **no** TenantManager/middleware — org-scoping is **manual per view** (`Model.objects.filter(organization=request.user.organization)`), with `.none()` as deny-default. Roles live on `User.Role` ([authentication/models.py:116](../../apps/authentication/models.py#L116)): `admin, cao, senior_auditor, junior_auditor, compliance_officer, finance_manager, external_auditor`; capability map at `:194`.

**Reuse (do not invent a new framework):** `IsAuthenticated` + `RequiresOrganization` ([core/permissions.py](../../core/permissions.py)) + `CanRunAudit` ([audit_engine/permissions.py:7](../../apps/audit_engine/permissions.py#L7)) + `IsOrganizationScopedObject`; function views use `@org_admin_required` / `@org_auditor_required`.

| Action | Roles | Reuse |
|---|---|---|
| Create engagement | admin, cao | `@org_admin_required` / `CanRunAudit` |
| Upload files | admin, cao, senior_auditor | `CanManageFiles` / `@org_auditor_required` |
| Review findings | admin, cao, senior_auditor, compliance_officer | `IsComplianceOrAbove` |
| Approve workpapers | admin, cao | `@org_admin_required` (+ new `CanApproveWorkpapers`) |
| Export reports | admin, cao, senior_auditor | `IsSeniorAuditorOrAbove` |
| View (read-only) | all org members | `IsOrganizationMember` |

**Leak-prevention rules for the new app:** every model has indexed `organization` FK; every `get_queryset` filters by org and returns `.none()` for unaffiliated non-staff; object-level `IsOrganizationScopedObject`; **Celery tasks receive `organization_id` explicitly** (matching `audit/tasks.py`, `audit_engine/tasks.py`) and re-fetch within that scope.

## 19. Performance & File-Size Plan

- Large Excel/CSV → **async** (`process_document_task` pattern; Celery confirmed via `finai_backend/celery.py`).
- **Chunked import** (existing `BulkUploadJob/Item`, iterator chunk_size ~500); per-row validation errors captured in `validation_errors` JSON.
- **Staging tables** absorb raw rows before any posting; progress via job status fields; **delete/rollback** = drop the upload + its staging rows (safe because staging is *not* the ledger).
- Sync threshold for small files (mirror data_export `SOFT_CAP`), async above it; PDF reports use the existing report-PDF cache.

## 20. Testing Plan (per phase)

Model tests (constraints, org FK, immutability) · service tests (TB/GL parse, balance checks, mapping) · upload-validation tests (malformed files, unbalanced TB, unmapped accounts) · mapping tests · **tenant-isolation tests** (extend `tests/test_multitenant_isolation.py`) · permission tests (role matrix) · reconciliation-algorithm tests (amount/date/ref/counterparty/direction, many-to-one) · materiality-integration tests (verdict on findings) · sampling tests (seeded reproducibility, strata coverage) · report/export tests (PDF/Excel render, no formal-opinion wording) · **regression guard**: existing invoice/payment/CRM/billing suites stay green (`apps/platform_admin`, `apps/billing`, `apps/payments`, `apps/invoices`, `apps/reports`).

---

## 21. Phase-by-Phase Implementation Roadmap

This roadmap is **aligned to the verified state** (spine exists; consolidate + wire). It folds in the user's strategic phasing: **Phase 0 verification first**, then architectural consolidation, then backbone wiring (the core), then AI reliability and production-readiness.

| Phase | Deliverable | Touches | Risk |
|---|---|---|---|
| **0 — Verify & baseline** | clean env + `migrate` + run all ~600 tests (record real pass rate) + one true end-to-end run (upload→validate→case→report); **archive `COMPREHENSIVE_GAP_ANALYSIS.json`**; produce a reality-based status matrix | read-only + docs | none |
| **1 — Consolidate (source of truth)** | pick canonical app per domain: audit (merge `auditing`+`audit_engine`), `ledger.JournalEntry` (demote `transactions.JournalEntry` to import-only), `reports` (absorb `reporting`); mark legacy `@deprecated`; one ERD + source-of-truth map | data-migration + deprecation | medium |
| **2 — Wire the backbone (CORE)** | TB import → `ledger` chart; FS lines (BS/IS/CF, reuse IAS 7); `AssertionAssessment` per material account; auto-plan procedures from materiality+risk services; `MisstatementAccumulation` (SAD); connect SAD → `isa700_opinion_service`; link `AuditEngagement` ↔ findings/evidence | extend `apps/audit` (+ reuse documents pattern) | medium |
| **3 — GL import + JE risk** | GL import + staging + GL↔TB reconcile + journal-entry risk via rule-engine adapter | extend `apps/audit` + rule_engine adapter | medium |
| **4 — Findings unification + materiality-in-findings** | `FinancialAuditFinding` adapter + materiality verdict on every finding | `apps/audit` (additive) | medium |
| **5 — Evidence + Workpapers** | EvidenceRequest (PBC) workflow + engagement workpaper templates | `apps/audit` + reuse `WorkingPaper` | low |
| **6 — GL-aware bank rec** | `BankReconciliationRun/Match` + extended matcher (direction, many-to-one) | `apps/audit`/`banking` adapter | medium |
| **7 — Risk-based sampling** | `AuditSamplePlan/Item` over the existing sampling service | `apps/audit` + audit/services | low |
| **8 — AI reliability** | wrap every GPT call in JSON-schema validation + binding confidence thresholds (below → mandatory human review) + store model-version & prompt-hash on outputs | `core/services`, `apps/invoices` | medium |
| **9 — Reports** | engagement report pack (reusing `apps/reports`) | `apps/reports` (additive) | medium |
| **10 — Legal rewording + production** | reword ISA-700 → "audit readiness / auditor review required"; Postgres; upload malware scan, CSP, API rate-limiting; coverage 60%+ | `apps/reports`, settings, infra | **high (legal)** — separate, reviewed change |

Each phase: additive models + new migrations; existing suites (`apps/platform_admin`, `apps/billing`, `apps/payments`, `apps/invoices`, `apps/reports`) must stay green before merge.

---

## 22. Mapping to the User's 10-Point Plan

| User plan | Covered by |
|---|---|
| 1. Connect everything to an Audit Engagement | §6, §7 (spine), Phase 1 |
| 2. Real Trial Balance Import | §8, Phase 2 |
| 3. Real General Ledger Import | §9, Phase 3 |
| 4. Bank Reconciliation → GL-based | §10, Phase 6 |
| 5. Materiality in every finding | §11, Phase 4 |
| 6. Risk-based Sampling | §12, Phase 7 |
| 7. Unify Findings | §13, Phase 4 |
| 8. Build Evidence Requests | §14, Phase 5 |
| 9. Expand Workpapers (accounts/bank/VAT) | §15, Phase 5 |
| 10. Professional reports, no automatic formal opinion | §16, §17, Phases 8–9 |

---

## 23. Exact Recommended Next Prompt

Per the single-decision priority (§6 of the user's plan): **Phase 0 verification + start Phase 2 (Trial Balance import)** — these deliver the biggest move toward a real audit platform because they prove the existing structure runs and connect the system to the *actual* start of an audit (the client trial balance).

> **TADGEEG-FIN-AUDIT-0B — Verify end-to-end, then scaffold Trial Balance import wired to the EXISTING `AuditEngagement`.**
> Part A (verify, read-only): clean venv, `pip install -r requirements.txt`, run `migrate`, run the full ~600-test suite and record the **real** pass rate, then one end-to-end run (upload invoice → validate → AuditCase → report). Archive `COMPREHENSIVE_GAP_ANALYSIS.json`. Produce a reality-based status matrix.
> Part B (Phase 2 start): add `TrialBalanceImport` + `TrialBalanceRow` models **in `apps/audit`** (org-scoped, FK to the existing `AuditEngagement`), an upload+parse service mirroring `documents` (SHA-256, async, per-row validation incl. **Σdebits=Σcredits**), and `AccountMapping` to `ledger` chart codes — into **staging only, never `ledger_*`**. Reuse permissions `IsAuthenticated + RequiresOrganization + CanRunAudit`. **No** changes to payments/CRM/Moyasar/reports/rule_engine contracts. Add model + validation + tenant-isolation + permission tests; run `check`, `makemigrations --check`, new tests; keep `billing/payments/platform_admin` suites green. Commit `Add trial balance import staging wired to engagement`; no push.

---

## 24. What NOT to Change

- **Do not** modify the `rule_engine` contracts (`RuleResult`, `NormalizedDocument`, `AuditRun/AuditResult/AuditEvidence`, `RiskScoreSummary`).
- **Do not** write client-uploaded TB/GL into `ledger_*` tables; use staging in the new app.
- **Do not** touch `JournalEntry` hash-chain, period-close, or `WorkingPaper` signature/hash logic.
- **Do not** delete or rename any existing finding model in place (`audit.AuditFinding`, `auditing.AuditFinding`, `audit_engine.AuditResult`).
- **Do not** auto-issue an audit opinion; rewording of `apps/reports` ISA-700 is a separate, reviewed phase.
- **Do not** change payments, subscriptions, CRM, Moyasar/manual payments, authentication, legal/public pages, ZATCA e-invoicing, or production settings.
- **Do not** create migrations or models in this assessment phase (already honored — none created).
