"""
Management command to seed the rule catalog.

Usage:
    python manage.py seed_rule_assignments
    python manage.py seed_rule_assignments --clear  # Clear and re-seed (dev only)
"""
from django.core.management.base import BaseCommand
from django.db import transaction


# ── Rule Catalog ──────────────────────────────────────────────────────────────
# Each entry: (rule_code, category, rule_type, scope, default_severity,
#              blocks_approval, requires_cross_document, implementation_class,
#              name_en, name_ar, description_en, fail_msg_en, fail_msg_ar, suggested_action_ar)

RULE_CATALOG = [
    # ── Generic Rules ─────────────────────────────────────────────────────────
    ("GEN-H01", "data_integrity", "validation", "generic", "high", False, False,
     "apps.rule_engine.rules.generic.document_number_rule.DocumentNumberRule",
     "Document Number Present", "وجود رقم المستند",
     "Every document must have a unique identifier number.",
     "Document number is missing.", "رقم المستند مفقود.",
     "أضف رقم مرجعي فريد للمستند."),

    ("GEN-H02", "data_integrity", "validation", "generic", "high", False, False,
     "apps.rule_engine.rules.generic.document_date_rule.DocumentDateRule",
     "Document Date Present", "وجود تاريخ المستند",
     "Every document must have a date.",
     "Document date is missing.", "تاريخ المستند مفقود.",
     "أضف تاريخ المستند."),

    ("GEN-H05", "data_integrity", "validation", "generic", "high", False, False,
     "apps.rule_engine.rules.generic.total_amount_rule.TotalAmountPresentRule",
     "Total Amount Present", "وجود المبلغ الإجمالي",
     "Every financial document must have a total amount.",
     "Total amount is missing.", "المبلغ الإجمالي مفقود.",
     "أضف المبلغ الإجمالي للمستند."),

    ("GEN-H06", "data_integrity", "validation", "generic", "medium", False, False,
     "apps.rule_engine.rules.generic.currency_rule.CurrencyRule",
     "Currency Present and Valid", "وجود رمز العملة وصحته",
     "Every financial document must specify a currency.",
     "Currency code is missing or invalid.", "رمز العملة مفقود أو غير صحيح.",
     "أضف رمز العملة الصحيح (مثال: SAR)."),

    ("GEN-H07", "financial_logic", "validation", "generic", "high", False, False,
     "apps.rule_engine.rules.generic.total_greater_zero_rule.TotalGreaterZeroRule",
     "Total Amount Greater Than Zero", "المبلغ الإجمالي أكبر من صفر",
     "Financial documents must have a positive total amount.",
     "Total amount is zero or negative.", "المبلغ الإجمالي صفر أو سالب.",
     "تحقق من صحة المبلغ الإجمالي."),

    ("DUP-04", "data_integrity", "anomaly", "generic", "high", True, False,
     "apps.rule_engine.rules.generic.duplicate_file_hash_rule.DuplicateFileHashRule",
     "Duplicate File Hash", "تكرار بصمة الملف",
     "Identical files (same hash) should not be uploaded twice.",
     "Duplicate file detected.", "تم اكتشاف ملف مكرر.",
     "تحقق من الملف المرفوع — قد يكون مكررًا."),

    ("CTL-01", "compliance", "compliance", "generic", "medium", False, False,
     "apps.rule_engine.rules.generic.workflow_rules.CostCenterRule",
     "Cost Center Assigned", "وجود مركز التكلفة",
     "Documents should be assigned to a cost center for proper accounting.",
     "No cost center assigned.", "لا يوجد مركز تكلفة.",
     "عيّن مركز التكلفة المناسب."),

    ("CTL-04", "compliance", "compliance", "generic", "high", False, False,
     "apps.rule_engine.rules.generic.workflow_rules.NoEditAfterApprovalRule",
     "No Edit After Approval", "عدم التعديل بعد الموافقة",
     "Approved documents must not be modified.",
     "Document was edited after approval.", "تم تعديل المستند بعد الموافقة.",
     "أوقف أي تعديلات على المستند المعتمد وافتح قضية تدقيق."),

    ("CTL-05", "compliance", "compliance", "generic", "medium", False, False,
     "apps.rule_engine.rules.generic.workflow_rules.HasApproverRule",
     "Has Approver", "وجود موافق",
     "Financial documents must have an assigned approver.",
     "No approver assigned.", "لا يوجد موافق.",
     "عيّن موافقًا مخوّلًا للمستند."),

    ("CTL-06", "compliance", "compliance", "generic", "low", False, False,
     "apps.rule_engine.rules.generic.workflow_rules.HasAuditTrailRule",
     "Has Audit Trail", "وجود سجل مراجعة",
     "Documents must have audit event records.",
     "No audit trail found.", "لا يوجد سجل مراجعة.",
     "تأكد من تفعيل سجل أحداث المراجعة."),

    # ── Invoice / VAT Rules ───────────────────────────────────────────────────
    ("VAT-01", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.vat_calculation_rule.VATRateRule",
     "VAT Rate Correct (15%)", "نسبة الضريبة المضافة صحيحة (15%)",
     "Saudi VAT rate must be 15%.",
     "VAT rate is not 15%.", "نسبة الضريبة ليست 15%.",
     "صحّح نسبة الضريبة إلى 15%."),

    ("VAT-02", "financial_logic", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.vat_calculation_rule.VATCalculationRule",
     "VAT Calculation Correct", "صحة حساب الضريبة المضافة",
     "Subtotal + VAT must equal total amount.",
     "VAT calculation error detected.", "خطأ في حساب الضريبة المضافة.",
     "راجع حساب الضريبة: الأساس + الضريبة يجب أن يساوي الإجمالي."),

    ("VAT-04", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.vat_calculation_rule.VATNumberFormatRule",
     "VAT Number Format Valid", "صيغة الرقم الضريبي صحيحة",
     "Saudi VAT numbers must be 15 digits starting with 3.",
     "VAT number format is invalid.", "صيغة الرقم الضريبي غير صحيحة.",
     "تحقق من الرقم الضريبي: 15 رقمًا تبدأ بـ 3."),

    ("VAT-05", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.invoice.vat_calculation_rule.ZATCAQRCodeRule",
     "ZATCA QR Code Valid", "صلاحية رمز QR للزكاة والضريبة",
     "ZATCA-compliant invoices must have a valid QR code.",
     "ZATCA QR code is missing or invalid.", "رمز QR للزكاة مفقود أو غير صالح.",
     "أضف رمز QR وفق متطلبات الزكاة والضريبة والجمارك."),

    ("DUP-01", "data_integrity", "validation", "generic", "high", True, False,
     "apps.rule_engine.rules.invoice.duplicate_invoice_rule.DuplicateDocumentNumberRule",
     "Duplicate Document Number", "تكرار رقم المستند",
     "Document numbers must be unique within an organization.",
     "Duplicate document number found.", "تكرار رقم المستند.",
     "راجع رقم المستند وتحقق من عدم تكراره."),

    ("ANO-01", "financial_logic", "anomaly", "generic", "medium", False, False,
     "apps.rule_engine.rules.invoice.duplicate_invoice_rule.AmountAnomalyRule",
     "Amount Unusually High", "مبلغ مرتفع بشكل غير معتاد",
     "Amounts significantly above vendor average or absolute threshold are flagged.",
     "Unusually high amount detected.", "تم اكتشاف مبلغ مرتفع بشكل غير معتاد.",
     "راجع المبلغ مع مدير الميزانية."),

    # ── Purchase Order Rules ──────────────────────────────────────────────────
    ("PO-M06", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.purchase_order.retroactive_po_rule.VendorApprovedListRule",
     "Vendor Not on Approved List", "مورد غير موجود في قائمة الموردين المعتمدين",
     "Purchase orders should only be issued to approved vendors.",
     "Vendor is not on the approved list.", "المورد غير موجود في القائمة المعتمدة.",
     "احصل على موافقة على المورد قبل إصدار أمر الشراء."),

    ("PO-M08", "compliance", "compliance", "specialized", "high", True, True,
     "apps.rule_engine.rules.purchase_order.retroactive_po_rule.RetroactivePORule",
     "Retroactive PO Creation", "إنشاء أمر شراء بأثر رجعي",
     "PO must be created before the invoice date.",
     "PO was created after the invoice date.", "تم إنشاء أمر الشراء بعد تاريخ الفاتورة.",
     "أنشئ أمر الشراء قبل الفاتورة في المرة القادمة."),

    # ── Bank Statement Rules ──────────────────────────────────────────────────
    ("BNK-M01", "reconciliation", "reconciliation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.bank_statement.balance_reconciliation_rule.BalanceReconciliationRule",
     "Balance Reconciliation Failure", "فشل مطابقة الرصيد البنكي",
     "Opening balance + credits - debits must equal closing balance.",
     "Bank balance does not reconcile.", "الرصيد البنكي لا يتطابق.",
     "راجع الكشف البنكي مع البنك لتحديد مصدر الفارق."),

    ("BNK-M06", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.bank_statement.balance_reconciliation_rule.DuplicateTransactionRule",
     "Duplicate Bank Transactions", "معاملات بنكية مكررة",
     "Identical transactions (same amount, date, description) indicate errors or fraud.",
     "Duplicate transactions detected.", "تم اكتشاف معاملات مكررة.",
     "راجع المعاملات المكررة مع البنك."),

    ("BNK-M07", "compliance", "compliance", "specialized", "critical", True, False,
     "apps.rule_engine.rules.bank_statement.balance_reconciliation_rule.StructuringDetectionRule",
     "Structuring Detection (AML)", "اكتشاف التجزئة المتعمدة (غسيل أموال)",
     "Multiple transactions just below AML threshold indicate structuring.",
     "Potential structuring detected.", "تم اكتشاف احتمال تجزئة متعمدة.",
     "أبلغ عن هذا النشاط لمسؤول الامتثال لمكافحة غسيل الأموال."),

    ("BNK-M08", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.bank_statement.balance_reconciliation_rule.IBANFormatRule",
     "IBAN Format Invalid", "صيغة IBAN غير صحيحة",
     "Saudi IBAN must be 24 characters starting with SA.",
     "IBAN format is invalid.", "صيغة IBAN غير صحيحة.",
     "تحقق من رقم الآيبان مع البنك."),

    # ── Payroll Rules ─────────────────────────────────────────────────────────
    ("PAY-M01", "anomaly", "anomaly", "specialized", "critical", True, True,
     "apps.rule_engine.rules.payroll.net_salary_arithmetic_rule.GhostEmployeeRule",
     "Ghost Employee Detection", "كشف الموظف الوهمي",
     "Employees in payroll must exist in HR records.",
     "Ghost employee indicators detected.", "مؤشرات موظفين وهميين.",
     "راجع قائمة الموظفين مع قسم الموارد البشرية فورًا."),

    ("PAY-M03", "financial_logic", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.payroll.net_salary_arithmetic_rule.GOSICalculationRule",
     "GOSI Contribution Mismatch", "خطأ في حساب اشتراكات التأمينات",
     "GOSI contributions must match the official calculation rates.",
     "GOSI calculation error detected.", "خطأ في حساب التأمينات الاجتماعية.",
     "راجع حساب التأمينات وفق نسب الزكاة والتأمينات."),

    ("PAY-M04", "financial_logic", "validation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.payroll.net_salary_arithmetic_rule.NetSalaryArithmeticRule",
     "Net Salary Arithmetic Validation", "التحقق من حساب صافي الراتب",
     "Net salary must equal basic + allowances - deductions.",
     "Net salary arithmetic errors detected.", "أخطاء في حساب صافي الراتب.",
     "راجع بيانات الراتب لكل موظف وصحّح الأخطاء الحسابية."),

    ("PAY-M11", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.payroll.net_salary_arithmetic_rule.DuplicateEmployeeIDRule",
     "Duplicate Employee ID", "معرّف موظف مكرر في الكشف",
     "Each employee must appear once per payroll run.",
     "Duplicate employee IDs found.", "معرّفات موظفين مكررة.",
     "راجع كشف الرواتب وأزل السجلات المكررة."),

    # ── Expense Rules ─────────────────────────────────────────────────────────
    ("EXP-M01", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.expense.expense_rules.MissingReceiptRule",
     "Missing Receipt for Expense Line", "فاتورة إثبات مفقودة لبند مصروف",
     "All expense lines must have attached receipts.",
     "Missing receipts detected.", "فواتير إثبات مفقودة.",
     "أرفق فواتير الإثبات لجميع بنود المصروفات."),

    ("EXP-M02", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.expense.expense_rules.ExpensePolicyLimitRule",
     "Expense Exceeds Policy Limit", "مصروف يتجاوز الحد السياساتي",
     "Expense amounts must not exceed category policy limits.",
     "Policy limit exceeded.", "تجاوز الحد السياساتي.",
     "احصل على موافقة استثنائية أو قلّص المطالبة إلى حد السياسة."),

    ("EXP-M07", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.expense.expense_rules.SelfApprovalRule",
     "Manager Self-Approval Risk", "مخاطر الموافقة على مصروف النفس",
     "Expense submitter and approver must be different persons.",
     "Self-approval detected.", "تمت الموافقة الذاتية.",
     "يجب أن يوافق شخص آخر على تقرير المصروفات."),

    ("EXP-M09", "financial_logic", "validation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.expense.expense_rules.ExpenseTotalMatchRule",
     "Expense Total Does Not Match Line Items", "إجمالي المطالبة لا يطابق مجموع البنود",
     "Sum of expense lines must equal the declared total.",
     "Expense total mismatch.", "تعارض في إجمالي المصروفات.",
     "راجع مجموع البنود وصحّح الإجمالي المُعلن."),

    # ── Tax Return Rules ──────────────────────────────────────────────────────
    ("TAX-M01", "financial_logic", "validation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.tax_return.tax_return_rules.NetVATArithmeticRule",
     "Net VAT Arithmetic Error", "خطأ في حساب صافي الضريبة المضافة",
     "Net VAT = Output VAT - Input VAT.",
     "Net VAT arithmetic error.", "خطأ في حساب صافي الضريبة.",
     "راجع حساب صافي الضريبة: ضريبة المخرجات - ضريبة المدخلات."),

    ("TAX-M02", "compliance", "compliance", "specialized", "high", False, False,
     "apps.rule_engine.rules.tax_return.tax_return_rules.LateFilingRule",
     "Late Filing Detection", "اكتشاف التأخر في تقديم الإقرار",
     "VAT returns must be filed by the due date.",
     "Late filing detected.", "تأخر في تقديم الإقرار.",
     "قدّم الإقرار في الوقت المحدد لتجنب الغرامات."),

    ("TAX-M08", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.tax_return.tax_return_rules.ZATCAReferenceRule",
     "No ZATCA Reference Number", "غياب الرقم المرجعي للزكاة",
     "Accepted VAT returns must have a ZATCA reference number.",
     "ZATCA reference number is missing.", "الرقم المرجعي للزكاة مفقود.",
     "احصل على رقم مرجعي من منصة الزكاة والضريبة والجمارك."),

    # ── Fixed Asset Rules ─────────────────────────────────────────────────────
    ("AST-M01", "financial_logic", "validation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.fixed_asset.fixed_asset_rules.DepreciationCalculationRule",
     "Depreciation Calculation Error", "خطأ في حساب الإهلاك",
     "Annual depreciation must match Cost / Useful Life for straight-line method.",
     "Depreciation calculation errors found.", "أخطاء في حساب الإهلاك.",
     "راجع حسابات الإهلاك لكل أصل."),

    ("AST-M02", "financial_logic", "validation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.fixed_asset.fixed_asset_rules.NegativeBookValueRule",
     "Negative Book Value Detected", "قيمة دفترية سالبة",
     "Accumulated depreciation must not exceed asset cost.",
     "Negative book value detected.", "قيمة دفترية سالبة.",
     "أوقف الإهلاك عند الوصول للقيمة الدفترية الصفرية."),

    ("AST-M04", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.fixed_asset.fixed_asset_rules.DuplicateAssetIDRule",
     "Duplicate Asset Registration", "تسجيل أصل مكرر",
     "Each asset must have a unique ID in the register.",
     "Duplicate asset IDs found.", "معرّفات أصول مكررة.",
     "راجع سجل الأصول وأزل السجلات المكررة."),

    # ── Sales Receipt Rules ───────────────────────────────────────────────────
    ("REC-M01", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.sales_receipt.sales_receipt_rules.QRCodeContentRule",
     "QR Code Content Invalid", "محتوى رمز QR غير صالح",
     "ZATCA QR code TLV fields must match document data.",
     "QR code content is invalid.", "محتوى رمز QR غير صالح.",
     "أعد توليد رمز QR من نظام الفوترة الإلكترونية."),

    ("REC-M03", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.sales_receipt.sales_receipt_rules.CashReceiptLimitRule",
     "Receipt Amount Exceeds Cash Limit", "مبلغ الإيصال يتجاوز حد الدفع النقدي",
     "Cash transactions above SAR 60,000 require AML reporting.",
     "Cash receipt exceeds AML threshold.", "الإيصال النقدي يتجاوز حد الإبلاغ لمكافحة غسيل الأموال.",
     "أبلغ عن هذه المعاملة لمسؤول الامتثال."),

    # ── Cross-Document Rules ──────────────────────────────────────────────────
    ("CDR-01", "reconciliation", "reconciliation", "cross_document", "critical", True, True,
     "apps.rule_engine.rules.cross_document.invoice_po_match_rule.InvoicePOMatchRule",
     "Invoice–PO Amount Mismatch", "تعارض مبلغ الفاتورة مع أمر الشراء",
     "Invoice amount must match linked PO within tolerance.",
     "Invoice-PO amount mismatch detected.", "تعارض مبالغ الفاتورة وأمر الشراء.",
     "راجع أمر الشراء والفاتورة وحدد مصدر الفارق."),

    ("CDR-03", "reconciliation", "reconciliation", "cross_document", "critical", True, True,
     "apps.rule_engine.rules.cross_document.invoice_po_match_rule.PayrollBankReconciliationRule",
     "Payroll–Bank Transfer Reconciliation", "تسوية إجمالي الرواتب مع التحويل البنكي",
     "Total payroll must match the bank transfer amount.",
     "Payroll and bank transfer amounts do not match.", "إجمالي الرواتب لا يطابق التحويل البنكي.",
     "راجع إجمالي الرواتب والتحويل البنكي وحدد مصدر الفارق."),
]

