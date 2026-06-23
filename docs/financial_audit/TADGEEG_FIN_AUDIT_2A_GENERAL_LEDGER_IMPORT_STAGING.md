# TADGEEG-FIN-AUDIT-2A — General Ledger Import Staging

> **Phase type:** Additive. GL staging models + parser/validation service + org-scoped DRF API + admin + tests + docs. **GL intake only.**
> **Date:** 2026-06-23 · **Builds on:** `1cba09d` (1B). · **Predecessors:** [1A](TADGEEG_FIN_AUDIT_1A_TRIAL_BALANCE_IMPORT_STAGING.md), [1B](TADGEEG_FIN_AUDIT_1B_TRIAL_BALANCE_UPLOAD_AND_ACCOUNT_MAPPING.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).
> **Honored:** `apps.audit` canonical; reuse existing `AuditEngagement`, `TrialBalanceImport`, `AccountMapping`; **no** ledger writes; no second engagement; no `apps/financial_audit`.

---

## 1. What was implemented

Client General-Ledger intake as **staging**, linked to the existing `AuditEngagement` and (optionally) to a `TrialBalanceImport`:

1. `GeneralLedgerImport` + `GeneralLedgerRow` (in `apps/audit/general_ledger_models.py`, re-exported from `models.py`).
2. A safe CSV/XLSX parser/validator (`apps/audit/services/general_ledger_import.py`) with AR/EN header aliasing, amount + date normalisation, **per-journal balancing**, `AccountMapping` linking (classification only), and **Trial Balance alignment** checks.
3. Org-scoped DRF upload/list/detail endpoints (same safe pattern as 1B).
4. Read-focused, tenant-aware admin; tests; migration `0015`.

## 2. Why staging tables (and why the ledger is untouched)

Same rationale as 1A, carried forward: `apps.ledger` is internal, hash-chained, period-locked accounting truth; a client GL is **evidence under audit** and must be immutable/version-stamped. GL rows are inserted into exactly two tables (`audit_general_ledger_imports`, `audit_general_ledger_rows`); a test asserts **zero** new `ledger.Account`/`JournalEntry`/`JournalLine` rows after parsing. No journal entries are posted.

## 3. Model summary

**`GeneralLedgerImport`** (`audit_general_ledger_imports`): FK `engagement` + `organization` (must match) + nullable `related_trial_balance_import` (must be same engagement/org); `uploaded_file`/`file_sha256`/`original_filename`/`source_format`; period/fiscal/currency; `status` (uploaded→validating→validation_failed|validated→imported→archived); counts incl. `journal_count`, `balanced_journal_count`, `unbalanced_journal_count`; `total_debit`/`total_credit`/`difference`/`is_balanced`; `column_mapping`/`validation_summary`/`errors`/`warnings`; trail. Indexes: (engagement,-created_at), (organization,status), fiscal_year, period_start, period_end. `clean()` rejects org mismatch **and** a foreign TB link.

**`GeneralLedgerRow`** (`audit_general_ledger_rows`): FK `import_batch`/`engagement`/`organization`; `row_number`, `journal_number`, `line_number`, `transaction_date`, `posting_date`, `account_code`, `account_name`, nullable `mapped_account` (FK→`AccountMapping`, SET_NULL, **classification only**), `debit`/`credit`/`signed_amount`/`currency`, `description`, `document_number`, `reference`, `counterparty`, `cost_center`, `department`, `entered_by`, `source_system`, `is_valid`, `validation_errors`, `raw_data`. Unique (`import_batch`,`row_number`); indexes on journal_number, account_code, transaction_date, posting_date, mapped_account, is_valid. **No** uniqueness on journal_number/account_code (GL repeats them across lines).

## 4. Parser / validation rules

- Format must be csv/xlsx/xls (else `validation_failed` + error).
- Required: `account_code`; one amount representation (`debit`/`credit` **or** signed `amount`). Missing dates → warning.
- Amount normalisation (separators, currency symbols, `(123)`→negative); non-numeric → row error. Signed `amount` ≥0 → debit, <0 → credit.
- Date normalisation across common EN/intl formats; present-but-unparseable → row error.
- Row valid iff it has an `account_code` and no numeric/date parse errors; invalid rows stored with `validation_errors` (never dropped); blank rows skipped.
- `period_start ≤ period_end` (else hard error).
- Batch totals over **valid** rows; `is_balanced = |Σdebit − Σcredit| ≤ 0.01`.
- **Per-journal balancing:** rows grouped by `journal_number` (when present); each journal's debit/credit compared within tolerance → `balanced/unbalanced_journal_count`. Journal imbalance and GL-level imbalance are **warnings**, not hard failures (an auditor wants to *see* the imbalance).
- Status: import-level error or any invalid row → `validation_failed`; else `validated`.
- `file_sha256` captured; rows persisted atomically (delete+recreate on re-validation).

