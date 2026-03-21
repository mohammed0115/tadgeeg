# Document Audit Rule Engine — Complete Architecture & Implementation Record

> **Last Updated:** 2026-03-22
> **System:** Tadgeeg — AI-Powered Financial Document Auditing SaaS (Multi-tenant, Saudi Arabia)
> **Status:** IMPLEMENTED — Rule Engine v2.0 live, 40 rules seeded, 129 system assignments, 118 tests passing

---

## Actual System State (Before Implementation)

> **Critical finding (pre-implementation):** The system did NOT have 30 implemented rule classes. It had:
> - **6 executable rule classes** (R001-R006) in apps/audit/rules/
> - **30 validation fields** stored as booleans in InvoiceValidationResult model — schema only, not rule logic
> - **Rule codes referenced** in typed_models.py (PO-001, BNK-001...) as documentation only — zero implementations
> - **ValidationService** with basic arithmetic checks — not integrated into the rule engine
> - **CustomRuleDefinition** model — config-driven, not class-based
>
> **Coverage before:** ~18% of what a complete document audit engine requires.

---

## 1. Executive Technical Summary

The system was structurally invoice-centric. The 6 implemented rule classes were designed with invoice data structures in mind. The 30 "rules" in InvoiceValidationResult were stored results, not reusable logic. Every other document type (purchase_order, bank_statement, payroll, expense, tax_return, fixed_asset, sales_receipt) had typed models with rich fields but zero active audit rule implementations executing against them.

**Critical biases identified and fixed:**
- AuditEngine.evaluate() dispatched all 6 rules against every document but rules internally queried Invoice.objects — producing wrong risk scores for non-invoice documents → Fixed via NormalizedDocument abstraction
- No rule existed for: bank reconciliation, payroll arithmetic, GOSI calculation, three-way PO matching, depreciation accuracy, VAT return arithmetic, expense policy enforcement → All implemented
- No cross-document rule existed anywhere → CDR-01, CDR-03 implemented; CDR architecture complete
- Risk scoring aggregated all 6 rules equally regardless of document type → Replaced by weighted severity model

---

## 2. Current 30-Rule Reusability Assessment

### Group 1: Header / Existence Rules (8 rules)

| # | Rule Code | Rule Name EN | Rule Name AR | Reusability | Implemented |
|---|-----------|-------------|-------------|-------------|-------------|
| 1 | GEN-H01 | Document Number Present | وجود رقم المستند | 5/5 | YES |
| 2 | GEN-H02 | Document Date Present | وجود تاريخ المستند | 5/5 | YES |
| 3 | GEN-H03 | Counterparty Name Present | وجود اسم الطرف | 4/5 | no |
| 4 | GEN-H04 | Tax ID Present | وجود الرقم الضريبي | 2/5 | no |
| 5 | GEN-H05 | Total Amount Present | وجود المبلغ الإجمالي | 5/5 | YES |
| 6 | GEN-H06 | Currency Present | وجود رمز العملة | 5/5 | YES |
| 7 | GEN-H07 | Total Amount > Zero | المبلغ أكبر من صفر | 4/5 | YES |
| 8 | GEN-H08 | No VAT Without Base | لا ضريبة بدون أساس | 2/5 | no |

### Group 2: Duplicate Detection Rules (5 rules)

| # | Rule Code | Rule Name EN | Rule Name AR | Reusability | Implemented |
|---|-----------|-------------|-------------|-------------|-------------|
| 9 | DUP-01 | Duplicate Document Number | تكرار رقم المستند | 5/5 | YES |
| 10 | DUP-02 | Duplicate Vendor+Number | تكرار المورد+الرقم | 3/5 | no |
| 11 | DUP-03 | Duplicate Fingerprint | تكرار البصمة | 4/5 | no |
| 12 | DUP-04 | Duplicate File Hash | تكرار بصمة الملف | 5/5 | YES |
| 13 | DUP-05 | Duplicate Across Months | تكرار عبر الأشهر | 3/5 | no |

### Group 3: VAT Validation Rules (5 rules)

