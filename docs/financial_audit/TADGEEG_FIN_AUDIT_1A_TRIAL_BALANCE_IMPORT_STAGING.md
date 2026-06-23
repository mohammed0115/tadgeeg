# TADGEEG-FIN-AUDIT-1A — Trial Balance Import Staging (linked to existing AuditEngagement)

> **Phase type:** Additive implementation. Models + service + admin + tests + docs. Trial Balance **only**.
> **Date:** 2026-06-23 · **Predecessor:** [0B Runtime Verification](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).
> **Canonical decisions honored:** `apps.audit` is canonical; the existing `apps.audit.engagement_models.AuditEngagement` is reused (no second engagement model); no `apps/financial_audit`; client TB rows go to **staging**, never the ledger.

---

## 1. What was implemented

A first real financial-audit data-intake layer: **client trial-balance upload staging**, linked by FK to the existing `AuditEngagement`.

- Two staging models in `apps/audit/trial_balance_models.py` (re-exported from `apps/audit/models.py` for Django discovery, mirroring how `AuditEngagement` is exported).
- A safe CSV/XLSX parser + validator in `apps/audit/services/trial_balance_import.py` with Arabic/English header aliasing, amount normalisation, row- and import-level validation, balance checking, and a stored summary.
- Read-only, tenant-aware Django admin registration (imported audit evidence cannot be added/edited from admin).
- A full test module (`apps/audit/tests/test_trial_balance_import.py`).
- Migration `apps/audit/migrations/0013_trialbalanceimport_trialbalancerow_and_more.py`.

No UI/API endpoints were added — the project's audit views layer is large and there is no single obvious upload pattern to safely extend in this phase, so per the prompt this phase delivers **models + service + admin + tests + docs**, and the upload/list/detail UI is deferred (see §9).

## 2. Why staging tables (and why the ledger is untouched)

- **`apps.ledger` is internal accounting truth.** `ledger.JournalEntry` is double-entry, `HashChainMixin` (tamper-evident, immutable once posted) and guarded by `AccountingPeriod` open/closed/locked state. A client upload written there would be blocked by period close and would corrupt the platform's own books.
- **A client trial balance is *evidence of what the client reported*** at a point in time. It must be **import-versioned and immutable**: corrections create a *new* import (the old one is `archived`), never an in-place edit — which hash-chained ledger rows forbid mid-workflow anyway.
- **Mapping without contamination:** staging rows carry the client's raw `account_code`; a later phase maps those to `ledger.Account` codes *for classification/reporting only*. **This phase inserts into exactly two tables** (`audit_trial_balance_imports`, `audit_trial_balance_rows`) and is covered by a test asserting **zero** new `ledger.JournalEntry`/`JournalLine` rows.

## 3. Model summary

**`TrialBalanceImport`** (`audit_trial_balance_imports`) — one uploaded file per engagement:
- Links: `engagement` (FK → `AuditEngagement`), `organization` (FK, denormalised; **must equal** `engagement.organization`).
- File: `uploaded_file`, `file_sha256`, `original_filename`, `source_format` (csv/xlsx/xls).
- Period: `period_start`, `period_end`, `fiscal_year`, `currency`.
- Lifecycle `status`: `uploaded → validating → validation_failed | validated → imported → archived`.
- Results: `row_count`, `valid_row_count`, `invalid_row_count`, `total_debit`, `total_credit`, `difference`, `is_balanced`, `column_mapping` (JSON), `validation_summary` (JSON), `errors` (JSON), `warnings` (JSON).
- Trail: `created_by`, `created_at`, `updated_at`, `validated_at`, `archived_at`.
- Indexes: (engagement, -created_at), (organization, status), (fiscal_year). `clean()` rejects cross-tenant.

**`TrialBalanceRow`** (`audit_trial_balance_rows`) — one staged line:
- Links: `import_batch` (FK), `engagement`, `organization` (denormalised from parent).
- Data: `row_number`, `account_code`, `account_name`, `account_type`, `opening_debit/credit`, `period_debit/credit`, `closing_debit/credit`, `net_movement`, `closing_balance`, `currency`.
- Validation: `is_valid`, `validation_errors` (JSON), `raw_data` (JSON — original row preserved).
- Constraint: unique (`import_batch`, `row_number`). Indexes: (import_batch, row_number), (engagement, account_code), (organization, is_valid), (account_type). **No uniqueness on `account_code`** (client exports may repeat accounts).

