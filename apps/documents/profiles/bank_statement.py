from decimal import Decimal

from apps.documents.profiles.base import DocumentTypeProfile, build_field


class BankStatementProfile(DocumentTypeProfile):
    code = "bank_statement"
    name_ar = "كشف حساب بنكي"
    name_en = "Bank Statement"
    category = "financial"
    approval_levels = 1
    high_value_threshold = Decimal("0")
    fields = [
        build_field("account_number", "رقم الحساب", "Account Number", "str", True, ui_order=10),
        build_field("period_from", "الفترة من", "Period From", "date", True, ui_order=20),
        build_field("period_to", "الفترة إلى", "Period To", "date", True, ui_order=30),
        build_field("opening_balance", "الرصيد الافتتاحي", "Opening Balance", "decimal", True, ui_section="balances", ui_order=40),
        build_field("closing_balance", "الرصيد الختامي", "Closing Balance", "decimal", True, ui_section="balances", ui_order=50),
        build_field("transactions", "المعاملات", "Transactions", "list", True, ui_section="balances", ui_order=60),
    ]
    blocking_rule_codes = ["FIN-003"]
    workflow_states = [
        "uploaded",
        "extracted",
        "needs_review",
        "validated",
        "audit_passed",
        "archived",
    ]