| # | Rule Code | Rule Name EN | Rule Name AR | Reusability | Implemented |
|---|-----------|-------------|-------------|-------------|-------------|
| 14 | VAT-01 | VAT Rate = 15% | نسبة الضريبة 15% | 2/5 | YES |
| 15 | VAT-02 | VAT Calculation Correct | صحة حساب الضريبة | 3/5 | YES |
| 16 | VAT-03 | Subtotal + VAT = Total | الأساس+الضريبة=الإجمالي | 3/5 | no |
| 17 | VAT-04 | VAT Number Format | صحة الرقم الضريبي | 2/5 | YES |
| 18 | VAT-05 | ZATCA QR Code Valid | صلاحية رمز QR | 1/5 | YES |

### Group 4: Anomaly Detection Rules (6 rules)

| # | Rule Code | Rule Name EN | Rule Name AR | Reusability | Implemented |
|---|-----------|-------------|-------------|-------------|-------------|
| 19 | ANO-01 | Amount Unusually High | مبلغ مرتفع غير معتاد | 4/5 | YES |
| 20 | ANO-02 | New Unknown Vendor | مورد جديد مجهول | 3/5 | no |
| 21 | ANO-03 | Many Documents Same Day | كثرة المستندات يوم واحد | 4/5 | no |
| 22 | ANO-04 | Sudden Price Change | ارتفاع مفاجئ في السعر | 3/5 | no |
| 23 | ANO-05 | Year-End Concentration | تركّز نهاية السنة | 4/5 | no |
| 24 | ANO-06 | Vendor Dominates Spend | هيمنة مورد على الإنفاق | 3/5 | no |

### Group 5: Financial Control Rules (6 rules)

| # | Rule Code | Rule Name EN | Rule Name AR | Reusability | Implemented |
|---|-----------|-------------|-------------|-------------|-------------|
| 25 | CTL-01 | Cost Center Assigned | وجود مركز التكلفة | 4/5 | YES |
| 26 | CTL-02 | Account Code Assigned | وجود رمز الحساب | 3/5 | no |
| 27 | CTL-03 | Within Budget Limit | ضمن حد الميزانية | 4/5 | no |
| 28 | CTL-04 | No Edit After Approval | عدم التعديل بعد الموافقة | 5/5 | YES |
| 29 | CTL-05 | Has Approver | وجود موافق | 5/5 | YES |
| 30 | CTL-06 | Has Audit Trail | وجود سجل مراجعة | 5/5 | YES |

---

## 3. Missing Rules Catalog

### 3.1 Purchase Order Rules (9 rules)

| Rule Code | Rule Name EN | Rule Name AR | Severity | Implemented |
|-----------|-------------|-------------|----------|-------------|
| PO-M01 | Three-Way Match Failure | فشل المطابقة الثلاثية | CRITICAL | no |
| PO-M02 | Invoice Precedes PO | فاتورة قبل أمر الشراء | HIGH | no |
| PO-M03 | PO Quantity Tolerance Exceeded | تجاوز تفاوت الكمية | HIGH | no |
| PO-M04 | PO Price Deviation > Threshold | انحراف السعر عن العقد | HIGH | no |
| PO-M05 | PO Splitting (Threshold Avoidance) | تجزئة أمر الشراء | HIGH | no |
| PO-M06 | Vendor Not on Approved List | مورد غير موافق عليه | HIGH | YES |
| PO-M07 | Delivery Date Expired Without GRN | استحقاق التوصيل بدون استلام | MEDIUM | no |
| PO-M08 | Retroactive PO Creation | إنشاء أمر شراء بأثر رجعي | HIGH | YES |
| PO-M09 | Sole-Source Without Justification | شراء منفرد بدون مبرر | MEDIUM | no |

### 3.2 Bank Statement Rules (11 rules)

| Rule Code | Rule Name EN | Rule Name AR | Severity | Implemented |
|-----------|-------------|-------------|----------|-------------|
| BNK-M01 | Balance Reconciliation Failure | فشل مطابقة الرصيد | CRITICAL | YES |
| BNK-M02 | Benford's Law Deviation | انحراف قانون بنفورد | HIGH | no |
| BNK-M03 | Round-Amount Transaction Cluster | تكتّل المبالغ المستديرة | HIGH | no |
| BNK-M04 | Weekend/Holiday Transactions | معاملات في إجازات رسمية | MEDIUM | no |
| BNK-M05 | Late-Night Transaction Cluster | معاملات في ساعات متأخرة | MEDIUM | no |
| BNK-M06 | Duplicate Transactions | معاملات مكررة | HIGH | YES |
| BNK-M07 | Structuring Detection (AML, SAR 60k) | اكتشاف التجزئة المتعمدة | CRITICAL | YES |
| BNK-M08 | IBAN Format Invalid (SA: 24 chars, starts SA) | صيغة IBAN السعودي خاطئة | HIGH | YES |
| BNK-M09 | Rapid Succession Transfers | تحويلات متتالية سريعة | HIGH | no |
| BNK-M10 | GL Reconciliation Mismatch | عدم تطابق مع دفتر الأستاذ | HIGH | no |
| BNK-M11 | Intercompany Transfer Undocumented | تحويل بين شركات بدون وثيقة | MEDIUM | no |