## 5. Supported headers (alias map, EN + AR)

account_code (**رقم الحساب/كود الحساب**) · account_name (**اسم الحساب**) · debit (**مدين**) · credit (**دائن**) · amount (**المبلغ/القيمة**) · transaction_date (**التاريخ/تاريخ المعاملة**) · posting_date (**تاريخ الترحيل/تاريخ القيد**) · journal_number (**رقم القيد/رقم اليومية/رقم السند**) · line_number (**رقم السطر**) · description (**البيان/الوصف**) · document_number (**رقم المستند/رقم الفاتورة**) · reference (**المرجع**) · counterparty (**الطرف المقابل/العميل/المورد**) · cost_center (**مركز التكلفة**) · department (**القسم/الإدارة**) · entered_by (**المستخدم/أدخله**) · source_system (**النظام/المصدر**) · currency (**العملة**).

## 6. AccountMapping integration (classification only)

For each GL row, the service looks up an existing `AccountMapping` for the same engagement + `account_code` and links `row.mapped_account` when found. It **does not** create or mutate mappings, post entries, or touch ledger accounts; existing (incl. manual) mappings are untouched. `validation_summary.unmapped_account_count` reports how many distinct GL accounts have no mapping yet (use 1B's generate endpoint to fill them). Linking uses `on_delete=SET_NULL`, so removing a mapping never cascades into GL evidence.

## 7. Trial Balance alignment checks

When `related_trial_balance_import` is set (validated same engagement/org), the service compares GL account codes vs TB account codes and records, as **warnings** (never hard failures):
- `gl_accounts_missing_from_tb` (GL activity on accounts absent from the TB),
- `tb_accounts_without_gl_activity` (TB accounts with no GL movement),
- a fiscal-year mismatch warning if the GL and TB fiscal years differ.
Counts + capped code lists are stored in `validation_summary.trial_balance_alignment`.

## 8. API behavior

Under `/api/v1/audit/` (no namespace), mirroring 1B:

| Method · Path | Permission | Behavior |
|---|---|---|
| `GET /general-ledger/imports/` | authenticated | List GL imports in the user's org (optional `?engagement=`). |
| `POST /general-ledger/imports/` | auditor+ | Multipart upload (`engagement`, `uploaded_file`, optional `related_trial_balance_import`, period/fiscal/currency). Engagement + TB link resolved **scoped to the user's org** (404/400 otherwise); runs `parse_and_validate`; returns detail (201) or 400 with the failed import. |
| `GET /general-ledger/imports/<uuid>/` | authenticated | Org-scoped detail: summary, journal counts, alignment, and up to 20 sample invalid rows. |

No hard delete; no archive endpoint this phase.

## 9. Tenant isolation rules

Engagement and TB-link resolved via `organization=request.user.organization` (not theirs → 404/400, no disclosure). All querysets org-filtered. `organization` always set from the engagement, never request input; the service re-asserts org == engagement.org and TB-link engagement/org. Tested: cross-org upload denied, cross-org detail 404, list scoped, foreign TB link rejected.

## 10. Test results

`pytest apps/audit/tests/test_general_ledger_import.py` — model creation/uniqueness, cross-tenant + foreign-TB `clean()` rejection, CSV balanced + journal grouping, unbalanced GL/journal warnings, AR/EN aliases, signed amounts, invalid-row capture, summary + sha256, period validation, format rejection, XLSX, row org inheritance, AccountMapping linking + unmapped count, TB alignment warnings, org-scoped upload/list/detail API, cross-org denial, and **no ledger writes**. Full `apps/audit` suite re-run (see response §10).

## 11. Intentionally NOT implemented (out of scope)

Bank reconciliation · VAT reconciliation · materiality integration · sampling · assertions matrix · SAD/misstatement accumulation · workpaper generation · report packs · ISA-700 wording · AI analysis · posting GL rows into ledger · hard delete/archive endpoints.

## 12. Recommended next phase

**TADGEEG-FIN-AUDIT-2B — GL journal-entry risk flags & period-end/sensitive-account analytics** (read-only, over the staged GL: weekend/after-hours postings, round numbers, just-below-threshold, rare account pairings — surfaced as warnings/candidate findings, no ledger writes), then begin **wiring findings + materiality to the engagement**.

## 13. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no GL/TB data into ledger tables; no `ledger.JournalEntry` change; no bank-rec/materiality/sampling/SAD this phase; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no ISA-700 wording change; no production-readiness claim.