# ── Document-to-Rule Assignments ──────────────────────────────────────────────
# Format: (rule_code, document_type, applicability, blocks_approval_override)
# blocks_approval_override=None means use rule default

SYSTEM_ASSIGNMENTS = [
    # GEN-H01: all types
    *[("GEN-H01", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "other"]],

    # GEN-H02: all types
    *[("GEN-H02", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "other"]],

    # GEN-H05: all types
    *[("GEN-H05", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt"]],

    # GEN-H06: all types
    *[("GEN-H06", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "other"]],

    # GEN-H07: most types (not tax_return where net can be 0)
    *[("GEN-H07", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "payroll",
        "expense", "fixed_asset", "sales_receipt"]],

    # DUP-04: all types
    *[("DUP-04", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "other"]],

    # CTL-01: financial docs only
    *[("CTL-01", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "expense", "fixed_asset", "payroll"]],

    # CTL-04, CTL-05, CTL-06: all types
    *[("CTL-04", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt"]],
    *[("CTL-05", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "payroll", "expense", "tax_return", "fixed_asset"]],
    *[("CTL-06", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt"]],

    # VAT rules: invoice, PO, expense, tax_return, sales_receipt
    *[("VAT-01", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "expense", "tax_return", "sales_receipt"]],
    *[("VAT-02", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "expense", "tax_return", "sales_receipt"]],
    *[("VAT-04", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "tax_return", "sales_receipt"]],
    ("VAT-05", "sales_invoice", "full", None),
    ("VAT-05", "sales_receipt", "full", None),

    # DUP-01, ANO-01: common types
    *[("DUP-01", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "expense", "sales_receipt"]],
    *[("ANO-01", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "payroll", "expense", "fixed_asset", "sales_receipt"]],

    # PO rules
    ("PO-M06", "purchase_order", "full", None),
    ("PO-M08", "purchase_order", "full", None),

    # Bank statement rules
    *[("BNK-M01", "bank_statement", "full", None),
      ("BNK-M06", "bank_statement", "full", None),
      ("BNK-M07", "bank_statement", "full", None),
      ("BNK-M08", "bank_statement", "full", None)],

    # Payroll rules
    *[("PAY-M01", "payroll", "full", None),
      ("PAY-M03", "payroll", "full", None),
      ("PAY-M04", "payroll", "full", None),
      ("PAY-M11", "payroll", "full", None)],

    # Expense rules
    *[("EXP-M01", "expense", "full", None),
      ("EXP-M02", "expense", "full", None),
      ("EXP-M07", "expense", "full", None),
      ("EXP-M09", "expense", "full", None)],

    # Tax return rules
    *[("TAX-M01", "tax_return", "full", None),
      ("TAX-M02", "tax_return", "full", None),
      ("TAX-M08", "tax_return", "full", None)],

    # Fixed asset rules
    *[("AST-M01", "fixed_asset", "full", None),
      ("AST-M02", "fixed_asset", "full", None),
      ("AST-M04", "fixed_asset", "full", None)],

    # Sales receipt rules
    *[("REC-M01", "sales_receipt", "full", None),
      ("REC-M03", "sales_receipt", "full", None)],

    # Cross-document rules
    *[("CDR-01", "sales_invoice", "conditional", None),
      ("CDR-01", "purchase_order", "full", None),
      ("CDR-03", "payroll", "full", None),
      ("CDR-03", "bank_statement", "conditional", None)],
]


class Command(BaseCommand):
    help = "Seed rule definitions and system-level rule assignments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing system rules before seeding (dev only).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.rule_engine.models import (
            RuleDefinition, RuleDefinitionTranslation, RuleAssignment
        )

        if options["clear"]:
            self.stdout.write(self.style.WARNING("Clearing existing system rule data..."))
            RuleAssignment.objects.filter(organization__isnull=True).delete()
            RuleDefinition.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared."))

        # ── Seed Rule Definitions ──────────────────────────────────────────────
        self.stdout.write("Seeding rule definitions...")
        rule_map = {}

        for entry in RULE_CATALOG:
            (code, cat, rtype, scope, sev, blocks, cross_doc,
             impl_class, name_en, name_ar, desc, fail_en, fail_ar, action_ar) = entry

            rule, created = RuleDefinition.objects.update_or_create(
                rule_code=code,
                defaults={
                    "category": cat,
                    "rule_type": rtype,
                    "scope": scope,
                    "default_severity": sev,
                    "blocks_approval": blocks,
                    "requires_cross_document": cross_doc,
                    "implementation_class": impl_class,
                    "is_active": True,
                    "is_system_rule": True,
                }
            )
            rule_map[code] = rule

            # English translation
            RuleDefinitionTranslation.objects.update_or_create(
                rule=rule,
                language="en",
                defaults={
                    "name": name_en,
                    "description": desc,
                    "fail_message": fail_en,
                    "suggested_action": "",
                }
            )

            # Arabic translation
            RuleDefinitionTranslation.objects.update_or_create(
                rule=rule,
                language="ar",
                defaults={
                    "name": name_ar,
                    "description": desc,
                    "fail_message": fail_ar,
                    "suggested_action": action_ar,
                }
            )

            status_str = self.style.SUCCESS("created") if created else "updated"
            self.stdout.write(f"  {code}: {status_str}")

        self.stdout.write(f"\nSeeded {len(RULE_CATALOG)} rule definitions.")

        # ── Seed System Assignments ────────────────────────────────────────────
        self.stdout.write("\nSeeding system rule assignments...")
        created_count = 0
        skipped_count = 0

        for (code, doc_type, applicability, blocks_override) in SYSTEM_ASSIGNMENTS:
            rule = rule_map.get(code)
            if not rule:
                self.stdout.write(self.style.WARNING(f"  Skipping {code} — not in catalog."))
                continue

            assignment, created = RuleAssignment.objects.update_or_create(
                rule=rule,
                document_type=doc_type,
                organization=None,  # system-level
                defaults={
                    "applicability": applicability,
                    "status": "active",
                    "blocks_approval_override": blocks_override,
                }
            )
            if created:
                created_count += 1
            else:
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! {len(RULE_CATALOG)} rules | "
                f"{created_count} new assignments | "
                f"{skipped_count} updated assignments."
            )
        )