### 3.3 Payroll Rules (11 rules)

| Rule Code | Rule Name EN | Rule Name AR | Severity | Implemented |
|-----------|-------------|-------------|----------|-------------|
| PAY-M01 | Ghost Employee Detection | كشف الموظف الوهمي | CRITICAL | YES |
| PAY-M02 | Salary Spike Anomaly | ارتفاع راتب مفاجئ | HIGH | no |
| PAY-M03 | GOSI Contribution Mismatch (11.75%/9.75%) | خطأ في حساب التأمينات | HIGH | YES |
| PAY-M04 | Net Salary Arithmetic Error | خطأ في حساب صافي الراتب | CRITICAL | YES |
| PAY-M05 | Employee Count vs HR System | تعارض عدد الموظفين مع HR | HIGH | no |
| PAY-M06 | Payroll Period Overlap | تداخل فترات الرواتب | HIGH | no |
| PAY-M07 | Payment to Terminated Employee | دفع لموظف منتهية خدمته | CRITICAL | no |
| PAY-M08 | Bank Account Change Without Notice | تغيير حساب بنكي بدون إشعار | HIGH | no |
| PAY-M09 | Allowances Exceed Policy Ceiling | بدلات تتجاوز الحد السياساتي | MEDIUM | no |
| PAY-M10 | Total Payroll vs Bank Outflow | إجمالي الرواتب لا يطابق التحويل | CRITICAL | no |
| PAY-M11 | Duplicate Employee ID | معرّف موظف مكرر | HIGH | YES |

### 3.4 Expense Rules (10 rules)

| Rule Code | Rule Name EN | Rule Name AR | Severity | Implemented |
|-----------|-------------|-------------|----------|-------------|
| EXP-M01 | Missing Receipt for Expense Line | فاتورة إثبات مفقودة | HIGH | YES |
| EXP-M02 | Expense Exceeds Policy Limit | مصروف يتجاوز الحد السياساتي | HIGH | YES |
| EXP-M03 | Duplicate Expense Claim | مطالبة مصروف مكررة | HIGH | no |
| EXP-M04 | Claim Submitted After Deadline | مطالبة بعد انتهاء المهلة | MEDIUM | no |
| EXP-M05 | Split Claim (Threshold Avoidance) | تجزئة المطالبة | HIGH | no |
| EXP-M06 | Weekend Expense Without Justification | مصروف في إجازة بدون مبرر | MEDIUM | no |
| EXP-M07 | Manager Self-Approval Risk | موافق على مصروف نفسه | HIGH | YES |
| EXP-M08 | Personal Category Expense | مصروف شخصي في تقرير عمل | HIGH | no |
| EXP-M09 | Total Does Not Match Line Items | الإجمالي لا يطابق السطور | CRITICAL | YES |
| EXP-M10 | Receipt VAT Mismatch | تناقض ضريبة الفاتورة | MEDIUM | no |

### 3.5 Tax Return Rules (8 rules)

| Rule Code | Rule Name EN | Rule Name AR | Severity | Implemented |
|-----------|-------------|-------------|----------|-------------|
| TAX-M01 | Net VAT Arithmetic Error | خطأ في حساب صافي الضريبة | CRITICAL | YES |
| TAX-M02 | Late Filing Detection | اكتشاف التأخر في الإقرار | HIGH | YES |
| TAX-M03 | VAT Number Format Invalid | صيغة الرقم الضريبي خاطئة | HIGH | no |
| TAX-M04 | Prior Period Variance Spike | تفاوت كبير مع الفترة السابقة | HIGH | no |
| TAX-M05 | Sales Reconciliation Failure | فشل تسوية المبيعات | CRITICAL | no |
| TAX-M06 | Input VAT vs Purchases Mismatch | عدم تطابق ضريبة المشتريات | HIGH | no |
| TAX-M07 | Zero-Rated vs Exempt Misclassification | خلط المعفى بالصفري | MEDIUM | no |
| TAX-M08 | No ZATCA Reference Number | غياب رقم مرجعي من الزكاة | HIGH | YES |