## 4. Validation rules

- File format must be csv/xlsx/xls — otherwise `validation_failed` + `TrialBalanceImportError`.
- Header detection via alias map → canonical columns; `account_code` is required (its absence is an import-level error); missing `account_name` is a warning.
- Amount normalisation: thousands separators, spaces, currency symbols stripped; `(123)` → `-123`; blanks → 0; non-numeric → row error.
- Amount resolution priority per row: explicit `closing_debit/credit` → `debit/credit` → signed `balance` (positive→debit, negative→credit).
- Row valid iff it has an `account_code` and no non-numeric amounts; invalid rows are stored with `validation_errors` (never dropped). Fully-blank rows are skipped (not counted).
- `period_start <= period_end` (if both supplied).
- Totals: `total_debit`/`total_credit` summed over **valid** rows; `difference = total_debit − total_credit`; `is_balanced = |difference| ≤ 0.01`.
- Status: any import-level error or any invalid row → `validation_failed`; otherwise `validated` (+ `validated_at`).
- `file_sha256` captured on every run (integrity, mirrors the documents app).

## 5. Supported headers (alias map, EN + AR)

| Canonical | Examples |
|---|---|
| account_code | Account Code / Account No / Code / **كود الحساب / رقم الحساب** |
| account_name | Account Name / Description / **اسم الحساب / البيان** |
| account_type | Account Type / Category / **نوع الحساب / التصنيف** |
| debit / credit | Debit, Dr / Credit, Cr / **مدين / دائن** |
| closing_debit / closing_credit | Closing Debit / Closing Credit / **الرصيد المدين / الرصيد الدائن** |
| opening_debit / opening_credit, period_debit / period_credit | Opening/Movement variants / **افتتاحي/حركة** |
| balance | Balance / Closing Balance / **الرصيد / الرصيد الختامي** |
| currency | Currency / Ccy / **العملة** |

Files need not share identical headers; only `account_code` + one amount representation are required.

## 6. Tenant isolation rules

- Every `TrialBalanceImport.organization` **must equal** `engagement.organization` — enforced both in `TrialBalanceImport.clean()` and as a guard at the top of `parse_and_validate()` (raises `ValidationError`).
- `TrialBalanceRow.organization`/`engagement` are set from the parent import, never from the file.
- Admin querysets filter by `request.user.organization` (via `TenantAwareModelAdmin`).
- Tests verify org consistency and cross-tenant denial. (No API added this phase; when added, querysets must be org-scoped and uploads restricted to the user's own engagements.)

## 7. Test results

`pytest apps/audit/tests/test_trial_balance_import.py` → **19 passed** (see §11 of the response). Coverage: model creation linked to engagement; row creation; cross-tenant `clean()` rejection; CSV balanced/unbalanced; Arabic & closing-debit/credit aliases; signed-balance column; blank-row skipping; invalid-row capture; summary totals; period validation; unsupported-format rejection; XLSX parsing; sha256 capture; service-level cross-tenant denial; rows inherit engagement/org; **no writes to ledger**; parse from attached `uploaded_file`. Full `apps/audit` suite re-run to confirm no regression.

## 8. Intentionally NOT implemented (out of scope)

General Ledger import · bank reconciliation · VAT reconciliation · materiality integration · sampling · assertions matrix · SAD/misstatement accumulation · workpaper generation · report packs · AI analysis · ISA-700 wording changes · upload/list/detail UI/API.

## 9. Recommended next phase

**TADGEEG-FIN-AUDIT-1B — Trial Balance upload UI/API + `AccountMapping` to `ledger` chart codes** (org-scoped endpoints reusing `IsAuthenticated + RequiresOrganization + CanRunAudit`; map staged `account_code` → `ledger.Account` for classification only, still no ledger writes). Then **2A — General Ledger import staging** (same staging pattern), followed by wiring findings/materiality to the engagement.

## 10. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no TB rows into ledger tables; no GL import this phase; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no ISA-700 wording change; no production-readiness claim.
