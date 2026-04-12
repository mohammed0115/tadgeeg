from decimal import Decimal

from apps.documents.profiles.base import DocumentTypeProfile, build_field


class JournalEntryProfile(DocumentTypeProfile):
    code = "journal_entry"
    name_ar = "قيد يومية"
    name_en = "Journal Entry"
    category = "financial"
    approval_levels = 2
    high_value_threshold = Decimal("250000")
    fields = [
        build_field("entry_number", "رقم القيد", "Entry Number", "str", True, ui_order=10),
        build_field("posting_date", "تاريخ الترحيل", "Posting Date", "date", True, ui_order=20),
        build_field("debit_total", "إجمالي المدين", "Debit Total", "decimal", True, ui_section="amounts", ui_order=30),
        build_field("credit_total", "إجمالي الدائن", "Credit Total", "decimal", True, ui_section="amounts", ui_order=40),
        build_field("prepared_by", "أُعد بواسطة", "Prepared By", "str", True, ui_section="workflow", ui_order=50),
        build_field("approved_by", "اعتمد بواسطة", "Approved By", "str", True, ui_section="workflow", ui_order=60),
    ]
    blocking_rule_codes = ["FIN-002"]
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