# Canonical Schema & Rule Engine Refactor Plan
**Generated:** 2026-03-22
**Platform:** Tadgeeg — AI-Powered Financial Document Auditing SaaS
**Status:** IN PROGRESS — Day 1 started

---

## Executive Summary

The platform has two parallel upload pipelines (Invoice + Typed Documents), a rule engine with 40 rules across 9 document types, and an AI extraction layer via OpenAI Vision. The foundation is solid but has **critical architectural gaps**:

| Area | Current State | Critical Problem |
|---|---|---|
| Field extraction | OpenAI Vision + parsers | Some extracted fields never reach the model |
| Normalization | Per-type normalizers | No canonical schema — each type is siloed |
| Rule-field binding | Implicit via `typed_data` dict | No formal dependency registry — rules fail silently |
| Null handling | Inconsistent | Some rules crash, some return NOT_APPLICABLE incorrectly |
| Upload pipeline | Two separate paths | No unified normalization pass before rules run |
| Cross-document | CrossDocumentLink model exists | Rules can't access it at execution time |
| Evidence | EvidenceItem exists | Sparsely populated — auditors see empty evidence |
| Schema | JSON blobs + typed models | No canonical field layer — mapping is implicit |

---

## Canonical Field Inventory

### Group A — Core Identity Fields

| canonical_field_name | Arabic Label | Type | Nullable | Applicable Types | Storage | Rules | Reporting |
|---|---|---|---|---|---|---|---|
| `document_type` | نوع المستند | str | NO | ALL | YES | YES | YES |
| `document_number` | رقم المستند | str | YES | ALL | YES | YES | YES |
| `document_date` | تاريخ المستند | date | YES | ALL | YES | YES | YES |
| `posting_date` | تاريخ الترحيل | date | YES | ALL | NO | NO | YES |
| `reference_number` | رقم المرجع | str | YES | ALL | NO | YES | YES |
| `source_filename` | اسم الملف | str | NO | ALL | YES | NO | YES |
| `source_sheet_name` | اسم الورقة | str | YES | Excel types | NO | NO | YES |
| `tenant_id` | معرف المستأجر | UUID | NO | ALL | YES | YES | YES |
| `company_name` | اسم الشركة | str | YES | ALL | NO | YES | YES |
| `branch` | الفرع | str | YES | ALL | NO | NO | YES |
| `department` | القسم | str | YES | ALL | NO | NO | YES |
| `cost_center` | مركز التكلفة | str | YES | ALL | NO | YES | YES |
| `status` | الحالة | str | NO | ALL | YES | YES | YES |
| `notes` | ملاحظات | text | YES | ALL | NO | NO | NO |

### Group B — Counterparty Fields

| canonical_field_name | Arabic Label | Type | Nullable | Applicable Types |
|---|---|---|---|---|
| `vendor_name` | اسم المورد | str | YES | invoice, purchase_order, expense |
| `vendor_tax_number` | رقم ضريبة المورد | str | YES | invoice, purchase_order |
| `vendor_cr_number` | رقم السجل التجاري | str | YES | invoice, purchase_order |
| `customer_name` | اسم العميل | str | YES | invoice, sales_receipt |
| `customer_tax_number` | رقم ضريبة العميل | str | YES | invoice, sales_receipt |
| `employee_id` | رقم الموظف | str | YES | payroll, expense |
| `employee_name` | اسم الموظف | str | YES | payroll, expense |
| `approver_name` | اسم المعتمد | str | YES | ALL workflow types |
| `bank_name` | اسم البنك | str | YES | bank_statement |

### Group C — Financial Amount Fields

| canonical_field_name | Arabic Label | Type | Nullable | Applicable Types |
|---|---|---|---|---|
| `currency_code` | رمز العملة | str(3) | NO | ALL |
| `subtotal_amount` | المبلغ قبل الضريبة | decimal | YES | invoice, purchase_order, sales_receipt |
| `tax_rate` | نسبة الضريبة | decimal | YES | invoice, sales_receipt, vat_return |
| `tax_amount` | مبلغ الضريبة | decimal | YES | invoice, purchase_order, sales_receipt |
| `discount_amount` | مبلغ الخصم | decimal | YES | invoice |
| `net_amount` | الصافي | decimal | YES | ALL financial |
| `debit_amount` | مدين | decimal | YES | bank_statement |
| `credit_amount` | دائن | decimal | YES | bank_statement |
| `balance_amount` | الرصيد | decimal | YES | bank_statement, fixed_asset |
| `payment_amount` | مبلغ الدفع | decimal | YES | invoice, vat_return |
| `budget_limit` | سقف الميزانية | decimal | YES | purchase_order |
| `quantity` | الكمية | decimal | YES | purchase_order, invoice lines |
| `unit_price` | سعر الوحدة | decimal | YES | purchase_order, invoice lines |

