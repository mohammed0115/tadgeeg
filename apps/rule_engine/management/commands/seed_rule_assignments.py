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

    ("ZATCA-P2", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.zatca_phase2_rule.ZATCAPhase2ConformanceRule",
     "ZATCA Phase 2 Conformance", "مطابقة المرحلة الثانية للزكاة والضريبة",
     "UBL XML invoices must be signed and contain the required Phase 2 elements (UUID, ICV, PIH).",
     "ZATCA Phase 2 conformance failed.", "فشل مطابقة المرحلة الثانية.",
     "تأكّد أن الفاتورة موقّعة رقمياً وتحتوي على UUID/ICV/PIH وجميع الحقول الأساسية."),

    ("ZATCA-P3", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.zatca_pih_chain_rule.ZATCAPIHChainRule",
     "ZATCA PIH Chain Integrity", "سلامة سلسلة هاش الفاتورة السابقة",
     "Each invoice (after the first) must embed the SHA-256 of the previous invoice (PIH).",
     "PIH chain broken.", "سلسلة PIH مكسورة.",
     "تحقّق من قيمة PIH وقارنها بهاش الفاتورة السابقة في السلسلة."),

    # ── IFRS rules pack ──────────────────────────────────────────────────────
    ("IFRS-15", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.invoice.ifrs_rules.RevenueRecognitionTimingRule",
     "Revenue Recognition Timing (IFRS 15)", "توقيت الاعتراف بالإيرادات (IFRS 15)",
     "Year-end cut-off invoices must be reviewed to confirm revenue is recognized in the correct period.",
     "Year-end cut-off review required.", "مطلوب مراجعة فترة نهاية السنة.",
     "تأكّد من أن تاريخ تحويل السيطرة يقع في الفترة الصحيحة."),

    ("IFRS-2", "compliance", "compliance", "specialized", "low", False, False,
     "apps.rule_engine.rules.invoice.ifrs_rules.ExpenseMatchingRule",
     "Expense Matching (IFRS 2)", "مبدأ المقابلة (IFRS 2)",
     "Expenses must be recorded in the same period as the related revenue.",
     "Expense matching deviation.", "انحراف عن مبدأ المقابلة.",
     "راجع توقيت تسجيل المصروف مقابل فترة الخدمة."),

    ("IFRS-1", "anomaly", "anomaly", "specialized", "low", False, False,
     "apps.rule_engine.rules.invoice.ifrs_rules.GoingConcernIndicatorRule",
     "Going-Concern Indicator (IFRS 1)", "مؤشرات استمرارية المنشأة (IFRS 1)",
     "Multiple risk indicators clustering on a single invoice may signal going-concern doubt.",
     "Going-concern indicators present.", "مؤشرات استمرارية المنشأة موجودة.",
     "صعّد المستند للمراجع الإداري لتقييم استمرارية المنشأة."),

    ("IFRS-MAT", "compliance", "compliance", "specialized", "medium", True, False,
     "apps.rule_engine.rules.invoice.ifrs_rules.MaterialityThresholdRule",
     "Materiality Review (IFRS Materiality)", "مراجعة الأهمية النسبية (IFRS)",
     "Invoices above the materiality threshold (5% of revenue or 100k SAR) require auditor review.",
     "Above materiality threshold.", "تجاوز حد الأهمية النسبية.",
     "أرسل الفاتورة للمراجع الرئيسي لمراجعتها."),

    ("IFRS-FX", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.invoice.ifrs_rules.CurrencyConsistencyRule",
     "Foreign Currency Disclosure (IAS 21)", "الإفصاح عن العملة الأجنبية (IAS 21)",
     "Foreign-currency invoices must disclose the exchange rate used.",
     "Foreign currency without FX disclosure.", "عملة أجنبية بدون إفصاح عن سعر الصرف.",
     "أضف سعر الصرف المستخدم في تحويل العملة."),

    # ── IFRS period-close rules (cross-period, run during period audits) ──────
    ("IFRS-CON", "reconciliation", "reconciliation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.invoice.period_close_rules.ConsolidationBalanceRule",
     "Consolidation Balance (Σ debits = Σ credits)", "توازن التجميع (المدين = الدائن)",
     "Total debits must equal total credits across all journal entries in the period.",
     "Consolidation imbalance.", "خلل في التوازن.",
     "راجع القيود غير المتوازنة قبل إقفال الفترة."),

    ("IFRS-DEF", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.invoice.period_close_rules.DeferredRevenueRule",
     "Deferred Revenue Recognition (IFRS 15.B89)", "تأجيل الاعتراف بالإيراد (IFRS 15.B89)",
     "Multi-period service revenue must be deferred and recognized over the period.",
     "Multi-period revenue not deferred.", "إيراد متعدد الفترات لم يُؤجَّل.",
     "أنشئ قيد تأجيل وأعد توزيع الإيراد على الفترات."),

    ("IFRS-ACC", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.invoice.period_close_rules.AccrualCutOffRule",
     "Accrual Cut-Off", "قطع الاستحقاق",
     "Invoices must be booked in the same period as service delivery.",
     "Cut-off error: booking date drifts from delivery.", "خطأ قطع: تاريخ القيد ينحرف عن التسليم.",
     "صحّح تاريخ القيد ليطابق فترة الخدمة."),

    ("IFRS-LSE", "compliance", "compliance", "specialized", "low", False, False,
     "apps.rule_engine.rules.invoice.period_close_rules.LeaseClassificationRule",
     "Lease Classification (IFRS 16)", "تصنيف عقد الإيجار (IFRS 16)",
     "Classify lease as operating or finance per IFRS 16 criteria.",
     "Lease classification recorded.", "تم تسجيل تصنيف الإيجار.",
     "راجع التصنيف قبل القيد المحاسبي."),

    # ── SOCPA standards mapping ──────────────────────────────────────────────
    ("SOCPA-200", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.socpa_rules.AuditorIndependenceRule",
     "Auditor Independence (SOCPA 200)", "استقلالية المدقق (SOCPA 200)",
     "The reviewer must be independent of the user who uploaded the document.",
     "Auditor independence violated.", "إخلال باستقلالية المدقق.",
     "أعد تعيين المراجعة لمستخدم مختلف."),

    ("SOCPA-500", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.invoice.socpa_rules.SufficientEvidenceRule",
     "Sufficient Audit Evidence (SOCPA 500)", "كفاية أدلة التدقيق (SOCPA 500)",
     "Audit evidence (text, OCR confidence, line items, audit trail) must be sufficient.",
     "Insufficient audit evidence.", "أدلة التدقيق غير كافية.",
     "اجمع الأدلة الناقصة قبل إصدار الرأي."),

    ("SOCPA-450", "compliance", "compliance", "specialized", "critical", True, False,
     "apps.rule_engine.rules.invoice.socpa_rules.MaterialMisstatementRule",
     "Material Misstatement Risk (SOCPA 450)", "خطر التحريف الجوهري (SOCPA 450)",
     "Three or more high-severity rule failures indicate material misstatement risk.",
     "Material misstatement risk detected.", "خطر تحريف جوهري.",
     "لا يجوز اعتماد المستند قبل معالجة الفشل الحرج."),

    ("SOCPA-700", "compliance", "compliance", "specialized", "low", False, False,
     "apps.rule_engine.rules.invoice.socpa_rules.AuditOpinionBasisRule",
     "Audit Opinion Basis (SOCPA 700)", "أساس رأي المدقق (SOCPA 700)",
     "Classifies the supportable audit opinion based on rule outcomes and risk score.",
     "Opinion basis recorded.", "تم تسجيل أساس الرأي.",
     "راجع تصنيف الرأي قبل التوقيع النهائي."),

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

    # ── Internal-control rules (CTL) ──────────────────────────────────────────
    ("CTL-003", "compliance", "compliance", "generic", "high", True, False,
     "apps.rule_engine.rules.invoice.control_rules.BudgetThresholdRule",
     "Budget Threshold Exceeded", "تجاوز سقف الميزانية المخصصة",
     "Invoice amount exceeds the configured department / cost-center budget.",
     "Amount exceeds budget threshold.", "المبلغ يتجاوز سقف الميزانية.",
     "احصل على موافقة استثنائية أو راجع تخصيص الميزانية."),

    ("CTL-004", "compliance", "compliance", "generic", "high", True, False,
     "apps.rule_engine.rules.invoice.control_rules.PostApprovalLockRule",
     "Post-Approval Modification", "تعديل بعد الاعتماد",
     "Documents must not be modified after approval without re-approval.",
     "Document was modified after approval.", "تم تعديل المستند بعد اعتماده.",
     "أعد الاعتماد بعد التعديل أو ارجع للنسخة الأصلية."),

    ("CTL-005", "compliance", "compliance", "generic", "critical", True, False,
     "apps.rule_engine.rules.invoice.control_rules.SegregationOfDutiesRule",
     "Segregation of Duties Violation", "إخلال بمبدأ الفصل بين الصلاحيات",
     "The user who uploaded a document must not be the user who approves it.",
     "Same user uploaded and approved.", "نفس المستخدم رفع المستند ووافق عليه.",
     "اطلب الاعتماد من مستخدم مختلف عن الذي رفع المستند."),

    ("CTL-006", "compliance", "compliance", "generic", "medium", False, False,
     "apps.rule_engine.rules.invoice.control_rules.AuditTrailCompletenessRule",
     "Incomplete Audit Trail", "سلسلة تدقيق غير مكتملة",
     "Required audit-trail events (uploaded, processed) must be present.",
     "Audit trail is incomplete.", "سلسلة التدقيق غير مكتملة.",
     "أكمل أحداث التدقيق المفقودة قبل الاعتماد النهائي."),

    # ── Document quality / authenticity rules (DOC) ───────────────────────────
    ("DOC-001", "validation", "validation", "generic", "medium", False, False,
     "apps.rule_engine.rules.invoice.document_quality_rules.LowOCRConfidenceRule",
     "Low OCR Confidence", "ثقة منخفضة في التعرّف الضوئي",
     "OCR confidence below threshold means downstream extraction is unreliable.",
     "OCR confidence is below threshold.", "ثقة التعرّف الضوئي أقل من الحد المطلوب.",
     "أعد رفع نسخة أوضح من المستند."),

    ("DOC-002", "validation", "validation", "generic", "low", False, False,
     "apps.rule_engine.rules.invoice.document_quality_rules.HandwrittenDocumentRule",
     "Handwritten / Low-Quality Scan", "مستند بخط اليد أو مسح منخفض الجودة",
     "Handwritten or poorly-scanned documents need extra manual scrutiny.",
     "Document appears handwritten or low quality.", "المستند بخط اليد أو منخفض الجودة.",
     "تأكّد من أن المستند مطبوع وواضح."),

    ("DOC-003", "anomaly", "anomaly", "generic", "critical", True, False,
     "apps.rule_engine.rules.invoice.document_quality_rules.DocumentAlterationRule",
     "Document Alterations Detected", "اشتباه في تعديل المستند",
     "Visual evidence of tampering (whitening, ink mismatch, overwriting) is a fraud red flag.",
     "Document appears altered.", "اشتباه في تعديل المستند.",
     "صعّد المستند للمدقق الرئيسي وتحقّق من الأصل لدى الجهة المصدرة."),

    # ── Anomaly rules (ANO) ───────────────────────────────────────────────────
    ("ANO-02", "anomaly", "anomaly", "generic", "medium", False, False,
     "apps.rule_engine.rules.invoice.anomaly_rules.NewVendorRule",
     "First-Time Vendor", "مورّد جديد لم يسبق التعامل معه",
     "First-time vendors are an elevated fraud-risk vector.",
     "Vendor has no prior invoices.", "المورّد لم يسبق التعامل معه.",
     "تحقّق من شرعية المورّد قبل اعتماد الفاتورة."),

    ("ANO-03", "anomaly", "anomaly", "generic", "low", False, False,
     "apps.rule_engine.rules.invoice.anomaly_rules.RoundNumberRule",
     "Round-Number Amount", "مبلغ مدوّر بشكل مريب",
     "Round-number invoices (multiples of 1000 SAR with no fractions) are unusual once VAT is applied.",
     "Amount is suspiciously round.", "المبلغ مدوّر بشكل غير اعتيادي.",
     "تحقّق من تفاصيل المبلغ وحساب الضريبة."),

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

    # ── Invoice Mandatory Rules ───────────────────────────────────────────────
    ("VAT-03", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.invoice_mandatory_rules.VATReverseChargeRule",
     "VAT Reverse Charge Mechanism", "آلية الاحتساب العكسي للضريبة",
     "B2B cross-border transactions may require reverse-charge VAT treatment.",
     "Reverse charge VAT indicator missing or inconsistent.", "مؤشر الاحتساب العكسي للضريبة مفقود أو غير متسق.",
     "تحقق من تطبيق آلية الاحتساب العكسي للمعاملات عبر الحدود."),

    ("INV-M01", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.invoice_mandatory_rules.InvoiceVendorNameRule",
     "Invoice Vendor Name Present", "وجود اسم المورد في الفاتورة",
     "Invoice must contain the vendor/supplier name.",
     "Vendor name is missing from invoice.", "اسم المورد مفقود من الفاتورة.",
     "أضف اسم المورد أو المُورِّد إلى الفاتورة."),

    ("INV-M02", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.invoice_mandatory_rules.InvoiceVendorVATRule",
     "Invoice Vendor VAT Number Present", "وجود الرقم الضريبي للمورد في الفاتورة",
     "Invoice must contain a valid vendor VAT registration number.",
     "Vendor VAT number is missing or invalid.", "الرقم الضريبي للمورد مفقود أو غير صحيح.",
     "أضف الرقم الضريبي الصحيح للمورد."),

    ("INV-M03", "compliance", "validation", "specialized", "medium", False, False,
     "apps.rule_engine.rules.invoice.invoice_mandatory_rules.InvoiceDueDateRule",
     "Invoice Due Date Present", "وجود تاريخ الاستحقاق في الفاتورة",
     "Invoice should specify a due date for payment.",
     "Invoice due date is missing.", "تاريخ استحقاق الفاتورة مفقود.",
     "أضف تاريخ الاستحقاق للفاتورة."),

    ("INV-M04", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.invoice.invoice_mandatory_rules.InvoiceLineItemsPresenceRule",
     "Invoice Line Items Present", "وجود بنود تفصيلية في الفاتورة",
     "Invoice must contain at least one line item.",
     "Invoice has no line items.", "الفاتورة لا تحتوي على بنود تفصيلية.",
     "أضف بنود تفصيلية للفاتورة."),

    ("INV-M05", "financial_logic", "validation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.invoice.invoice_mandatory_rules.InvoiceLineItemTotalRule",
     "Invoice Line Items Total Matches Header", "مجموع بنود الفاتورة يطابق الإجمالي",
     "Sum of invoice line item amounts must match the declared total.",
     "Invoice line items total does not match header total.", "مجموع بنود الفاتورة لا يطابق الإجمالي.",
     "راجع مجموع البنود وصحح الإجمالي المُعلن."),

    ("INV-M06", "data_integrity", "anomaly", "specialized", "medium", False, False,
     "apps.rule_engine.rules.invoice.invoice_mandatory_rules.InvoiceSequenceGapRule",
     "Invoice Sequence Gap Detected", "ثغرة في تسلسل أرقام الفواتير",
     "Missing invoice numbers in the sequence may indicate deleted or concealed documents.",
     "Invoice sequence gaps detected.", "ثغرات في تسلسل أرقام الفواتير.",
     "تحقق من الفواتير المفقودة في التسلسل."),

    # ── Purchase Order Mandatory Rules ────────────────────────────────────────
    ("PO-M01", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.purchase_order.po_mandatory_rules.POBudgetAvailabilityRule",
     "PO Exceeds Available Budget", "أمر الشراء يتجاوز الميزانية المتاحة",
     "Purchase orders must not exceed the available budget for the cost center.",
     "PO amount exceeds available budget.", "مبلغ أمر الشراء يتجاوز الميزانية المتاحة.",
     "احصل على موافقة ميزانية إضافية قبل إصدار أمر الشراء."),

    ("PO-M02", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.purchase_order.po_mandatory_rules.POAuthorizationLevelRule",
     "PO Authorization Level Insufficient", "مستوى تفويض أمر الشراء غير كافٍ",
     "PO approver must have sufficient authorization level for the amount.",
     "PO approver authorization level is insufficient.", "مستوى تفويض المعتمد غير كافٍ لهذا المبلغ.",
     "احصل على موافقة من مسؤول ذي صلاحية مناسبة."),

    ("PO-M03", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.purchase_order.po_mandatory_rules.POThreeQuotationsRule",
     "Three Quotations Not Obtained", "عدم الحصول على ثلاثة عروض أسعار",
     "POs above the threshold require at least three competitive quotations.",
     "Three quotations requirement not satisfied.", "لم يتم استيفاء شرط الحصول على ثلاثة عروض أسعار.",
     "احصل على ثلاثة عروض أسعار منافسة على الأقل."),

    ("PO-M04", "compliance", "anomaly", "specialized", "high", True, False,
     "apps.rule_engine.rules.purchase_order.po_mandatory_rules.POSplittingRule",
     "PO Splitting to Avoid Threshold", "تجزئة أوامر الشراء لتجنب الحد",
     "Multiple small POs to the same vendor near a threshold may indicate intentional splitting.",
     "Potential PO splitting detected.", "اكتشاف احتمال تجزئة أوامر الشراء.",
     "راجع أوامر الشراء الأخيرة لنفس المورد وحدد ما إذا كانت ينبغي دمجها."),

    ("PO-M05", "compliance", "validation", "specialized", "medium", False, False,
     "apps.rule_engine.rules.purchase_order.po_mandatory_rules.PODeliveryDateRule",
     "PO Delivery Date Missing or Past", "تاريخ تسليم أمر الشراء مفقود أو منتهٍ",
     "PO must have a future delivery date.",
     "PO delivery date is missing or in the past.", "تاريخ التسليم مفقود أو في الماضي.",
     "أضف تاريخ تسليم صحيح لأمر الشراء."),

    ("PO-M07", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.purchase_order.po_mandatory_rules.POCompletenessRule",
     "PO Missing Required Fields", "حقول إلزامية مفقودة في أمر الشراء",
     "PO must have all mandatory fields: vendor, amount, items, and approver.",
     "PO is missing required fields.", "أمر الشراء يفتقر إلى حقول إلزامية.",
     "استكمل جميع الحقول الإلزامية في أمر الشراء."),

    # ── GRN Rules ─────────────────────────────────────────────────────────────
    ("GRN-M01", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.grn.grn_rules.GRNNumberPresentRule",
     "GRN Number Present", "وجود رقم إشعار الاستلام",
     "Goods Receipt Note must have a reference number.",
     "GRN number is missing.", "رقم إشعار الاستلام مفقود.",
     "أضف رقم مرجعي فريد لإشعار الاستلام."),

    ("GRN-M02", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.grn.grn_rules.GRNDatePresentRule",
     "GRN Date Present", "وجود تاريخ إشعار الاستلام",
     "Goods Receipt Note must have a receipt date.",
     "GRN date is missing.", "تاريخ إشعار الاستلام مفقود.",
     "أضف تاريخ الاستلام."),

    ("GRN-M03", "compliance", "compliance", "specialized", "high", True, True,
     "apps.rule_engine.rules.grn.grn_rules.GRNLinkedToPORule",
     "GRN Not Linked to Purchase Order", "إشعار الاستلام غير مرتبط بأمر شراء",
     "Every GRN must reference a valid purchase order.",
     "GRN has no linked purchase order.", "إشعار الاستلام لا يحمل رابطاً لأمر شراء.",
     "اربط إشعار الاستلام بأمر الشراء المقابل."),

    ("GRN-M04", "financial_logic", "validation", "specialized", "critical", True, False,
     "apps.rule_engine.rules.grn.grn_rules.GRNQuantityMatchRule",
     "GRN Quantity Mismatch with PO", "تعارض الكميات بين إشعار الاستلام وأمر الشراء",
     "Received quantity must match ordered quantity within tolerance.",
     "Quantity mismatch detected.", "تعارض في الكميات المستلمة والمطلوبة.",
     "راجع الكميات المستلمة مع أمر الشراء."),

    ("GRN-M05", "compliance", "anomaly", "specialized", "high", True, False,
     "apps.rule_engine.rules.grn.grn_rules.GRNRejectionRateRule",
     "Excessive Goods Rejection Rate", "معدل رفض مفرط للبضاعة المستلمة",
     "Rejection rate above threshold indicates quality or fraud issues.",
     "Excessive goods rejection rate detected.", "معدل رفض مفرط للبضاعة.",
     "راجع أسباب الرفض مع المورد وافتح تحقيقاً."),

    ("GRN-M06", "financial_logic", "anomaly", "specialized", "high", True, False,
     "apps.rule_engine.rules.grn.grn_rules.GRNPriceDeviationRule",
     "GRN Price Deviation from PO", "انحراف السعر في إشعار الاستلام عن أمر الشراء",
     "Invoice price must match PO price within tolerance.",
     "Price deviation detected between GRN and PO.", "انحراف في الأسعار بين إشعار الاستلام وأمر الشراء.",
     "راجع الأسعار مع المورد وحدد مصدر الانحراف."),

    ("GRN-M07", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.grn.grn_rules.GRNDeliveryOverdueRule",
     "GRN Delivery Overdue", "تأخر تسليم البضاعة",
     "Delivery should occur by the PO delivery date.",
     "Delivery is overdue.", "تأخر في التسليم.",
     "تواصل مع المورد بشأن التأخر في التسليم."),

    ("GRN-M08", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.grn.grn_rules.GRNQualityInspectionRule",
     "GRN Quality Inspection Not Performed", "لم يتم إجراء فحص الجودة",
     "Quality inspection must be performed and documented.",
     "Quality inspection not completed.", "لم يتم استكمال فحص الجودة.",
     "أكمل فحص الجودة ووثّق النتائج."),

    ("GRN-M09", "financial_logic", "validation", "specialized", "high", True, True,
     "apps.rule_engine.rules.grn.grn_rules.GRNInvoiceAmountMatchRule",
     "GRN Invoice Amount Mismatch", "تعارض مبلغ الفاتورة مع إشعار الاستلام",
     "Invoice amount must match GRN amount within tolerance.",
     "Invoice amount does not match GRN.", "مبلغ الفاتورة لا يطابق إشعار الاستلام.",
     "راجع مبلغ الفاتورة مقابل إشعار الاستلام."),

    ("GRN-M10", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.grn.grn_rules.GRNApproverPresentRule",
     "GRN Missing Approver", "إشعار الاستلام لا يحمل توقيع موافق",
     "GRN must be approved by an authorized person.",
     "GRN has no approver.", "إشعار الاستلام لا يحمل موافقة.",
     "احصل على موافقة مفوَّضة على إشعار الاستلام."),

    # ── Payment Voucher Rules ─────────────────────────────────────────────────
    ("PMT-M01", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.payment.payment_rules.PaymentNumberPresentRule",
     "Payment Voucher Number Present", "وجود رقم سند الصرف",
     "Payment voucher must have a unique reference number.",
     "Payment number is missing.", "رقم سند الصرف مفقود.",
     "أضف رقماً مرجعياً فريداً لسند الصرف."),

    ("PMT-M02", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.payment.payment_rules.PaymentDatePresentRule",
     "Payment Date Present", "وجود تاريخ سند الصرف",
     "Payment voucher must have a payment date.",
     "Payment date is missing.", "تاريخ الصرف مفقود.",
     "أضف تاريخ الصرف."),

    ("PMT-M03", "compliance", "compliance", "specialized", "high", True, True,
     "apps.rule_engine.rules.payment.payment_rules.PaymentLinkedToInvoiceRule",
     "Payment Not Linked to Invoice", "سند الصرف غير مرتبط بفاتورة",
     "Every payment voucher should reference a valid invoice.",
     "Payment has no linked invoice.", "سند الصرف لا يحمل رابطاً لفاتورة.",
     "اربط سند الصرف بالفاتورة المقابلة."),

    ("PMT-M04", "data_integrity", "anomaly", "specialized", "critical", True, False,
     "apps.rule_engine.rules.payment.payment_rules.DuplicatePaymentRule",
     "Duplicate Payment Detected", "اكتشاف دفع مزدوج",
     "Same invoice must not be paid twice.",
     "Potential duplicate payment detected.", "اكتشاف احتمال دفع مزدوج.",
     "تحقق من سجلات الدفع لنفس الفاتورة فوراً."),

    ("PMT-M05", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.payment.payment_rules.PaymentApprovalRule",
     "Payment Missing Approval", "سند الصرف لا يحمل موافقة",
     "Payment vouchers must be approved before processing.",
     "Payment has no approver.", "سند الصرف لا يحمل موافقة.",
     "احصل على موافقة مفوَّضة على سند الصرف."),

    ("PMT-M06", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.payment.payment_rules.PaymentExceedsThresholdRule",
     "Payment Exceeds Authorization Threshold", "سند الصرف يتجاوز حد التفويض",
     "Large payments require higher authorization level.",
     "Payment exceeds authorization threshold.", "مبلغ الصرف يتجاوز حد التفويض.",
     "احصل على موافقة من مستوى تفويض أعلى."),

    ("PMT-M07", "compliance", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.payment.payment_rules.PaymentIBANFormatRule",
     "Payment IBAN Format Invalid", "صيغة IBAN في سند الصرف غير صحيحة",
     "Payment IBAN must match Saudi format: SA + 22 characters.",
     "IBAN format is invalid.", "صيغة IBAN غير صحيحة.",
     "تحقق من رقم الآيبان مع البنك."),

    ("PMT-M08", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.payment.payment_rules.AdvancePaymentClearanceRule",
     "Advance Payment Not Cleared", "سلفة لم يتم تسويتها",
     "Advance payments must be cleared against invoices.",
     "Advance payment not cleared.", "السلفة لم يتم تسويتها.",
     "سوِّ السلفة مقابل الفاتورة المقابلة."),

    ("PMT-M09", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.payment.payment_rules.LatePaymentRule",
     "Late Payment Detected", "دفع متأخر",
     "Payments should be made before the invoice due date.",
     "Payment is late.", "الدفع متأخر عن تاريخ الاستحقاق.",
     "راجع دورة الدفع وعالج أسباب التأخير."),

    ("PMT-M10", "financial_logic", "validation", "specialized", "critical", True, True,
     "apps.rule_engine.rules.payment.payment_rules.PaymentAmountMatchRule",
     "Payment Amount Mismatches Invoice", "مبلغ سند الصرف لا يطابق الفاتورة",
     "Payment amount must match the linked invoice amount.",
     "Payment amount does not match invoice.", "مبلغ الصرف لا يطابق مبلغ الفاتورة.",
     "راجع مبلغ سند الصرف مقابل الفاتورة المرتبطة."),

    # ── Bank Statement Extended Rules ─────────────────────────────────────────
    ("BNK-M02", "anomaly", "anomaly", "specialized", "critical", True, False,
     "apps.rule_engine.rules.bank_statement.balance_reconciliation_rule.BenfordsLawBankRule",
     "Bank Transactions Fail Benford's Law", "المعاملات البنكية تخالف قانون بنفورد",
     "Transaction amounts should follow Benford's Law distribution.",
     "Benford's Law anomaly detected in bank transactions.", "شذوذ في توزيع أرقام المعاملات البنكية (قانون بنفورد).",
     "افحص المعاملات البنكية للتأكد من عدم وجود تلاعب."),

    ("BNK-M03", "anomaly", "anomaly", "specialized", "medium", False, False,
     "apps.rule_engine.rules.bank_statement.balance_reconciliation_rule.RoundAmountClusterRule",
     "Suspicious Round Amount Clustering", "تجمّع مريب للمبالغ المستديرة",
     "Unusually high proportion of round-number transactions indicates fabrication risk.",
     "Round amount clustering detected.", "تجمّع مبالغ مستديرة.",
     "راجع المعاملات ذات المبالغ المستديرة."),

    ("BNK-M04", "anomaly", "anomaly", "specialized", "medium", False, False,
     "apps.rule_engine.rules.bank_statement.balance_reconciliation_rule.WeekendTransactionRule",
     "Suspicious Weekend Bank Transactions", "معاملات بنكية مريبة في عطلة نهاية الأسبوع",
     "Multiple weekend transactions carry elevated fraud risk.",
     "Weekend transaction clustering detected.", "تجمّع معاملات في نهاية الأسبوع.",
     "راجع المعاملات التي تمت في عطلة نهاية الأسبوع."),

    ("BNK-M05", "anomaly", "anomaly", "specialized", "high", True, False,
     "apps.rule_engine.rules.bank_statement.balance_reconciliation_rule.LateNightTransactionRule",
     "Late Night Bank Transactions", "معاملات بنكية في وقت متأخر من الليل",
     "Multiple late-night transactions (23:00–05:00) are a fraud indicator.",
     "Late-night transactions detected.", "معاملات بنكية في ساعات الليل المتأخرة.",
     "راجع المعاملات التي تمت في ساعات الليل."),

    # ── AI Risk Rules ─────────────────────────────────────────────────────────
    ("AI-R01", "data_integrity", "validation", "generic", "high", True, False,
     "apps.rule_engine.rules.ai_risk.ai_risk_rules.LowOCRConfidenceRule",
     "Low OCR Confidence Score", "انخفاض درجة ثقة قراءة النص الآلي",
     "AI OCR confidence below threshold indicates unreliable extraction.",
     "Low OCR confidence detected.", "انخفاض درجة ثقة استخراج النص.",
     "أعد رفع المستند بجودة أعلى أو أدخل البيانات يدوياً."),

    ("AI-R02", "data_integrity", "anomaly", "generic", "medium", False, False,
     "apps.rule_engine.rules.ai_risk.ai_risk_rules.HandwrittenDocumentRule",
     "Handwritten Document Detected", "اكتشاف مستند مكتوب بخط اليد",
     "Handwritten documents require manual verification.",
     "Handwritten document detected.", "اكتشاف مستند مكتوب بخط اليد.",
     "تحقق يدوياً من محتوى المستند المكتوب بخط اليد."),

    ("AI-R03", "data_integrity", "anomaly", "generic", "critical", True, False,
     "apps.rule_engine.rules.ai_risk.ai_risk_rules.DocumentAlterationRule",
     "Document Alteration Detected", "اكتشاف تعديل في المستند",
     "AI analysis indicates potential document tampering or alteration.",
     "Document alteration indicators detected.", "مؤشرات تعديل في المستند.",
     "احتفظ بالمستند الأصلي وأبلغ المسؤول عن الامتثال."),

    ("AI-R04", "data_integrity", "validation", "generic", "medium", False, False,
     "apps.rule_engine.rules.ai_risk.ai_risk_rules.DocumentClarityRule",
     "Document Clarity Insufficient", "وضوح المستند غير كافٍ",
     "Document image must be clear enough for reliable extraction.",
     "Document clarity is insufficient.", "وضوح المستند غير كافٍ للاستخراج الموثوق.",
     "أعد رفع المستند بجودة صورة أعلى."),

    ("AI-R05", "anomaly", "anomaly", "generic", "high", True, False,
     "apps.rule_engine.rules.ai_risk.ai_risk_rules.BenfordsLawRule",
     "Document Amounts Fail Benford's Law", "مبالغ المستند تخالف قانون بنفورد",
     "Amount distribution should follow Benford's Law.",
     "Benford's Law anomaly detected.", "شذوذ وفق قانون بنفورد.",
     "افحص توزيع مبالغ المستند للتحقق من صحتها."),

    ("AI-R06", "anomaly", "anomaly", "generic", "high", True, False,
     "apps.rule_engine.rules.ai_risk.ai_risk_rules.HighRiskScoreRule",
     "AI Risk Score Exceeds Threshold", "درجة المخاطر الذكاء الاصطناعي تتجاوز الحد",
     "Overall AI risk score above threshold requires human review.",
     "High AI risk score detected.", "درجة مخاطر عالية من الذكاء الاصطناعي.",
     "افحص المستند يدوياً بسبب درجة المخاطر المرتفعة."),

    ("AI-R07", "data_integrity", "validation", "generic", "high", True, False,
     "apps.rule_engine.rules.ai_risk.ai_risk_rules.EmptyAIExtractionRule",
     "AI Extraction Returned Empty Result", "الاستخراج الذكي أعاد نتيجة فارغة",
     "AI extraction must return at least some recognized fields.",
     "AI extraction returned no usable data.", "استخراج الذكاء الاصطناعي لم يُعيد بيانات قابلة للاستخدام.",
     "تحقق من جودة المستند أو أدخل البيانات يدوياً."),

    ("AI-R08", "data_integrity", "anomaly", "generic", "critical", True, False,
     "apps.rule_engine.rules.ai_risk.ai_risk_rules.DuplicateContentFingerprintRule",
     "Duplicate Content Fingerprint Detected", "اكتشاف بصمة محتوى مكررة",
     "Documents with identical content fingerprints indicate duplication.",
     "Duplicate content fingerprint detected.", "اكتشاف بصمة محتوى مكررة.",
     "تحقق من المستندات المكررة وأزل النسخ الزائدة."),

    # ── Security Rules ────────────────────────────────────────────────────────
    ("SEC-M01", "compliance", "compliance", "generic", "critical", True, False,
     "apps.rule_engine.rules.security.security_rules.SelfApprovalSecurityRule",
     "Self-Approval Security Violation", "انتهاك أمني: موافقة الشخص على عمله",
     "Segregation of duties: uploader and approver must be different persons.",
     "Self-approval violation detected.", "انتهاك مبدأ الفصل بين المهام.",
     "يجب أن يكون المقدِّم والمعتمد شخصين مختلفين."),

    ("SEC-M02", "compliance", "compliance", "generic", "high", True, False,
     "apps.rule_engine.rules.security.security_rules.HighValueDualAuthorizationRule",
     "High-Value Document Missing Dual Authorization", "مستند ذو قيمة عالية يفتقر للتفويض المزدوج",
     "Documents above the dual-authorization threshold need two approvers.",
     "Dual authorization missing for high-value document.", "التفويض المزدوج مفقود لمستند ذو قيمة عالية.",
     "احصل على موافقة ثانية لاستكمال متطلب التفويض المزدوج."),

    ("SEC-M03", "compliance", "compliance", "generic", "critical", True, False,
     "apps.rule_engine.rules.security.security_rules.BlockedVendorRule",
     "Transaction with Blocked or Sanctioned Vendor", "معاملة مع مورد محظور أو خاضع لعقوبات",
     "Vendor must not appear on the organization's blocked/sanctioned list.",
     "Blocked or sanctioned vendor detected.", "مورد محظور أو خاضع لعقوبات.",
     "أوقف المعاملة وأبلغ مسؤول الامتثال فوراً."),

    ("SEC-M04", "anomaly", "anomaly", "generic", "medium", False, False,
     "apps.rule_engine.rules.security.security_rules.WeekendSubmissionRule",
     "Weekend / Off-Hours Document Submission", "تقديم مستند في عطلة نهاية الأسبوع",
     "Documents submitted on weekends carry elevated fraud risk.",
     "Weekend submission detected.", "تقديم مستند في عطلة نهاية الأسبوع.",
     "راجع المستندات المقدَّمة في عطلة نهاية الأسبوع."),

    ("SEC-M05", "compliance", "compliance", "generic", "critical", True, False,
     "apps.rule_engine.rules.security.security_rules.EditAfterApprovalRule",
     "Document Edited After Approval", "تعديل المستند بعد الموافقة",
     "Documents must not be modified after they have been approved.",
     "Post-approval modification detected.", "تم تعديل المستند بعد الموافقة.",
     "أوقف أي تعديلات وافتح قضية تدقيق."),

    ("SEC-M06", "compliance", "compliance", "generic", "high", True, False,
     "apps.rule_engine.rules.security.security_rules.AuditTrailCompletenessRule",
     "Audit Trail Incomplete or Missing", "سجل التدقيق غير مكتمل أو مفقود",
     "Document must have a complete audit trail.",
     "Audit trail is incomplete or missing.", "سجل التدقيق غير مكتمل أو مفقود.",
     "تأكد من تفعيل وتسجيل أحداث المراجعة لهذا المستند."),

    # ── Payroll Extended Rules ────────────────────────────────────────────────
    ("PAY-M02", "anomaly", "anomaly", "specialized", "high", True, False,
     "apps.rule_engine.rules.payroll.net_salary_arithmetic_rule.SalarySpikeRule",
     "Unexplained Salary Spike Detected", "ارتفاع مفاجئ غير مبرر في الراتب",
     "Detects abnormal salary increases (>30%) without documented justification.",
     "Unexplained salary spike detected.", "ارتفاع مفاجئ غير مبرر في الراتب.",
     "وثّق مبرر الزيادة في الراتب أو راجع مع الموارد البشرية."),

    ("PAY-M05", "data_integrity", "validation", "specialized", "high", True, False,
     "apps.rule_engine.rules.payroll.net_salary_arithmetic_rule.EmployeeCountConsistencyRule",
     "Employee Headcount Inconsistency", "تناقض في عدد الموظفين المُدرجين",
     "Headcount in payroll list must match the declared employee_count field.",
     "Employee headcount inconsistency detected.", "تناقض في عدد الموظفين.",
     "راجع كشف الرواتب وتأكد من تطابق عدد الموظفين."),

    ("PAY-M06", "compliance", "compliance", "specialized", "critical", True, True,
     "apps.rule_engine.rules.payroll.net_salary_arithmetic_rule.PayrollPeriodOverlapRule",
     "Duplicate Payroll Period Detected", "تكرار فترة صرف رواتب",
     "Two payroll sheets must not cover the same period for the same organization.",
     "Overlapping payroll period detected.", "تداخل في فترات صرف الرواتب.",
     "تحقق من الكشوف المتداخلة وأزل التكرار لمنع الصرف المزدوج."),

    # ── Expense Extended Rules ────────────────────────────────────────────────
    ("EXP-M03", "data_integrity", "anomaly", "specialized", "high", True, False,
     "apps.rule_engine.rules.expense.expense_rules.DuplicateExpenseClaimRule",
     "Duplicate Expense Claim", "مطالبة مصروفات مكررة",
     "Same expense must not be claimed multiple times.",
     "Duplicate expense claim detected.", "اكتشاف مطالبة مصروفات مكررة.",
     "تحقق من المطالبات السابقة وأزل التكرار."),

    ("EXP-M04", "compliance", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.expense.expense_rules.ExpenseSubmissionDeadlineRule",
     "Expense Submitted After Deadline", "تقديم مصروف بعد الموعد النهائي",
     "Expense claims must be submitted within policy deadline.",
     "Late expense submission detected.", "تقديم مصروف متأخر عن الموعد النهائي.",
     "قدّم مطالبات المصروفات في الوقت المحدد وفق السياسة."),

    ("EXP-M05", "anomaly", "anomaly", "specialized", "high", True, False,
     "apps.rule_engine.rules.expense.expense_rules.SplitTransactionRule",
     "Split Transaction to Avoid Policy Limit", "تقسيم المعاملة لتجنب حد السياسة",
     "Multiple small expenses in same category on same day may indicate deliberate splitting.",
     "Potential split transaction detected.", "اكتشاف احتمال تقسيم معاملة.",
     "راجع المصروفات المتعددة في نفس التاريخ والفئة."),

    # ── Cross-Document Rules ──────────────────────────────────────────────────
    ("CDR-01", "reconciliation", "reconciliation", "cross_document", "critical", True, True,
     "apps.rule_engine.rules.cross_document.invoice_po_match_rule.InvoicePOMatchRule",
     "Invoice–PO Amount Mismatch", "تعارض مبلغ الفاتورة مع أمر الشراء",
     "Invoice amount must match linked PO within tolerance.",
     "Invoice-PO amount mismatch detected.", "تعارض مبالغ الفاتورة وأمر الشراء.",
     "راجع أمر الشراء والفاتورة وحدد مصدر الفارق."),

    ("CDR-02", "reconciliation", "reconciliation", "cross_document", "critical", True, True,
     "apps.rule_engine.rules.cross_document.three_way_match_rule.ThreeWayMatchRule",
     "Three-Way Match (PO ↔ Invoice ↔ GRN)", "المطابقة الثلاثية (أمر الشراء ↔ الفاتورة ↔ مذكرة الاستلام)",
     "Quantity, unit price, total amount, and vendor must be consistent across PO, Invoice, and GRN.",
     "Three-way match mismatch detected.", "تعارض في المطابقة الثلاثية.",
     "راجع أمر الشراء والفاتورة ومذكرة الاستلام وحدد مصدر الفارق."),

    ("CDR-03", "reconciliation", "reconciliation", "cross_document", "critical", True, True,
     "apps.rule_engine.rules.cross_document.invoice_po_match_rule.PayrollBankReconciliationRule",
     "Payroll–Bank Transfer Reconciliation", "تسوية إجمالي الرواتب مع التحويل البنكي",
     "Total payroll must match the bank transfer amount.",
     "Payroll and bank transfer amounts do not match.", "إجمالي الرواتب لا يطابق التحويل البنكي.",
     "راجع إجمالي الرواتب والتحويل البنكي وحدد مصدر الفارق."),

    # ── GAAP Core Rules ───────────────────────────────────────────────────────
    ("GAAP-COMP-001", "compliance", "validation", "generic", "high", True, False,
     "apps.rule_engine.rules.gaap.categories.completeness.GAAPCompletenessCoreFieldsRule",
     "GAAP Completeness: Core Fields", "اكتمال الحقول الأساسية وفق GAAP",
     "Core accounting records must include mandatory completeness fields.",
     "GAAP completeness core fields check failed.", "فشل التحقق من اكتمال الحقول الأساسية وفق GAAP.",
     "استكمل الحقول الأساسية قبل اعتماد المستند."),

    ("GAAP-CUT-001", "compliance", "compliance", "generic", "high", True, False,
     "apps.rule_engine.rules.gaap.categories.cutoff.GAAPCutoffPeriodRule",
     "GAAP Cutoff Period", "فترة القطع المحاسبي وفق GAAP",
     "Transactions should be recognized in the proper accounting period.",
     "GAAP cutoff period check failed.", "فشل التحقق من فترة القطع المحاسبي وفق GAAP.",
     "راجع تاريخ القيد وتأكد من الفترة المحاسبية الصحيحة."),

    ("GAAP-DOC-001", "compliance", "compliance", "generic", "high", True, False,
     "apps.rule_engine.rules.gaap.categories.documentation.GAAPDocumentationSupportRule",
     "GAAP Supporting Documentation", "التوثيق الداعم وفق GAAP",
     "Material transactions must have supporting documentation.",
     "GAAP supporting documentation check failed.", "فشل التحقق من التوثيق الداعم وفق GAAP.",
     "أرفق المستندات الداعمة للمعاملات الجوهرية."),

    ("GAAP-CLS-001", "financial_logic", "validation", "specialized", "medium", False, False,
     "apps.rule_engine.rules.gaap.categories.classification.GAAPClassificationCapexOpexRule",
     "GAAP Classification: Capex vs Opex", "تصنيف CAPEX/OPEX وفق GAAP",
     "Transactions should be classified correctly between capital and operating expenses.",
     "GAAP classification check failed.", "فشل التحقق من التصنيف وفق GAAP.",
     "راجع تصنيف العملية بين مصروف تشغيلي ومصروف رأسمالي."),

    ("GAAP-REV-001", "compliance", "compliance", "specialized", "high", True, False,
     "apps.rule_engine.rules.gaap.categories.recognition.GAAPRevenueRecognitionRule",
     "GAAP Revenue Recognition", "الاعتراف بالإيراد وفق GAAP",
     "Revenue should be recognized in line with GAAP recognition principles.",
     "GAAP revenue recognition check failed.", "فشل التحقق من الاعتراف بالإيراد وفق GAAP.",
     "راجع توقيت الاعتراف بالإيراد وفق المعيار المحاسبي."),

    ("GAAP-EXP-001", "financial_logic", "compliance", "specialized", "medium", False, False,
     "apps.rule_engine.rules.gaap.categories.recognition.GAAPExpenseMatchingRule",
     "GAAP Expense Matching", "مبدأ مقابلة المصروفات وفق GAAP",
     "Expenses should be matched to the related period/revenue where applicable.",
     "GAAP expense matching check failed.", "فشل التحقق من مبدأ مقابلة المصروفات وفق GAAP.",
     "راجع قيد المصروفات وتأكد من ربطها بالفترة الصحيحة."),

    ("GAAP-CONS-001", "compliance", "validation", "generic", "medium", False, False,
     "apps.rule_engine.rules.gaap.categories.consistency.GAAPConsistencyTreatmentRule",
     "GAAP Consistency of Treatment", "اتساق المعالجة المحاسبية وفق GAAP",
     "Similar transactions should be treated consistently over time.",
     "GAAP consistency check failed.", "فشل التحقق من اتساق المعالجة وفق GAAP.",
     "وحّد سياسة المعالجة وطبّقها بشكل متسق على العمليات المماثلة."),
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
      ("CDR-02", "purchase_order", "full", None),
      ("CDR-02", "invoice", "conditional", None),
      ("CDR-02", "goods_receipt", "conditional", None),
      ("CDR-03", "payroll", "full", None),
      ("CDR-03", "bank_statement", "conditional", None)],

    # Invoice mandatory rules
    *[("VAT-03", dt, "full", None) for dt in ["sales_invoice", "purchase_order", "expense"]],
    *[("INV-M01", dt, "full", None) for dt in ["sales_invoice", "purchase_order"]],
    *[("INV-M02", dt, "full", None) for dt in ["sales_invoice", "purchase_order"]],
    ("INV-M03", "sales_invoice", "full", None),
    ("INV-M04", "sales_invoice", "full", None),
    ("INV-M05", "sales_invoice", "full", None),
    ("INV-M06", "sales_invoice", "full", None),

    # PO mandatory rules
    *[("PO-M01", "purchase_order", "full", None),
      ("PO-M02", "purchase_order", "full", None),
      ("PO-M03", "purchase_order", "full", None),
      ("PO-M04", "purchase_order", "full", None),
      ("PO-M05", "purchase_order", "full", None),
      ("PO-M07", "purchase_order", "full", None)],

    # GRN rules
    *[("GRN-M01", "grn", "full", None),
      ("GRN-M02", "grn", "full", None),
      ("GRN-M03", "grn", "full", None),
      ("GRN-M04", "grn", "full", None),
      ("GRN-M05", "grn", "full", None),
      ("GRN-M06", "grn", "full", None),
      ("GRN-M07", "grn", "full", None),
      ("GRN-M08", "grn", "full", None),
      ("GRN-M09", "grn", "full", None),
      ("GRN-M10", "grn", "full", None)],

    # Payment voucher rules
    *[("PMT-M01", "payment", "full", None),
      ("PMT-M02", "payment", "full", None),
      ("PMT-M03", "payment", "full", None),
      ("PMT-M04", "payment", "full", None),
      ("PMT-M05", "payment", "full", None),
      ("PMT-M06", "payment", "full", None),
      ("PMT-M07", "payment", "full", None),
      ("PMT-M08", "payment", "full", None),
      ("PMT-M09", "payment", "full", None),
      ("PMT-M10", "payment", "full", None)],

    # Bank statement extended rules
    *[("BNK-M02", "bank_statement", "full", None),
      ("BNK-M03", "bank_statement", "full", None),
      ("BNK-M04", "bank_statement", "full", None),
      ("BNK-M05", "bank_statement", "full", None)],

    # AI risk rules: applied to all document types
    *[("AI-R01", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],
    *[("AI-R02", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],
    *[("AI-R03", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],
    *[("AI-R04", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],
    *[("AI-R05", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "fixed_asset", "sales_receipt", "grn", "payment"]],
    *[("AI-R06", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],
    *[("AI-R07", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],
    *[("AI-R08", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],

    # Security rules: applied to all document types
    *[("SEC-M01", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],
    *[("SEC-M02", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "payroll",
        "expense", "fixed_asset", "grn", "payment"]],
    *[("SEC-M03", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "grn", "payment", "expense"]],
    *[("SEC-M04", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],
    *[("SEC-M05", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment"]],
    *[("SEC-M06", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "bank_statement", "payroll",
        "expense", "tax_return", "fixed_asset", "sales_receipt", "grn", "payment", "other"]],

    # Payroll extended rules
    *[("PAY-M02", "payroll", "full", None),
      ("PAY-M05", "payroll", "full", None),
      ("PAY-M06", "payroll", "full", None)],

    # Expense extended rules
    *[("EXP-M03", "expense", "full", None),
      ("EXP-M04", "expense", "full", None),
      ("EXP-M05", "expense", "full", None)],

    # GAAP core assignments
    *[("GAAP-COMP-001", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "expense", "bank_statement", "other"]],
    *[("GAAP-CUT-001", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "expense", "tax_return", "other"]],
    *[("GAAP-DOC-001", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "expense", "fixed_asset", "other"]],
    *[("GAAP-CLS-001", dt, "full", None) for dt in [
        "expense", "purchase_order", "fixed_asset", "sales_invoice", "other"]],
    *[("GAAP-REV-001", dt, "full", None) for dt in [
        "sales_invoice", "sales_receipt", "other"]],
    *[("GAAP-EXP-001", dt, "full", None) for dt in [
        "expense", "purchase_order", "sales_invoice", "other"]],
    *[("GAAP-CONS-001", dt, "full", None) for dt in [
        "sales_invoice", "purchase_order", "expense", "bank_statement", "other"]],

    # Generic rules extended to new doc types (grn, payment)
    *[("GEN-H01", dt, "full", None) for dt in ["grn", "payment"]],
    *[("GEN-H02", dt, "full", None) for dt in ["grn", "payment"]],
    *[("GEN-H05", dt, "full", None) for dt in ["grn", "payment"]],
    *[("GEN-H06", dt, "full", None) for dt in ["grn", "payment"]],
    *[("GEN-H07", dt, "full", None) for dt in ["grn", "payment"]],
    *[("DUP-04", dt, "full", None) for dt in ["grn", "payment"]],
    *[("CTL-04", dt, "full", None) for dt in ["grn", "payment"]],
    *[("CTL-05", dt, "full", None) for dt in ["grn", "payment"]],
    *[("CTL-06", dt, "full", None) for dt in ["grn", "payment"]],
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
