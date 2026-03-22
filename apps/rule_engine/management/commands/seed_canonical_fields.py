"""
Management command: seed_canonical_fields
Seeds CanonicalFieldDefinition and DocumentTypeFieldMapping from
CanonicalMapper.FALLBACK_MAPPING.
Idempotent — safe to run multiple times.
"""
from django.core.management.base import BaseCommand
from core.services.canonical_mapper import CanonicalMapper


ALL_TYPES = [
    "invoice", "purchase_order", "bank_statement",
    "payroll", "expense_report", "tax_declaration",
    "vat_return", "fixed_asset", "sales_receipt",
]

FIELD_DEFINITIONS = [
    # (field_code, label_en, label_ar, data_type, group, applicable_types, storage, rules, reporting, nullable, sort)
    # ── Identity ──
    ("document_type",     "Document Type",     "نوع المستند",       "string",  "identity",       ["*"],    True,  True,  True,  False, 1),
    ("document_number",   "Document Number",   "رقم المستند",       "string",  "identity",       ["*"],    True,  True,  True,  True,  2),
    ("document_date",     "Document Date",     "تاريخ المستند",     "date",    "identity",       ["*"],    True,  True,  True,  True,  3),
    ("posting_date",      "Posting Date",      "تاريخ الترحيل",     "date",    "identity",       ["*"],    False, False, True,  True,  4),
    ("reference_number",  "Reference Number",  "رقم المرجع",        "string",  "identity",       ["*"],    False, True,  True,  True,  5),
    ("source_filename",   "Source Filename",   "اسم الملف",         "string",  "identity",       ["*"],    True,  False, True,  False, 6),
    ("source_sheet_name", "Sheet Name",        "اسم الورقة",        "string",  "identity",       ["*"],    False, False, True,  True,  7),
    ("company_name",      "Company Name",      "اسم الشركة",        "string",  "identity",       ["*"],    False, True,  True,  True,  8),
    ("branch",            "Branch",            "الفرع",             "string",  "identity",       ["*"],    False, False, True,  True,  9),
    ("department",        "Department",        "القسم",             "string",  "identity",       ["*"],    False, False, True,  True,  10),
    ("cost_center",       "Cost Center",       "مركز التكلفة",      "string",  "identity",       ["*"],    False, True,  True,  True,  11),
    ("account_code",      "Account Code",      "كود الحساب",        "string",  "identity",       ["*"],    False, True,  True,  True,  12),
    ("status",            "Status",            "الحالة",            "string",  "identity",       ["*"],    True,  True,  True,  False, 13),
    ("notes",             "Notes",             "ملاحظات",           "string",  "identity",       ["*"],    False, False, False, True,  14),
    # ── Counterparty ──
    ("vendor_name",       "Vendor Name",       "اسم المورد",        "string",  "counterparty",   ["invoice","purchase_order","expense_report","bank_statement"],      False, True,  True,  True,  1),
    ("vendor_tax_number", "Vendor VAT Number", "رقم ضريبة المورد",  "string",  "counterparty",   ["invoice","purchase_order","sales_receipt"],                        False, True,  True,  True,  2),
    ("vendor_cr_number",  "Vendor CR Number",  "رقم السجل التجاري", "string",  "counterparty",   ["invoice","purchase_order","tax_declaration","vat_return"],         False, False, True,  True,  3),
    ("customer_name",     "Customer Name",     "اسم العميل",        "string",  "counterparty",   ["invoice","sales_receipt"],                                         False, False, True,  True,  4),
    ("customer_tax_number","Customer VAT",     "رقم ضريبة العميل",  "string",  "counterparty",   ["invoice","sales_receipt"],                                         False, True,  True,  True,  5),
    ("employee_id",       "Employee ID",       "رقم الموظف",        "string",  "counterparty",   ["payroll","expense_report"],                                        False, True,  True,  True,  6),
    ("employee_name",     "Employee Name",     "اسم الموظف",        "string",  "counterparty",   ["payroll","expense_report","purchase_order"],                       False, True,  True,  True,  7),
    ("approver_name",     "Approver Name",     "اسم المعتمد",       "string",  "counterparty",   ["purchase_order","expense_report"],                                 False, True,  True,  True,  8),
    ("bank_name",         "Bank Name",         "اسم البنك",         "string",  "counterparty",   ["bank_statement","payroll"],                                        False, False, True,  True,  9),
    # ── Financial ──
    ("currency_code",     "Currency",          "العملة",            "string",  "financial",      ["*"],    True,  True,  True,  False, 1),
    ("subtotal_amount",   "Subtotal",          "المبلغ قبل الضريبة","decimal", "financial",      ["invoice","purchase_order","sales_receipt"],                        False, True,  True,  True,  2),
    ("tax_rate",          "Tax Rate %",        "نسبة الضريبة",      "decimal", "financial",      ["invoice","sales_receipt","tax_declaration","vat_return"],          False, True,  True,  True,  3),
    ("tax_amount",        "Tax Amount",        "مبلغ الضريبة",      "decimal", "financial",      ["invoice","purchase_order","sales_receipt","expense_report"],       False, True,  True,  True,  4),
    ("discount_amount",   "Discount",          "مبلغ الخصم",        "decimal", "financial",      ["invoice"],                                                         False, False, True,  True,  5),
    ("net_amount",        "Net Amount",        "الصافي",            "decimal", "financial",      ["*"],    True,  True,  True,  True,  6),
    ("debit_amount",      "Debit Amount",      "مدين",              "decimal", "financial",      ["bank_statement"],                                                  False, True,  True,  True,  7),
    ("credit_amount",     "Credit Amount",     "دائن",              "decimal", "financial",      ["bank_statement"],                                                  False, True,  True,  True,  8),
    ("balance_amount",    "Balance",           "الرصيد",            "decimal", "financial",      ["bank_statement","fixed_asset"],                                    False, True,  True,  True,  9),
    ("payment_amount",    "Payment Amount",    "مبلغ الدفع",        "decimal", "financial",      ["invoice","tax_declaration","vat_return"],                          False, True,  True,  True,  10),
    ("budget_limit",      "Budget Limit",      "سقف الميزانية",     "decimal", "financial",      ["purchase_order"],                                                  False, True,  True,  True,  11),
    # ── Compliance ──
    ("zatca_invoice_number","ZATCA Invoice #", "رقم فاتورة زاتكا",  "string",  "compliance",     ["invoice","sales_receipt"],                                         False, True,  True,  True,  1),
    ("qr_code_valid",     "QR Code Valid",     "صحة رمز QR",        "boolean", "compliance",     ["invoice","sales_receipt"],                                         False, True,  True,  True,  2),
    ("vat_registration_number","VAT Reg #",    "رقم تسجيل ضريبة القيمة المضافة","string","compliance",["invoice","tax_declaration","vat_return","sales_receipt"],  False, True,  True,  True,  3),
    ("zatca_reference",   "ZATCA Reference",   "مرجع زاتكا",        "string",  "compliance",     ["tax_declaration","vat_return"],                                    False, True,  True,  True,  4),
    ("filing_status",     "Filing Status",     "حالة التقديم",      "string",  "compliance",     ["tax_declaration","vat_return"],                                    False, True,  True,  True,  5),
    ("approval_status",   "Approval Status",   "حالة الاعتماد",     "string",  "compliance",     ["purchase_order","expense_report"],                                 False, True,  True,  True,  6),
    ("bank_account_number","Bank Account #",   "رقم الحساب البنكي", "string",  "compliance",     ["bank_statement","payroll"],                                        False, False, True,  True,  7),
    ("iban",              "IBAN",              "رقم الآيبان",        "string",  "compliance",     ["bank_statement","payroll"],                                        False, True,  True,  True,  8),
    # ── Timeline ──
    ("issue_date",        "Issue Date",        "تاريخ الإصدار",     "date",    "timeline",       ["*"],    False, True,  True,  True,  1),
    ("due_date",          "Due Date",          "تاريخ الاستحقاق",   "date",    "timeline",       ["invoice","tax_declaration","vat_return"],                          False, True,  True,  True,  2),
    ("delivery_date",     "Delivery Date",     "تاريخ التسليم",     "date",    "timeline",       ["purchase_order"],                                                  False, False, True,  True,  3),
    ("submission_date",   "Submission Date",   "تاريخ التقديم",     "date",    "timeline",       ["expense_report","tax_declaration","vat_return"],                   False, True,  True,  True,  4),
    ("approval_date",     "Approval Date",     "تاريخ الاعتماد",    "date",    "timeline",       ["purchase_order","expense_report"],                                 False, False, True,  True,  5),
    ("payment_date",      "Payment Date",      "تاريخ الدفع",       "date",    "timeline",       ["payroll","tax_declaration","vat_return"],                          False, False, True,  True,  6),
    ("period_from",       "Period From",       "بداية الفترة",      "date",    "timeline",       ["bank_statement","payroll","tax_declaration","vat_return","expense_report"], False, True, True, True, 7),
    ("period_to",         "Period To",         "نهاية الفترة",      "date",    "timeline",       ["bank_statement","payroll","tax_declaration","vat_return","expense_report"], False, True, True, True, 8),
    ("tax_period",        "Tax Period",        "الفترة الضريبية",   "string",  "timeline",       ["tax_declaration","vat_return","fixed_asset"],                      False, True,  True,  True,  9),
    # ── Classification ──
    ("expense_type",      "Expense Type",      "نوع المصروف",       "string",  "classification", ["expense_report"],                                                  False, True,  True,  True,  1),
    ("asset_category",    "Asset Category",    "فئة الأصل",         "string",  "classification", ["fixed_asset"],                                                     False, True,  True,  True,  2),
    ("asset_id",          "Asset ID",          "معرف الأصل",        "string",  "classification", ["fixed_asset"],                                                     False, True,  True,  True,  3),
    ("payroll_month",     "Payroll Month",     "شهر الرواتب",       "string",  "classification", ["payroll"],                                                         False, False, True,  True,  4),
    ("payment_method",    "Payment Method",    "طريقة الدفع",       "string",  "classification", ["expense_report","invoice"],                                        False, False, True,  True,  5),
    ("depreciation_method","Depreciation Method","طريقة الإهلاك",   "string",  "classification", ["fixed_asset"],                                                     False, True,  True,  True,  6),
    ("useful_life_years", "Useful Life (Yrs)", "العمر الإنتاجي",    "integer", "classification", ["fixed_asset"],                                                     False, True,  True,  True,  7),
    # ── HR / Payroll ──
    ("gross_salary",      "Gross Salary",      "الراتب الإجمالي",   "decimal", "hr_payroll",     ["payroll"],                                                         False, True,  True,  True,  1),
    ("net_salary",        "Net Salary",        "صافي الراتب",       "decimal", "hr_payroll",     ["payroll"],                                                         False, True,  True,  True,  2),
    ("total_allowances",  "Total Allowances",  "إجمالي البدلات",    "decimal", "hr_payroll",     ["payroll"],                                                         False, True,  True,  True,  3),
    ("total_deductions",  "Total Deductions",  "إجمالي الاستقطاعات","decimal", "hr_payroll",     ["payroll"],                                                         False, True,  True,  True,  4),
    ("gosi_amount",       "GOSI Amount",       "مبلغ التأمينات",    "decimal", "hr_payroll",     ["payroll"],                                                         False, True,  True,  True,  5),
    ("employee_count",    "Employee Count",    "عدد الموظفين",      "integer", "hr_payroll",     ["payroll"],                                                         False, True,  True,  True,  6),
]