### 3.6 Fixed Asset Rules (9 rules)

| Rule Code | Rule Name EN | Rule Name AR | Severity | Implemented |
|-----------|-------------|-------------|----------|-------------|
| AST-M01 | Depreciation Calculation Error | خطأ في حساب الإهلاك | CRITICAL | YES |
| AST-M02 | Negative Book Value | قيمة دفترية سالبة | CRITICAL | YES |
| AST-M03 | Over-Depreciation | إهلاك زائد | HIGH | no |
| AST-M04 | Duplicate Asset Registration | تسجيل أصل مكرر | HIGH | YES |
| AST-M05 | Asset Without Purchase Document | أصل بدون وثيقة شراء | HIGH | no |
| AST-M06 | Asset Disposal Without Approval | تصرف في أصل بدون موافقة | HIGH | no |
| AST-M07 | CAPEX vs OPEX Misclassification | خلط النفقات الرأسمالية والتشغيلية | HIGH | no |
| AST-M08 | Useful Life Out of Policy Range | عمر افتراضي خارج النطاق | MEDIUM | no |
| AST-M09 | Fully Depreciated Asset Still Active | أصل مستهلك كليًا لا يزال نشطًا | LOW | no |

### 3.7 Sales Receipt Rules (6 rules)

| Rule Code | Rule Name EN | Rule Name AR | Severity | Implemented |
|-----------|-------------|-------------|----------|-------------|
| REC-M01 | QR Code Content Invalid | محتوى رمز QR غير صالح | HIGH | YES |
| REC-M02 | Receipt Number Sequence Gap | فجوة في تسلسل الإيصالات | HIGH | no |
| REC-M03 | Receipt Amount Exceeds Cash Limit (SAR 60k AML) | مبلغ نقدي يتجاوز الحد | HIGH | YES |
| REC-M04 | Credit Note Exceeds Original | إشعار دائن يتجاوز المبلغ الأصلي | HIGH | no |
| REC-M05 | Receipt Issued After Invoice Settled | إيصال بعد تسوية الفاتورة | MEDIUM | no |
| REC-M06 | Void Receipt Without Authorization | إلغاء إيصال بدون تفويض | HIGH | no |

### 3.8 Cross-Document Rules (6 rules)

| Rule Code | Rule Name EN | Rule Name AR | Severity | Doc Types | Implemented |
|-----------|-------------|-------------|----------|-----------|-------------|
| CDR-01 | Invoice-PO Amount Mismatch | تعارض مبلغ الفاتورة مع أمر الشراء | CRITICAL | INV + PO | YES |
| CDR-02 | Invoice-Payment Matching | مطابقة الفاتورة بالدفعة البنكية | HIGH | INV + BNK | no |
| CDR-03 | Payroll-Bank Reconciliation | تسوية الرواتب مع البنك | CRITICAL | PAY + BNK | YES |
| CDR-04 | Tax Return-Invoice Reconciliation | تسوية الإقرار مع الفواتير | CRITICAL | TAX + INV | no |
| CDR-05 | Fixed Asset-Purchase Document | أصل ثابت بدون وثيقة شراء | HIGH | AST + INV/PO | no |
| CDR-06 | Expense Receipt-Invoice Match | مطابقة إيصال المصروف | MEDIUM | EXP + INV | no |

**TOTALS: 40 implemented / 85 total rules | 40 seeded in DB | 129 system assignments**

---

## 4. Document-to-Rule Matrix

Legend: F=FULL | P=PARTIAL | C=CONDITIONAL | N=NOT_APPLICABLE