### Group D — Compliance / ZATCA Fields

| canonical_field_name | Arabic Label | Type | Nullable | Applicable Types |
|---|---|---|---|---|
| `zatca_invoice_number` | رقم فاتورة زاتكا | str | YES | invoice, sales_receipt |
| `qr_code_valid` | صحة رمز QR | bool | YES | invoice, sales_receipt |
| `vat_registration_number` | رقم تسجيل ضريبة القيمة المضافة | str | YES | invoice, vat_return, sales_receipt |
| `zatca_reference` | مرجع زاتكا | str | YES | vat_return |
| `filing_status` | حالة التقديم | str | YES | vat_return |
| `payment_status` | حالة الدفع | str | YES | invoice |
| `approval_status` | حالة الاعتماد | str | YES | purchase_order, expense |
| `bank_account_number` | رقم الحساب البنكي | str | YES | bank_statement, payroll |
| `iban` | رقم الآيبان | str | YES | bank_statement, payroll |

### Group E — Timeline Fields

| canonical_field_name | Arabic Label | Type | Nullable |
|---|---|---|---|
| `issue_date` | تاريخ الإصدار | date | YES |
| `due_date` | تاريخ الاستحقاق | date | YES |
| `delivery_date` | تاريخ التسليم | date | YES |
| `submission_date` | تاريخ التقديم | date | YES |
| `approval_date` | تاريخ الاعتماد | date | YES |
| `payment_date` | تاريخ الدفع | date | YES |
| `period_from` | بداية الفترة | date | YES |
| `period_to` | نهاية الفترة | date | YES |
| `tax_period` | الفترة الضريبية | str | YES |

### Group F — Classification Fields

| canonical_field_name | Arabic Label | Type | Nullable |
|---|---|---|---|
| `expense_type` | نوع المصروف | str | YES |
| `asset_category` | فئة الأصل | str | YES |
| `asset_id` | معرف الأصل | str | YES |
| `payroll_month` | شهر الرواتب | str | YES |
| `payment_method` | طريقة الدفع | str | YES |
| `depreciation_method` | طريقة الإهلاك | str | YES |
| `useful_life_years` | العمر الإنتاجي بالسنوات | int | YES |

### Group G — HR / Payroll Fields

| canonical_field_name | Arabic Label | Type | Nullable |
|---|---|---|---|
| `gross_salary` | الراتب الإجمالي | decimal | YES |
| `net_salary` | صافي الراتب | decimal | YES |
| `total_allowances` | إجمالي البدلات | decimal | YES |
| `total_deductions` | إجمالي الاستقطاعات | decimal | YES |
| `gosi_amount` | مبلغ التأمينات الاجتماعية | decimal | YES |
| `employee_count` | عدد الموظفين | int | YES |

---

## Column-to-Canonical Mapping by Document Type

### Invoice
| Raw Field | Canonical Field | Transform |
|---|---|---|
| `invoice_number` | `document_number` | string |
| `invoice_date` | `document_date` | date_parse |
| `due_date` | `due_date` | date_parse |
| `vendor_name` / `supplier_name` / `merchant_name` | `vendor_name` | first_non_null |
| `vendor_vat_number` | `vendor_tax_number` | string |
| `vendor_cr_number` | `vendor_cr_number` | string |
| `customer_name` | `customer_name` | string |
| `customer_vat_number` | `customer_tax_number` | string |
| `currency` | `currency_code` | uppercase |
| `subtotal` | `subtotal_amount` | decimal |
| `vat_rate` | `tax_rate` | decimal |
| `vat_amount` | `tax_amount` | decimal |
| `discount` | `discount_amount` | decimal |
| `total_amount` | `net_amount` | decimal |
| `qr_code_valid` | `qr_code_valid` | bool |
| `cost_center` | `cost_center` | string |
| `department` | `department` | string |

### Purchase Order
| Raw Field | Canonical Field | Transform |
|---|---|---|
| `po_number` | `document_number` | string |
| `po_date` | `document_date` | date_parse |
| `delivery_date` | `delivery_date` | date_parse |
| `vendor_name` | `vendor_name` | string |
| `vendor_vat_number` | `vendor_tax_number` | string |
| `vendor_cr_number` | `vendor_cr_number` | string |
| `requester_name` | `employee_name` | string |
| `department` | `department` | string |
| `cost_center` | `cost_center` | string |
| `currency` | `currency_code` | uppercase |
| `subtotal` | `subtotal_amount` | decimal |
| `vat_amount` | `tax_amount` | decimal |
| `total_amount` | `net_amount` | decimal |
| `budget_limit` | `budget_limit` | decimal |
| `approval_status` | `approval_status` | string |

