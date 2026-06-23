# TADGEEG-FIN-AUDIT-1B — Trial Balance Upload/API & Account Mapping

> **Phase type:** Additive. Org-scoped DRF endpoints over the 1A staging tables + an `AccountMapping` classification layer. **No** ledger writes, no new apps, no second `AuditEngagement`.
> **Date:** 2026-06-23 · **Builds on:** `2cd9650` (1A staging). · **Predecessors:** [1A](TADGEEG_FIN_AUDIT_1A_TRIAL_BALANCE_IMPORT_STAGING.md), [0B](TADGEEG_FIN_AUDIT_0B_RUNTIME_VERIFICATION_AND_SOURCE_OF_TRUTH.md).

---

## 1. What was implemented

1. **Minimal organization-scoped DRF API** to use the 1A Trial Balance staging: upload, list, detail.
2. **`AccountMapping` model + service** — maps each client TB account code → a canonical audit category (and optionally an existing `ledger.Account`) **for classification/linking only**.
3. Admin registration, tests, docs, migration `0014`.

The audit app already uses DRF (`APIView`/`generics`, `IsAuthenticated`, `IsSeniorAuditorOrAbove`) with consistent `request.user.organization` scoping, so the **smallest safe existing pattern was DRF** — no new UI framework was invented. Endpoints live in a dedicated `apps/audit/views_trial_balance.py` (mirroring the existing `views_rule_builder.py` split).

## 2. Upload / API behavior

Mounted under `/api/v1/audit/` (no namespace):

| Method · Path | Permission | Behavior |
|---|---|---|
| `GET /trial-balance/imports/` | authenticated | List imports in the user's org (optional `?engagement=`). |
| `POST /trial-balance/imports/` | auditor+ (`IsSeniorAuditorOrAbove`) | Multipart upload (`engagement`, `uploaded_file`, optional `period_start/period_end/fiscal_year/currency`). Resolves the engagement **scoped to the user's org** (404 if not theirs), infers format from extension (csv/xlsx/xls), creates the `TrialBalanceImport`, and runs the **existing 1A `parse_and_validate`**. Returns the detail payload (201) or 400 with the failed import on parse error. |
| `GET /trial-balance/imports/<uuid>/` | authenticated | Org-scoped detail: status, row/valid/invalid counts, totals, difference, `is_balanced`, `validation_summary`, errors/warnings, and a **sample of up to 20 invalid rows**. |
| `GET /trial-balance/account-mappings/` | authenticated | List mappings in the user's org (optional `?engagement=`). |
| `POST /trial-balance/account-mappings/generate/` | auditor+ | `{import_id}` → org-scoped → deterministically suggest mappings; returns a summary. |

No hard delete; no destructive endpoints. (Archive remains a status the model supports; no archive endpoint was added this phase.)

## 3. Organization isolation rules

- Upload resolves the engagement via `AuditEngagement.objects.filter(pk=…, organization=request.user.organization)`. An engagement in another org is simply **not found → 404**, never disclosed.
- List/detail/mapping querysets all filter by `organization=request.user.organization`.
- `TrialBalanceImport.organization` is always set from the resolved engagement, never from request input; the 1A service also re-asserts org == engagement.org.
- Generate-mappings is scoped by `import_id` + org (404 otherwise).
- Tested: cross-org upload denied, cross-org detail 404, list scoped, cross-org generate 404.

## 4. AccountMapping — purpose & why classification-only

`AccountMapping` (`audit_account_mappings`) is a **bridge/classification layer**: it records, per engagement, how a client's `account_code` maps to a canonical audit **category** and optionally to an existing `ledger.Account`.

- `mapped_ledger_account` is a **nullable FK with `on_delete=SET_NULL`** — a *read-only reference* to align the client chart with the platform chart for later reporting. The mapping **never posts journal entries and never mutates ledger accounts**; removing a ledger account nulls the reference rather than cascading into audit evidence.
- **Why classification-only:** the client trial balance is *evidence under audit*, not the platform's books. Mapping organizes that evidence; it must not flow into `apps.ledger` (internal, hash-chained, period-locked accounting truth). A test asserts **zero** new `Account`/`JournalEntry`/`JournalLine` rows after upload + mapping.