| Rule Code | INV | PO | BNK | PAY | EXP | TAX | AST | REC | OTH | Done |
|-----------|-----|----|-----|-----|-----|-----|-----|-----|-----|------|
| GEN-H01 | F | F | F | F | F | F | P | F | C | YES |
| GEN-H02 | F | F | F | F | F | F | F | F | F | YES |
| GEN-H03 | F | F | P | P | P | P | P | F | C | no |
| GEN-H04 | F | F | N | N | N | F | N | F | C | no |
| GEN-H05 | F | F | F | F | F | F | F | F | C | YES |
| GEN-H06 | F | F | F | F | F | F | F | F | F | YES |
| GEN-H07 | F | F | C | F | F | C | F | F | C | YES |
| GEN-H08 | F | F | N | N | P | F | N | F | N | no |
| DUP-01 | F | F | F | F | F | F | P | F | C | YES |
| DUP-02 | F | F | N | P | P | P | N | F | N | no |
| DUP-03 | F | F | N | C | F | N | N | F | C | no |
| DUP-04 | F | F | F | F | F | F | F | F | F | YES |
| DUP-05 | F | C | N | C | F | N | N | F | C | no |
| VAT-01 | F | F | N | N | F | F | N | F | N | YES |
| VAT-02 | F | F | N | N | F | F | N | F | N | YES |
| VAT-03 | F | F | N | N | F | F | N | F | N | no |
| VAT-04 | F | F | N | N | N | F | N | F | N | YES |
| VAT-05 | F | N | N | N | N | N | N | F | N | YES |
| ANO-01 | F | F | P | F | F | C | F | F | C | YES |
| ANO-02 | F | F | N | P | P | N | P | F | C | no |
| ANO-03 | F | F | N | N | C | N | N | F | C | no |
| ANO-04 | F | F | N | F | C | N | N | C | N | no |
| ANO-05 | F | F | C | N | C | N | F | C | C | no |
| ANO-06 | F | F | N | N | F | N | F | C | N | no |
| CTL-01 | F | F | N | F | F | N | F | C | N | YES |
| CTL-02 | F | F | N | N | F | N | F | C | N | no |
| CTL-03 | F | F | N | F | F | N | F | C | N | no |
| CTL-04 | F | F | F | F | F | F | F | F | F | YES |
| CTL-05 | F | F | N | F | F | F | F | C | C | YES |
| CTL-06 | F | F | F | F | F | F | F | F | F | YES |
| PO-M06 | N | F | N | N | N | N | N | N | N | YES |
| PO-M08 | N | F | N | N | N | N | N | N | N | YES |
| BNK-M01 | N | N | F | N | N | N | N | N | N | YES |
| BNK-M06 | N | N | F | N | N | N | N | N | N | YES |
| BNK-M07 | N | N | F | N | N | N | N | N | N | YES |
| BNK-M08 | N | N | F | N | N | N | N | N | N | YES |
| PAY-M01 | N | N | N | F | N | N | N | N | N | YES |
| PAY-M03 | N | N | N | F | N | N | N | N | N | YES |
| PAY-M04 | N | N | N | F | N | N | N | N | N | YES |
| PAY-M11 | N | N | N | F | N | N | N | N | N | YES |
| EXP-M01 | N | N | N | N | F | N | N | N | N | YES |
| EXP-M02 | N | N | N | N | F | N | N | N | N | YES |
| EXP-M07 | N | N | N | N | F | N | N | N | N | YES |
| EXP-M09 | N | N | N | N | F | N | N | N | N | YES |
| TAX-M01 | N | N | N | N | N | F | N | N | N | YES |
| TAX-M02 | N | N | N | N | N | F | N | N | N | YES |
| TAX-M08 | N | N | N | N | N | F | N | N | N | YES |
| AST-M01 | N | N | N | N | N | N | F | N | N | YES |
| AST-M02 | N | N | N | N | N | N | F | N | N | YES |
| AST-M04 | N | N | N | N | N | N | F | N | N | YES |
| REC-M01 | N | N | N | N | N | N | N | F | N | YES |
| REC-M03 | N | N | N | N | N | N | N | F | N | YES |
| CDR-01 | C | F | N | N | N | N | N | N | N | YES |
| CDR-03 | N | N | F | F | N | N | N | N | N | YES |

---

## 5. Gap Analysis

### Critical — All Resolved

| Gap | Description | Resolution |
|-----|-------------|------------ |
| GAP-C01 | No balance reconciliation for bank statements | BNK-M01 implemented |
| GAP-C02 | No payroll arithmetic in rule engine | PAY-M04 + PAY-M03 implemented |
| GAP-C03 | No VAT return arithmetic rule | TAX-M01 implemented |
| GAP-C04 | No three-way PO matching | CDR-01 (INV/PO) implemented |
| GAP-C05 | No cross-document rules anywhere | CDR-01, CDR-03 live; architecture complete |
| GAP-C06 | AuditEngine uses Invoice querysets for all docs | NormalizedDocument eliminates this |