### Bank Statement
| Raw Field | Canonical Field | Transform |
|---|---|---|
| `bank_name` | `bank_name` | string |
| `account_number` | `bank_account_number` | string |
| `iban` | `iban` | uppercase |
| `currency` | `currency_code` | uppercase |
| `statement_period_from` | `period_from` | date_parse |
| `statement_period_to` | `period_to` | date_parse |
| `closing_balance` | `balance_amount` | decimal |
| `total_credits` | `credit_amount` | decimal |
| `total_debits` | `debit_amount` | decimal |

### Payroll
| Raw Field | Canonical Field | Transform |
|---|---|---|
| `company_name` | `company_name` | string |
| `department` | `department` | string |
| `payroll_period_from` | `period_from` | date_parse |
| `payroll_period_to` | `period_to` | date_parse |
| `payment_date` | `payment_date` | date_parse |
| `currency` | `currency_code` | uppercase |
| `employee_count` | `employee_count` | direct |
| `total_gross_salary` | `gross_salary` | decimal |
| `total_net_salary` | `net_salary` | decimal |
| `total_allowances` | `total_allowances` | decimal |
| `total_deductions` | `total_deductions` | decimal |
| `total_gosi` | `gosi_amount` | decimal |

### Expense Report
| Raw Field | Canonical Field | Transform |
|---|---|---|
| `report_number` | `document_number` | string |
| `employee_name` | `employee_name` | string |
| `employee_id` | `employee_id` | string |
| `department` | `department` | string |
| `report_period_from` | `period_from` | date_parse |
| `report_period_to` | `period_to` | date_parse |
| `submitted_date` | `submission_date` | date_parse |
| `currency` | `currency_code` | uppercase |
| `total_claimed` | `net_amount` | decimal |
| `vat_included` | `tax_amount` | decimal |

### VAT Return / Tax Declaration
| Raw Field | Canonical Field | Transform |
|---|---|---|
| `taxpayer_name` | `company_name` | string |
| `vat_number` | `vat_registration_number` | string |
| `cr_number` | `vendor_cr_number` | string |
| `period_from` | `period_from` | date_parse |
| `period_to` | `period_to` | date_parse |
| `filing_date` | `submission_date` | date_parse |
| `due_date` | `due_date` | date_parse |
| `zatca_reference` | `zatca_reference` | string |
| `net_vat_payable` | `payment_amount` | decimal |
| `filing_status` | `filing_status` | string |

### Fixed Asset
| Raw Field | Canonical Field | Transform |
|---|---|---|
| `company_name` | `company_name` | string |
| `department` | `department` | string |
| `fiscal_year` | `tax_period` | string |
| `register_date` | `document_date` | date_parse |
| `total_book_value` | `net_amount` | decimal |
| `total_accumulated_depreciation` | `balance_amount` | decimal |

### Sales Receipt
| Raw Field | Canonical Field | Transform |
|---|---|---|
| `receipt_number` | `document_number` | string |
| `receipt_date` | `document_date` | date_parse |
| `seller_name` | `vendor_name` | string |
| `seller_vat_number` | `vendor_tax_number` | string |
| `customer_name` | `customer_name` | string |
| `customer_vat_number` | `customer_tax_number` | string |
| `currency` | `currency_code` | uppercase |
| `subtotal` | `subtotal_amount` | decimal |
| `vat_rate` | `tax_rate` | decimal |
| `vat_amount` | `tax_amount` | decimal |
| `total_amount` | `net_amount` | decimal |
| `zatca_uuid` | `zatca_invoice_number` | string |
| `qr_code_valid` | `qr_code_valid` | bool |

---

## Gap Analysis

### Critical Gaps
| # | Gap | Impact |
|---|---|---|
| C-01 | No canonical mapping layer — rules access raw AI output keys directly | Rules fail silently |
| C-02 | EXP-M07 self-approval: `approved_by` is a FK, never in `typed_data` | Rule is dead code |
| C-03 | No rule dependency registry — rules are black boxes | Cannot validate pipeline |
| C-04 | Upload pipeline drops some extracted fields | Evidence incomplete |
| C-05 | `tax_declaration` vs `vat_return` type name mismatch | Upload failure |

### High Priority Gaps
| # | Gap | Impact |
|---|---|---|
| H-01 | No null-safe field access helper in normalizers | Fragile field binding |
| H-02 | Line items stored as JSON blob — not indexed | Reporting blind spot |
| H-03 | Risk score calculated in 3 places with max() merge | Wrong risk levels |
| H-04 | AuditEvidence sparsely populated | Auditors see no explanation |
| H-05 | No `document_number` for BankStatement, PayrollSheet, FixedAsset | GEN-H01 always fails |
| H-06 | Transaction array has no canonical field names | BNK-M02, BNK-M04 brittle |

