from decimal import Decimal

from apps.documents.profiles.base import DocumentTypeProfile, build_field


class ContractProfile(DocumentTypeProfile):
    code = "contract"
    name_ar = "عقد"
    name_en = "Contract"
    category = "compliance"
    approval_levels = 2
    high_value_threshold = Decimal("100000")
    fields = [
        build_field("parties", "الأطراف", "Parties", "list", True, ui_order=10),
        build_field("effective_date", "تاريخ السريان", "Effective Date", "date", True, ui_order=20),
        build_field("expiry_date", "تاريخ الانتهاء", "Expiry Date", "date", True, ui_order=30),
        build_field("contract_value", "قيمة العقد", "Contract Value", "decimal", True, ui_section="amounts", ui_order=40),
        build_field("obligations", "الالتزامات", "Obligations", "list", True, ui_section="terms", ui_order=50),
    ]
    blocking_rule_codes = ["CMT-001", "WFL-001"]
    workflow_states = [
        "uploaded",
        "extracted",
        "needs_review",
        "validated",
        "audit_passed",
        "pending_approval",
        "approved",
        "archived",
    ]