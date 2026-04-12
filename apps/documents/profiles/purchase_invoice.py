from decimal import Decimal

from apps.documents.profiles.base import DocumentTypeProfile, build_field


class PurchaseInvoiceProfile(DocumentTypeProfile):
    code = "purchase_invoice"
    name_ar = "فاتورة مشتريات"
    name_en = "Purchase Invoice"
    category = "financial"
    approval_levels = 2
    high_value_threshold = Decimal("75000")
    fields = [
        build_field("invoice_number", "رقم الفاتورة", "Invoice Number", "str", True, ui_order=10),
        build_field("vendor_name", "اسم المورد", "Vendor Name", "str", True, ui_order=20),
        build_field("vendor_vat_number", "الرقم الضريبي للمورد", "Vendor VAT Number", "str", True, ui_order=30),
        build_field("line_items", "البنود", "Line Items", "list", True, ui_section="amounts", ui_order=40),
        build_field("subtotal", "الإجمالي قبل الضريبة", "Subtotal", "decimal", True, ui_section="amounts", ui_order=50),
        build_field("vat_amount", "الضريبة", "VAT Amount", "decimal", True, ui_section="amounts", ui_order=60),
        build_field("total_amount", "الإجمالي", "Total Amount", "decimal", True, ui_section="amounts", ui_order=70),
        build_field("invoice_date", "تاريخ الفاتورة", "Invoice Date", "date", True, ui_order=80),
        build_field("currency", "العملة", "Currency", "str", True, ui_order=90),
    ]
    blocking_rule_codes = ["CMT-001", "FIN-001", "CMP-001", "DUP-001"]
    workflow_states = [
        "uploaded",
        "extracted",
        "needs_review",
        "validated",
        "audit_failed",
        "audit_passed",
        "pending_approval",
        "approved",
        "posted",
        "archived",
    ]