from decimal import Decimal

from apps.documents.profiles.base import DocumentTypeProfile, build_field


class PurchaseOrderProfile(DocumentTypeProfile):
    code = "purchase_order"
    name_ar = "أمر شراء"
    name_en = "Purchase Order"
    category = "financial"
    approval_levels = 2
    high_value_threshold = Decimal("100000")
    fields = [
        build_field("po_number", "رقم أمر الشراء", "PO Number", "str", True, ui_order=10),
        build_field("vendor_name", "اسم المورد", "Vendor Name", "str", True, ui_order=20),
        build_field("currency", "العملة", "Currency", "str", True, ui_order=30),
        build_field("tax_type", "نوع الضريبة", "Tax Type", "str", True, ui_order=40),
        build_field("subtotal", "الإجمالي قبل الضريبة", "Subtotal", "decimal", True, ui_order=50),
        build_field("total_amount", "الإجمالي", "Total Amount", "decimal", True, ui_order=60),
        build_field("cost_center", "مركز التكلفة", "Cost Center", "str", True, ui_section="controls", ui_order=70),
        build_field("approver", "الموافق", "Approver", "str", True, ui_section="workflow", ui_order=80),
        build_field("justification", "المبرر", "Justification", "str", True, ui_section="workflow", ui_order=90),
        build_field("approval_date", "تاريخ الاعتماد", "Approval Date", "date", True, ui_section="workflow", ui_order=100),
        build_field("entity", "الجهة", "Entity", "str", True, ui_section="organization", ui_order=110),
    ]
    blocking_rule_codes = ["CMT-001", "CMT-002", "FIN-001", "WFL-001"]
    workflow_states = [
        "uploaded",
        "extracted",
        "needs_review",
        "validated",
        "audit_passed",
        "pending_approval",
        "approved",
        "posted",
        "archived",
    ]