### Medium Priority Gaps
| # | Gap | Impact |
|---|---|---|
| M-01 | InvoiceValidationResult: 30 boolean columns — adding rule needs migration | Schema rigidity |
| M-02 | No versioning on extracted data | Audit trail weak |
| M-03 | `counterparty_name` not always populated | ANO-01 degrades silently |
| M-04 | `org_context` dict not standardized across normalizers | Cross-rule inconsistency |
| M-05 | No per-organization policy limits for EXP-M02 | Cannot customize per tenant |
| M-06 | Excel multi-sheet files — only first sheet processed | Data loss |
| M-07 | No confidence score stored per field | QA blind spot |

---

## Rule-to-Field Dependency Matrix

| Rule Code | Required Fields | Null Behavior | Binding Status |
|---|---|---|---|
| GEN-H01 | `document_number` | FAIL | ✅ |
| GEN-H02 | `document_date` | FAIL | ✅ |
| GEN-H05 | `net_amount` | FAIL | ✅ |
| GEN-H06 | `currency_code` | WARNING | ✅ |
| GEN-H07 | `net_amount` | SKIP | ✅ |
| VAT-01 | `tax_rate` | NOT_APPLICABLE | ⚠️ Key tied to Invoice model |
| VAT-02 | `subtotal_amount`, `tax_amount`, `net_amount` | NOT_APPLICABLE | ⚠️ |
| VAT-04 | `vendor_tax_number` | NOT_APPLICABLE | ⚠️ Falls back on two keys |
| VAT-05 | `qr_code_valid` | NOT_APPLICABLE | ✅ |
| BNK-M01 | `balance_amount`, `credit_amount`, `debit_amount` | NOT_APPLICABLE | ✅ |
| BNK-M02 | `transactions[]` | NOT_APPLICABLE | ⚠️ No type hint |
| BNK-M03 | `iban` | NOT_APPLICABLE | ✅ |
| PAY-M01 | `employees[].id` | NOT_APPLICABLE | ⚠️ JSON key assumption |
| PAY-M03 | `employees[].{gross,deductions,net}` | NOT_APPLICABLE | ⚠️ |
| PAY-M04 | `gosi_amount` | FAIL | ✅ |
| EXP-M01 | `expense_lines[].receipt_attached` | FAIL | ⚠️ Key tied to AI output |
| EXP-M07 | `approved_by`, `employee_id` | NOT_APPLICABLE | ❌ DEAD CODE |
| EXP-M09 | `expense_lines[].amount`, `net_amount` | NOT_APPLICABLE | ✅ |
| TAX-M01 | `output_vat`, `input_vat`, `net_vat_payable` | NOT_APPLICABLE | ✅ |
| TAX-M02 | `submission_date`, `due_date` | NOT_APPLICABLE | ✅ |
| TAX-M08 | `filing_status`, `zatca_reference` | NOT_APPLICABLE | ✅ |
| AST-M01 | `assets[].book_value` | NOT_APPLICABLE | ⚠️ |
| AST-M02 | `assets[].{cost,accumulated_depreciation,book_value}` | NOT_APPLICABLE | ⚠️ |
| AST-M04 | `assets[].asset_id` | NOT_APPLICABLE | ⚠️ |

---

## 7-Day Action Plan

| Day | Tasks | Status |
|---|---|---|
| **Day 1** | Create canonical models, migration, seed commands | ⏳ IN PROGRESS |
| **Day 2** | Integrate CanonicalMapper into both upload pipelines | ⏳ PENDING |
| **Day 3** | Add `field_dependencies` + `get_field()` to AuditRuleBase, update all 40 rules | ⏳ PENDING |
| **Day 4** | Add RuleDependencyChecker pre-flight to AuditPipeline, deploy to dev | ⏳ PENDING |
| **Day 5** | Fix EXP-M07, BNK-M02/M04, ANO-01, add auto-evidence for null failures | ⏳ PENDING |
| **Day 6** | Full QA: all 8 doc types, performance test, update Rules.md | ⏳ PENDING |
| **Day 7** | Push to main, deploy to live, monitor | ⏳ PENDING |

---

## Implementation Progress

### Day 1 Deliverables
- [ ] `apps/documents/canonical_models.py` — CanonicalFieldDefinition, DocumentTypeFieldMapping, DocumentCanonicalData
- [ ] `apps/rule_engine/models/rule_field_dependency.py` — RuleFieldDependency
- [ ] Migration for canonical models
- [ ] `core/services/canonical_mapper.py` — CanonicalMapper + Transform
- [ ] `apps/rule_engine/management/commands/seed_canonical_fields.py`
- [ ] `apps/rule_engine/management/commands/seed_rule_dependencies.py`