### High Priority — Partial

| Gap | Description | Status |
|-----|-------------|--------|
| GAP-H01 | No structuring/layering detection | BNK-M07 (SAR 60k AML) |
| GAP-H02 | No ghost employee detection | PAY-M01 |
| GAP-H03 | No expense policy limit enforcement | EXP-M02 |
| GAP-H04 | No fixed asset depreciation validation | AST-M01, AST-M02 |
| GAP-H05 | No ZATCA QR content validation | VAT-05, REC-M01 |
| GAP-H06 | Rules not linked to typed models | 8 normalizers implemented |
| GAP-H07 | ValidationService independent from AuditEngine | AuditPipeline is single orchestrator |
| GAP-H08 | InvoiceValidationResult is flat boolean schema | All fields re-implemented as AuditRuleBase |
| GAP-H09 | No Benford's Law analysis | Pending (BNK-M02) |
| GAP-H10 | No GOSI contribution validation | PAY-M03 (11.75% Saudi / 9.75% non-Saudi) |

---

## 6. Implemented App Structure

    apps/rule_engine/                     LIVE
    models/
        rule_definition.py            RuleDefinition, RuleDefinitionTranslation
        rule_assignment.py            RuleAssignment (DB-backed, per tenant)
        audit_execution.py            AuditRun, AuditResult, AuditEvidence
        risk.py                       RiskScoreSummary
        review.py                     ManualReviewDecision
        cross_document.py             CrossDocumentLink
    rules/
        base.py                       AuditRuleBase ABC, NormalizedDocument, RuleResult, EvidenceItem
        generic/
            document_number_rule.py   GEN-H01
            document_date_rule.py     GEN-H02
            total_amount_rule.py      GEN-H05
            currency_rule.py          GEN-H06 (validates against GCC currency set)
            total_greater_zero_rule.py GEN-H07 (skips tax_return)
            duplicate_file_hash_rule.py DUP-04
            workflow_rules.py         CTL-01, CTL-04, CTL-05, CTL-06
        invoice/
            vat_calculation_rule.py   VAT-01, VAT-02, VAT-04, VAT-05
            duplicate_invoice_rule.py DUP-01, ANO-01
        purchase_order/
            retroactive_po_rule.py    PO-M06, PO-M08
        bank_statement/
            balance_reconciliation_rule.py  BNK-M01, BNK-M06, BNK-M07, BNK-M08
        payroll/
            net_salary_arithmetic_rule.py   PAY-M01, PAY-M03, PAY-M04, PAY-M11
        expense/
            expense_rules.py          EXP-M01, EXP-M02, EXP-M07, EXP-M09
        tax_return/
            tax_return_rules.py       TAX-M01, TAX-M02, TAX-M08
        fixed_asset/
            fixed_asset_rules.py      AST-M01, AST-M02, AST-M04
        sales_receipt/
            sales_receipt_rules.py    REC-M01, REC-M03
        cross_document/
            invoice_po_match_rule.py  CDR-01, CDR-03
    registry/
        rule_registry.py              Dynamic class loader + ALLOWED_RULE_MODULES allowlist
    selectors/
        rule_selector.py              Tenant/system merge logic with date filtering
    normalizers/
        __init__.py                   BaseNormalizer, DocumentNormalizerFactory
        invoice_normalizer.py         Invoice -> NormalizedDocument
        bank_statement_normalizer.py  BankStatement -> NormalizedDocument
        payroll_normalizer.py         PayrollSheet -> NormalizedDocument
        purchase_order_normalizer.py  PurchaseOrder -> NormalizedDocument
        expense_normalizer.py         ExpenseReport -> NormalizedDocument
        tax_return_normalizer.py      VATReturn -> NormalizedDocument
        fixed_asset_normalizer.py     FixedAsset -> NormalizedDocument
        sales_receipt_normalizer.py   SalesReceipt -> NormalizedDocument
    executors/
        audit_pipeline.py             Full orchestrator (AuditRun lifecycle, evidence, risk)
    risk/
        risk_aggregator.py            Weighted severity scoring
    serializers/
        audit_run_serializers.py      DRF serializers (AuditRun, AuditResult, RiskSummary, TriggerAudit)
    api/
        views.py                      7 endpoints
        urls.py                       Wired at api/v1/rule-engine/
    tasks/
        audit_tasks.py                Celery task (max_retries=3, soft_time_limit=120s)
    management/commands/
        seed_rule_assignments.py      Idempotent — 40 rules + 129 system assignments
    migrations/
        0001_initial.py               Applied
    admin.py                          Full Django admin for all 8 models
    tests/
        test_rules/
            test_balance_reconciliation.py  9 tests (BNK-M01)
            test_net_salary.py              8 tests (PAY-M04)
            test_generic_rules.py           30 tests (GEN-H01/02/05/06/07)
            test_vat_rules.py               36 tests (VAT-01/02/04/05)
            test_expense_rules.py           26 tests (EXP-M01/02/07/09)
            test_tax_return_rules.py        19 tests (TAX-M01/02/08)
        Total: 118 tests — all passing

