from decimal import Decimal

from apps.documents.profiles.base import DocumentTypeProfile, build_field


class SalesInvoiceProfile(DocumentTypeProfile):
    code = "sales_invoice"
    name_ar = "فاتورة مبيعات"
    name_en = "Sales Invoice"
    category = "financial"
    approval_levels = 1
    high_value_threshold = Decimal("50000")
    fields = [
        build_field("invoice_number", "رقم الفاتورة", "Invoice Number", "str", True, ui_order=10),
        build_field("customer_name", "اسم العميل", "Customer Name", "str", True, ui_order=20),
        build_field("issue_date", "تاريخ الإصدار", "Issue Date", "date", True, ui_order=30),
        build_field("subtotal", "الإجمالي قبل الضريبة", "Subtotal", "decimal", True, ui_section="amounts", ui_order=40),
        build_field("vat_amount", "الضريبة", "VAT Amount", "decimal", True, ui_section="amounts", ui_order=50),
        build_field("total_amount", "الإجمالي", "Total Amount", "decimal", True, ui_section="amounts", ui_order=60),
        build_field("currency", "العملة", "Currency", "str", True, ui_order=70),
    ]
    blocking_rule_codes = ["CMT-001", "FIN-001", "CMP-001"]
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