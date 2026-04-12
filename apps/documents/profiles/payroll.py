from decimal import Decimal

from apps.documents.profiles.base import DocumentTypeProfile, build_field


class PayrollProfile(DocumentTypeProfile):
    code = "payroll"
    name_ar = "مسير رواتب"
    name_en = "Payroll"
    category = "financial"
    approval_levels = 2
    high_value_threshold = Decimal("150000")
    fields = [
        build_field("period", "الفترة", "Period", "str", True, ui_order=10),
        build_field("employee_count", "عدد الموظفين", "Employee Count", "decimal", True, ui_order=20),
        build_field("gross_total", "الإجمالي الإجمالي", "Gross Total", "decimal", True, ui_section="amounts", ui_order=30),
        build_field("net_total", "الإجمالي الصافي", "Net Total", "decimal", True, ui_section="amounts", ui_order=40),
        build_field("prepared_by", "أُعد بواسطة", "Prepared By", "str", True, ui_section="workflow", ui_order=50),
        build_field("approved_by", "اعتمد بواسطة", "Approved By", "str", True, ui_section="workflow", ui_order=60),
    ]
    blocking_rule_codes = ["CMT-001", "FIN-001", "CMP-002"]
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