class Command(BaseCommand):
    help = "Seed CanonicalFieldDefinition and DocumentTypeFieldMapping. Idempotent."

    def handle(self, *args, **options):
        from apps.documents.canonical_models import CanonicalFieldDefinition, DocumentTypeFieldMapping

        self.stdout.write("Seeding canonical field definitions...")
        created_fields = 0
        updated_fields = 0

        for row in FIELD_DEFINITIONS:
            (field_code, label_en, label_ar, data_type, group,
             applicable_types, storage, rules, reporting, nullable, sort) = row

            obj, created = CanonicalFieldDefinition.objects.update_or_create(
                field_code=field_code,
                defaults=dict(
                    label_en=label_en,
                    label_ar=label_ar,
                    data_type=data_type,
                    field_group=group,
                    applicable_document_types=applicable_types,
                    required_for_storage=storage,
                    required_for_rule_execution=rules,
                    required_for_reporting=reporting,
                    is_nullable=nullable,
                    sort_order=sort,
                    is_active=True,
                ),
            )
            if created:
                created_fields += 1
            else:
                updated_fields += 1

        self.stdout.write(f"  Fields: {created_fields} created, {updated_fields} updated")

        self.stdout.write("Seeding document type field mappings...")
        mapper = CanonicalMapper()
        created_maps = 0

        for doc_type, field_map in mapper.FALLBACK_MAPPING.items():
            for field_code, sources in field_map.items():
                try:
                    canonical_field = CanonicalFieldDefinition.objects.get(field_code=field_code)
                except CanonicalFieldDefinition.DoesNotExist:
                    self.stdout.write(f"  WARNING: field_code '{field_code}' not in definitions, skipping")
                    continue

                for priority, source_def in enumerate(reversed(sources)):
                    _, created = DocumentTypeFieldMapping.objects.get_or_create(
                        canonical_field=canonical_field,
                        document_type=doc_type,
                        source_column=source_def["source"],
                        defaults=dict(
                            transform=source_def.get("transform", "direct"),
                            transform_args=source_def.get("args", {}),
                            priority=priority,
                            is_active=True,
                        ),
                    )
                    if created:
                        created_maps += 1

        self.stdout.write(f"  Mappings: {created_maps} created")
        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(FIELD_DEFINITIONS)} canonical fields, {created_maps} mappings seeded."
        ))