**Fields:** engagement, organization, account_code, account_name, `mapped_category` (17 categories incl. `unknown`), `mapped_ledger_account` (nullable), `mapping_source` (manual/rule_based/imported), `confidence` (nullable), notes, created_by/updated_by, created_at/updated_at. **Unique** (engagement, account_code); indexes on (engagement, account_code), (organization, mapped_category), (mapped_category).

## 5. Account mapping service & category rules

`apps/audit/services/account_mapping.py`:
- `suggest_category(account_name, account_code) → (category, confidence)` — deterministic, first-match-wins keyword rules over a normalized `"<name> <code>"` string. **No AI.** Confidence 0.700 on match, 0.000 (unknown) otherwise.
- `generate_mappings_from_import(import_batch, created_by=None)` — creates a `rule_based` mapping for each distinct account in the import that **isn't already mapped**, so existing **manual** mappings are preserved. Returns `{created, skipped_existing, distinct_accounts, by_category}`. Never touches the ledger.

Supported category rules (EN + AR, first-match-wins; specific before broad):

| Category | Sample keywords |
|---|---|
| vat_tax | vat / tax / zakat / **ضريبة / القيمة المضافة / زكاة** |
| cash_and_bank | cash / bank / petty / **نقدية / بنك / صندوق** |
| accounts_receivable | receivable / customer / **عملاء / ذمم مدينة** |
| inventory | inventory / stock / **مخزون / بضاعة** |
| fixed_assets | fixed asset / equipment / depreciation / **أصول ثابتة / إهلاك** |
| accounts_payable | payable / supplier / **موردين / ذمم دائنة** |
| loans | loan / facility / overdraft / **قرض / تمويل** |
| equity | equity / capital / reserve / **رأس المال / احتياطي** |
| revenue | revenue / sales / **مبيعات / إيرادات** |
| cost_of_sales | cost of sales / cogs / purchases / **تكلفة المبيعات / مشتريات** |
| payroll_expense | salary / payroll / wage / **رواتب / أجور** |
| finance_cost | interest expense / bank charge / **فوائد / مصاريف بنكية** |
| operating_expense | expense / rent / utilities / **مصروف / إيجار** |
| (else) | **unknown** |

## 6. Tests run

`pytest apps/audit/tests/test_trial_balance_upload_and_mapping.py` — covers: upload to own org (201 + parse ran), cross-org upload denied (404), unsupported extension (400), org-scoped list, detail summary + invalid-rows sample, cross-org detail 404, mapping model creation + uniqueness, AR/EN deterministic suggestions, unknown fallback, generate-from-import, **manual mapping preserved**, generate endpoint org scoping (own 201 / other 404), and **no ledger writes**. Full `apps/audit` suite re-run for regression (see response §8).

## 7. Intentionally NOT implemented (out of scope)

General Ledger import · bank reconciliation · VAT reconciliation · materiality integration · sampling · assertions matrix · SAD/misstatement accumulation · workpaper generation · report packs · AI analysis · ISA-700 wording changes · hard delete · archive endpoint · a bespoke front-end (the API is the surface; a UI can consume it later).

## 8. Recommended next phase

**TADGEEG-FIN-AUDIT-2A — General Ledger import staging** (same staging pattern, engagement-linked, no ledger writes), reusing the `AccountMapping` chart alignment; followed by wiring findings/materiality to the engagement.

## 9. What NOT to change (carried forward)

No second `AuditEngagement`; no `apps/financial_audit`; no TB/mapping data into ledger tables; no GL import this phase; no payments/subscriptions/CRM/Moyasar/manual-payments/legal-page changes; no ISA-700 wording change; no production-readiness claim.