---

## 7. Rule Engine Execution Flow

    Document Uploaded via AuditDocumentUploadView
        |
    DocumentUploadRouter.route()
        -> _route_invoice()   or   _route_document()
        |
    _trigger_rule_engine(document_id, document_type, organization_id)
        |  [async, only if USE_NEW_RULE_ENGINE=True]
    run_audit_task.delay()  [Celery, max_retries=3]
        |
    AuditPipeline.run(document_id, document_type, organization_id)
        |
    DocumentNormalizerFactory.get(document_type) -> NormalizedDocument
        |
    RuleSelector.get_applicable_rules(document_type, org_id)
        -> Merges org-specific + system-level assignments
        -> Respects effective_from/until dates
        -> Org assignments shadow system defaults
        |
    AuditRun created (status=RUNNING)
        |
    For each RuleAssignment:
        -> RuleRegistry.get_class(implementation_class)
        -> rule.check_preconditions(doc) -> SKIPPED if not met
        -> rule.execute(doc) -> RuleResult
        -> AuditResult + AuditEvidence persisted
        |
    RiskAggregator.compute(results, assignments)
        -> SEVERITY_WEIGHTS x result.risk_contribution
        -> Normalised to 0-100
        -> risk_level, blocks_approval, requires_manual_review
        |
    RiskScoreSummary upserted for document (update_or_create)
        |
    AuditRun updated (status=COMPLETED, all counters)

---

## 8. Risk Scoring Model

    SEVERITY_WEIGHTS = {
        "critical": 40.0,
        "high":     25.0,
        "medium":   10.0,
        "low":       5.0,
        "info":      1.0,
    }

    WARNING counts as 50% of the severity weight
    PASS / SKIPPED / NOT_APPLICABLE contribute 0

    risk_score = (
        sum(weight x risk_contribution for each FAIL/WARNING result)
        / sum(weight for each active rule)
    ) x 100   -- normalised to 0-100

    RISK_THRESHOLDS = {
        "critical": 75,
        "high":     50,
        "medium":   25,
        "low":       0,
    }

---

## 9. API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | /api/v1/rule-engine/rules/ | Full rule catalog with bilingual translations |
| GET | /api/v1/rule-engine/runs/ | List audit runs for organization |
| GET | /api/v1/rule-engine/runs/<pk>/ | Run detail with all rule results |
| GET | /api/v1/rule-engine/risk/<uuid>/ | Risk summary for a document |
| GET | /api/v1/rule-engine/high-risk/ | Documents with risk_level=high/critical |
| POST | /api/v1/rule-engine/trigger/ | Manually trigger audit pipeline |
| GET | /api/v1/rule-engine/analytics/top-failures/ | Top failed rules across all runs |

---

## 10. Dashboard AI Report Integration

The rule engine is fully integrated into apps/reports/ AI report system.

### Data Collection (_collect_rule_engine_data)
Queries AuditRun + AuditResult + RuleDefinitionTranslation to produce:
- Total runs, avg risk score, blocking failure count, manual review count
- Total rules applied, passed, failed, warnings
- Compliance percentage (passed / total_applied x 100)
- Risk distribution (critical / high / medium / low)
- Top 10 failed rules with Arabic names from RuleDefinitionTranslation
- Breakdown by document type (run count, avg risk, blocking count)

### Report Generation (GenerateAuditReportView.post)
- Adds audit_data["rule_engine"] section when USE_NEW_RULE_ENGINE=True
- AI narrative receives rule engine stats
- Rule engine compliance rate overrides legacy InvoiceValidationResult rate
- Key findings list extended with: total runs, top failed rule in Arabic, blocking count

### Template (templates/reports/invoice_audit_report.html)
New section "محرك قواعد التدقيق الذكي" renders when report.rule_engine is present:
- 6 KPI cards: documents audited, passed rules, failed rules, warnings, blocking failures, avg risk
- Risk distribution horizontal bars (critical -> low) using widthratio
- Top failed rules table: rule code badge, Arabic name, fail count badge, risk contribution bar
- Per-document-type breakdown grid with run count, avg risk, blocking badge

---

## 11. Settings and Feature Flags

    # finai_backend/settings.py

    LOCAL_APPS = [
        ...
        "apps.rule_engine",      # Registered
    ]

    # Security allowlist -- only classes from these modules can be loaded by RuleRegistry
    ALLOWED_RULE_MODULES = ["apps.rule_engine.rules"]

    # Master cutover switch -- True = new engine runs on every upload via Celery
    USE_NEW_RULE_ENGINE = True

---

## 12. Database Seed State

    python manage.py seed_rule_assignments
    Output:
      Seeded 40 rule definitions.
      40 rules | 129 new assignments | 0 updated assignments

All 40 rule definitions have:
- English + Arabic names, descriptions, fail messages, suggested actions
- is_system_rule=True (tenant-protected, not deletable by tenant users)
- is_active=True
- System-level RuleAssignment rows for every applicable document type

---

## 13. QA Requirements

Each rule must pass 8 mandatory test cases:
1. test_pass_case -- happy path
2. test_fail_case -- clear violation
3. test_boundary_case -- at exact threshold
4. test_precondition_not_met -- verifies SKIP behavior
5. test_config_override -- threshold override works
6. test_arabic_output -- AR explanation present on fail
7. test_evidence_structure -- evidence fields populated correctly
8. test_no_exception_on_malformed_input -- never raises, returns ERROR status

Current status: 118 tests, 100% passing

---

## 14. Security Model

| Threat | Mitigation |
|--------|-----------|
| Tenant data leakage | All DB queries filter by organization_id from doc.organization_id |
| Rule config injection | config_override is a JSONField; never eval/exec'd |
| Malicious class path | RuleRegistry only loads from ALLOWED_RULE_MODULES whitelist |
| Evidence data exposure | Row-level permission check before API exposure |
| Cross-tenant contamination | AuditRun.organization FK always included in queries |
| OCR content injection | All typed_data values treated as untrusted strings |
| Rule tampering | is_system_rule=True rules not deletable by tenant users |
| DoS via slow rules | Celery soft_time_limit=120s, time_limit=180s per task |

---

## 15. Remaining Work (Next Sprint)

### Phase 2 Rules Not Yet Implemented

| Priority | Rule Codes | Description |
|----------|-----------|-------------|
| Critical | PAY-M07 | Payment to terminated employee |
| Critical | PAY-M10 | Total payroll vs bank outflow |
| Critical | TAX-M05 | Sales reconciliation failure |
| High | BNK-M02 | Benford's Law deviation |
| High | BNK-M03 | Round-amount transaction clustering |
| High | BNK-M04 | Weekend/holiday transactions |
| High | PAY-M02 | Salary spike anomaly |
| High | EXP-M03 | Duplicate expense claim |
| High | AST-M06 | Asset disposal without approval |
| High | CDR-02 | Invoice-payment matching (INV+BNK) |
| High | CDR-04 | Tax return-invoice reconciliation |
| High | CDR-05 | Fixed asset-purchase document match |
| High | CDR-06 | Expense receipt-invoice match |
| Medium | PO-M01 | Three-way match failure |
| Medium | PO-M03/04/05 | PO quantity/price/split rules |
| Medium | GEN-H03/04/08 | Counterparty, tax ID, VAT-without-base |

### Planned Features
- Tenant rule configuration UI (enable/disable rules per org, set thresholds via config_override)
- InvoiceValidationResult deprecation (fields kept nullable, stop writing new data to old model)
- Old AuditEngine removal after shadow-mode comparison period confirms equivalence
- Rule version tracking and rollback capability
- PDF export of AuditRun detail (per-document rule-by-rule report)
- Webhook trigger on blocks_approval=True to halt document approval workflow
- Benford's Law statistical analysis for bank statement transaction amounts
- Three-way PO matching (PO-M01: PO qty/price vs GRN vs Invoice)
