"""
Dashboard Widget Configuration — Tadgeeg Audit Platform.

Defines the widget layout, data sources, and rendering config for every
section of the report dashboard.  The frontend (React/Next.js) reads this
config to render the correct widget types without hard-coding logic.

Usage:
    from apps.reports.dashboard_widgets import DOCUMENT_WIDGETS, EXECUTIVE_WIDGETS
    widgets = DOCUMENT_WIDGETS.get("sales_invoice")

Widget fields:
    id          — unique widget identifier
    type        — widget rendering type (see WIDGET_TYPES)
    title_ar/en — bilingual label
    data_path   — dot-notation path into the report JSON
    size        — grid column span: 1 | 2 | 3 | 4 (out of 12-col grid)
    priority    — display order (lower = higher in page)
    icon        — emoji or icon class
    color       — Tailwind color key: blue | green | red | yellow | purple | slate
    condition   — optional data_path that must be truthy to show widget
    chart_type  — for chart widgets: bar | pie | donut | line | gauge | waterfall
    thresholds  — for gauge/score widgets: {green, yellow, red} as percentages
    doc_types   — list of doc_types this widget applies to (empty = all)
"""

from __future__ import annotations
from typing import Any

# ─── Widget type catalogue ────────────────────────────────────────────────────

WIDGET_TYPES = {
    "kpi_card":        "Single metric display with icon and trend indicator",
    "kpi_row":         "Horizontal row of 3-6 KPI cards",
    "score_ring":      "Circular gauge (SVG) 0-100",
    "status_badge":    "Pass/Fail/Warning/Critical pill",
    "rule_table":      "Full rule evaluation table with sortable columns",
    "violations_list": "Severity-sorted violation cards with recommendations",
    "bar_chart":       "Horizontal or vertical bar chart",
    "donut_chart":     "Donut / pie breakdown chart",
    "waterfall_chart": "Running balance (bank reconciliation)",
    "field_grid":      "Key-value pairs in a responsive 2-column grid",
    "line_items_table":"Itemised line-items table",
    "alert_banner":    "Coloured alert/warning message box",
    "text_narrative":  "Free-text section (AI summary / recommendation body)",
    "compliance_bar":  "Single-row progress bar with % label",
    "timeline":        "Ordered list of events / audit trail",
    "vendor_card":     "Mini-card showing vendor name + VAT + CR",
    "heatmap_row":     "Row of coloured cells (risk distribution across doc types)",
}


# ─── Shared / generic widgets (appear in every document type) ─────────────────

_GENERIC_WIDGETS: list[dict] = [
    {
        "id":       "w-meta-status",
        "type":     "status_badge",
        "title_ar": "حالة المستند",
        "title_en": "Document Status",
        "data_path": "report_meta.status",
        "size":     1,
        "priority": 1,
        "icon":     "🔖",
        "color":    "slate",
    },
    {
        "id":       "w-summary-kpis",
        "type":     "kpi_row",
        "title_ar": "مؤشرات الأداء الرئيسية",
        "title_en": "Key Performance Indicators",
        "data_path": "summary",
        "fields": [
            {"key": "total_amount",      "label_ar": "الإجمالي",         "label_en": "Total",         "color": "blue",   "format": "currency"},
            {"key": "rules_passed",      "label_ar": "قواعد ناجحة",      "label_en": "Rules Passed",  "color": "green"},
            {"key": "rules_failed",      "label_ar": "قواعد فاشلة",      "label_en": "Rules Failed",  "color": "red"},
            {"key": "rules_warning",     "label_ar": "تحذيرات",          "label_en": "Warnings",      "color": "yellow"},
            {"key": "blocking_failures", "label_ar": "تمنع الاعتماد",    "label_en": "Blocks Approv.", "color": "purple"},
            {"key": "error_rate",        "label_ar": "نسبة الأخطاء",     "label_en": "Error Rate",    "color": "red",    "format": "percent"},
        ],
        "size":     4,
        "priority": 2,
        "icon":     "📊",
        "color":    "blue",
    },
    {
        "id":       "w-risk-score",
        "type":     "score_ring",
        "title_ar": "درجة المخاطر",
        "title_en": "Risk Score",
        "data_path": "summary.risk_score",
        "label_path": "summary.risk_level",
        "size":     1,
        "priority": 3,
        "icon":     "🎯",
        "color":    "blue",
        "thresholds": {"green": 85, "yellow": 60, "red": 0},
        "invert":   True,  # lower score = higher risk
    },
    {
        "id":       "w-compliance-bar",
        "type":     "compliance_bar",
        "title_ar": "نسبة الامتثال",
        "title_en": "Compliance Rate",
        "data_path": "summary.pass_rate",
        "size":     2,
        "priority": 4,
        "icon":     "✅",
        "color":    "green",
        "thresholds": {"green": 85, "yellow": 60, "red": 0},
    },
    {
        "id":       "w-key-fields",
        "type":     "field_grid",
        "title_ar": "الحقول الأساسية",
        "title_en": "Key Fields",
        "data_path": "key_fields",
        "size":     2,
        "priority": 5,
        "icon":     "📋",
        "color":    "slate",
    },
    {
        "id":       "w-rule-evaluation",
        "type":     "rule_table",
        "title_ar": "نتائج تقييم القواعد",
        "title_en": "Rule Evaluation",
        "data_path": "rule_evaluation",
        "size":     4,
        "priority": 6,
        "icon":     "⚖️",
        "color":    "indigo",
        "columns": ["rule_code", "rule_name", "status", "severity", "explanation", "blocks_approval"],
        "sortable": True,
        "filterable": True,
    },
    {
        "id":       "w-violations",
        "type":     "violations_list",
        "title_ar": "المخالفات",
        "title_en": "Violations",
        "data_path": "violations",
        "size":     4,
        "priority": 7,
        "icon":     "🚨",
        "color":    "red",
        "condition": "violations",
        "group_by":  "severity",
    },
    {
        "id":       "w-ai-insights",
        "type":     "text_narrative",
        "title_ar": "رؤى الذكاء الاصطناعي",
        "title_en": "AI Insights",
        "data_path": "ai_insights",
        "size":     2,
        "priority": 8,
        "icon":     "🤖",
        "color":    "violet",
        "condition": "ai_insights.has_insights",
        "sub_fields": [
            {"key": "anomalies",      "label_ar": "شذوذات",          "label_en": "Anomalies"},
            {"key": "patterns",       "label_ar": "أنماط مشبوهة",    "label_en": "Suspicious Patterns"},
            {"key": "vendor_behavior","label_ar": "سلوك المورد",     "label_en": "Vendor Behavior"},
            {"key": "ai_summary_ar",  "label_ar": "ملخص",            "label_en": "Summary (AR)"},
            {"key": "ai_summary_en",  "label_ar": "ملخص",            "label_en": "Summary (EN)"},
        ],
    },
    {
        "id":       "w-compliance-zatca",
        "type":     "field_grid",
        "title_ar": "الامتثال لـ ZATCA",
        "title_en": "ZATCA Compliance",
        "data_path": "compliance",
        "size":     2,
        "priority": 9,
        "icon":     "🏛️",
        "color":    "blue",
        "fields": [
            {"key": "zatca_compliant",  "label_ar": "متوافق مع ZATCA", "label_en": "ZATCA Compliant", "type": "bool"},
            {"key": "compliance_score", "label_ar": "نسبة الامتثال",   "label_en": "Score",           "format": "percent"},
            {"key": "missing_fields",   "label_ar": "حقول مفقودة",     "label_en": "Missing Fields",  "type": "list"},
        ],
    },
    {
        "id":       "w-recommendations",
        "type":     "violations_list",
        "title_ar": "التوصيات",
        "title_en": "Recommendations",
        "data_path": "recommendations",
        "size":     4,
        "priority": 10,
        "icon":     "💡",
        "color":    "yellow",
        "group_by":  "priority",
    },
    {
        "id":       "w-audit-trail",
        "type":     "timeline",
        "title_ar": "مسار التدقيق",
        "title_en": "Audit Trail",
        "data_path": "audit_trail",
        "size":     2,
        "priority": 11,
        "icon":     "🕐",
        "color":    "slate",
    },
]


# ─── Document-type-specific widgets ──────────────────────────────────────────

_INVOICE_SPECIFIC: list[dict] = [
    {
        "id":       "w-inv-vat-breakdown",
        "type":     "kpi_row",
        "title_ar": "تفصيل الضريبة المضافة",
        "title_en": "VAT Breakdown",
        "data_path": "document_specific.vat_breakdown",
        "fields": [
            {"key": "subtotal",      "label_ar": "الأساس الخاضع",   "label_en": "Subtotal",     "color": "slate", "format": "currency"},
            {"key": "vat_rate",      "label_ar": "نسبة الضريبة",    "label_en": "VAT Rate",     "color": "blue",  "format": "percent"},
            {"key": "vat_amount",    "label_ar": "مبلغ الضريبة",    "label_en": "VAT Amount",   "color": "slate", "format": "currency"},
            {"key": "total",         "label_ar": "الإجمالي",        "label_en": "Total",        "color": "blue",  "format": "currency"},
            {"key": "expected_vat",  "label_ar": "الضريبة المتوقعة","label_en": "Expected VAT", "color": "green", "format": "currency"},
        ],
        "size":     4,
        "priority": 12,
        "icon":     "🧾",
        "color":    "blue",
        "condition": "document_specific.vat_breakdown",
    },
    {
        "id":       "w-inv-qr",
        "type":     "status_badge",
        "title_ar": "رمز QR (ZATCA)",
        "title_en": "QR Code (ZATCA)",
        "data_path": "document_specific.qr_validation",
        "size":     1,
        "priority": 13,
        "icon":     "📱",
        "color":    "green",
        "condition": "document_specific.qr_validation",
    },
    {
        "id":       "w-inv-line-items",
        "type":     "line_items_table",
        "title_ar": "بنود الفاتورة",
        "title_en": "Invoice Line Items",
        "data_path": "document_specific.line_items",
        "size":     4,
        "priority": 14,
        "icon":     "📑",
        "color":    "slate",
        "condition": "document_specific.line_items",
    },
    {
        "id":       "w-inv-duplicate",
        "type":     "alert_banner",
        "title_ar": "تحذير: فاتورة مكررة",
        "title_en": "Warning: Duplicate Invoice",
        "data_path": "document_specific.is_duplicate",
        "size":     4,
        "priority": 15,
        "icon":     "🔁",
        "color":    "red",
        "condition": "document_specific.is_duplicate",
    },
]

_PO_SPECIFIC: list[dict] = [
    {
        "id":       "w-po-vendor",
        "type":     "vendor_card",
        "title_ar": "بيانات المورد",
        "title_en": "Vendor Details",
        "data_path": "document_specific.vendor_validation",
        "size":     2,
        "priority": 12,
        "icon":     "🏢",
        "color":    "violet",
        "condition": "document_specific.vendor_validation",
    },
    {
        "id":       "w-po-budget",
        "type":     "kpi_row",
        "title_ar": "التحقق من الميزانية",
        "title_en": "Budget Check",
        "data_path": "document_specific.budget_check",
        "fields": [
            {"key": "budget_limit",  "label_ar": "حد الميزانية",    "label_en": "Budget Limit", "color": "slate",  "format": "currency"},
            {"key": "total_amount",  "label_ar": "قيمة أمر الشراء", "label_en": "PO Amount",    "color": "blue",   "format": "currency"},
            {"key": "within_budget", "label_ar": "ضمن الميزانية",   "label_en": "Within Budget","color": "green",  "format": "bool"},
        ],
        "size":     3,
        "priority": 13,
        "icon":     "💰",
        "color":    "orange",
        "condition": "document_specific.budget_check",
    },
    {
        "id":       "w-po-line-items",
        "type":     "line_items_table",
        "title_ar": "بنود أمر الشراء",
        "title_en": "PO Line Items",
        "data_path": "document_specific.line_items",
        "size":     4,
        "priority": 14,
        "icon":     "📑",
        "color":    "slate",
        "condition": "document_specific.line_items",
    },
]

_BANK_SPECIFIC: list[dict] = [
    {
        "id":       "w-bank-reconciliation",
        "type":     "waterfall_chart",
        "title_ar": "مطابقة الرصيد",
        "title_en": "Balance Reconciliation",
        "data_path": "document_specific.reconciliation",
        "fields": [
            {"key": "opening_balance",    "label_ar": "رصيد الافتتاح", "label_en": "Opening",  "color": "slate"},
            {"key": "total_credits",      "label_ar": "الإيداعات",     "label_en": "+Credits", "color": "green"},
            {"key": "total_debits",       "label_ar": "السحوبات",      "label_en": "−Debits",  "color": "red"},
            {"key": "closing_balance",    "label_ar": "رصيد الإغلاق",  "label_en": "Closing",  "color": "blue"},
            {"key": "calculated_closing", "label_ar": "رصيد محسوب",    "label_en": "Calc.",    "color": "violet"},
        ],
        "size":     4,
        "priority": 12,
        "icon":     "🏦",
        "color":    "teal",
        "condition": "document_specific.reconciliation",
    },
    {
        "id":       "w-bank-suspicious",
        "type":     "alert_banner",
        "title_ar": "معاملات مشبوهة",
        "title_en": "Suspicious Transactions",
        "data_path": "document_specific.suspicious_transactions",
        "size":     4,
        "priority": 13,
        "icon":     "🔍",
        "color":    "orange",
        "condition": "document_specific.suspicious_transactions",
    },
]

_PAYROLL_SPECIFIC: list[dict] = [
    {
        "id":       "w-payroll-breakdown",
        "type":     "kpi_row",
        "title_ar": "تفصيل الرواتب",
        "title_en": "Payroll Breakdown",
        "data_path": "document_specific.salary_breakdown",
        "fields": [
            {"key": "total_gross",      "label_ar": "إجمالي الأساسي",    "label_en": "Total Gross",      "color": "slate",  "format": "currency"},
            {"key": "total_allowances", "label_ar": "إجمالي البدلات",    "label_en": "Total Allowances", "color": "green",  "format": "currency"},
            {"key": "total_deductions", "label_ar": "إجمالي الاستقطاعات","label_en": "Total Deductions", "color": "red",    "format": "currency"},
            {"key": "total_net",        "label_ar": "إجمالي الصافي",     "label_en": "Total Net",        "color": "blue",   "format": "currency"},
            {"key": "employee_count",   "label_ar": "عدد الموظفين",       "label_en": "Employees",        "color": "slate"},
        ],
        "size":     4,
        "priority": 12,
        "icon":     "👥",
        "color":    "emerald",
        "condition": "document_specific.salary_breakdown",
    },
    {
        "id":       "w-payroll-ghost",
        "type":     "alert_banner",
        "title_ar": "موظفون وهميون / تكرار",
        "title_en": "Ghost Employees / Duplicates",
        "data_path": "document_specific.employee_validation",
        "size":     4,
        "priority": 13,
        "icon":     "👻",
        "color":    "red",
        "condition": "document_specific.employee_validation.ghost_flags",
    },
    {
        "id":       "w-payroll-gosi",
        "type":     "kpi_card",
        "title_ar": "اشتراكات التأمينات الاجتماعية",
        "title_en": "GOSI Contributions",
        "data_path": "document_specific.gosi_summary.total_gosi",
        "size":     1,
        "priority": 14,
        "icon":     "🏥",
        "color":    "blue",
        "format":   "currency",
        "condition": "document_specific.gosi_summary",
    },
]

_EXPENSE_SPECIFIC: list[dict] = [
    {
        "id":       "w-expense-receipts",
        "type":     "kpi_row",
        "title_ar": "التحقق من الإيصالات",
        "title_en": "Receipt Validation",
        "data_path": "document_specific.receipt_validation",
        "fields": [
            {"key": "total_lines",     "label_ar": "إجمالي البنود",   "label_en": "Total Lines",      "color": "slate"},
            {"key": "with_receipt",    "label_ar": "بإيصال",          "label_en": "With Receipt",     "color": "green"},
            {"key": "without_receipt", "label_ar": "بدون إيصال",      "label_en": "Missing Receipt",  "color": "red"},
        ],
        "size":     3,
        "priority": 12,
        "icon":     "🧾",
        "color":    "pink",
        "condition": "document_specific.receipt_validation",
    },
    {
        "id":       "w-expense-categories",
        "type":     "donut_chart",
        "title_ar": "توزيع المصروفات حسب الفئة",
        "title_en": "Expense Category Breakdown",
        "data_path": "document_specific.category_breakdown",
        "label_key": "category",
        "value_key": "total",
        "size":     2,
        "priority": 13,
        "icon":     "🍩",
        "color":    "violet",
        "condition": "document_specific.category_breakdown",
    },
    {
        "id":       "w-expense-policy",
        "type":     "alert_banner",
        "title_ar": "مخالفات السياسة",
        "title_en": "Policy Violations",
        "data_path": "document_specific.policy_violations",
        "size":     4,
        "priority": 14,
        "icon":     "⚠️",
        "color":    "red",
        "condition": "document_specific.policy_violations.over_limit_count",
    },
]

_VAT_SPECIFIC: list[dict] = [
    {
        "id":       "w-vat-calculation",
        "type":     "kpi_row",
        "title_ar": "حساب صافي الضريبة",
        "title_en": "VAT Net Calculation",
        "data_path": "document_specific.vat_calculation",
        "fields": [
            {"key": "output_vat",     "label_ar": "ضريبة المخرجات",   "label_en": "Output VAT",    "color": "red",   "format": "currency"},
            {"key": "input_vat",      "label_ar": "ضريبة المدخلات",   "label_en": "Input VAT",     "color": "green", "format": "currency"},
            {"key": "calculated_net", "label_ar": "صافي محسوب",       "label_en": "Calculated Net","color": "blue",  "format": "currency"},
            {"key": "declared_net",   "label_ar": "صافي معلن",        "label_en": "Declared Net",  "color": "slate", "format": "currency"},
            {"key": "discrepancy",    "label_ar": "الفارق",           "label_en": "Discrepancy",   "color": "red",   "format": "currency"},
        ],
        "size":     4,
        "priority": 12,
        "icon":     "📊",
        "color":    "blue",
        "condition": "document_specific.vat_calculation",
    },
    {
        "id":       "w-vat-taxable",
        "type":     "bar_chart",
        "title_ar": "المبالغ الخاضعة للضريبة",
        "title_en": "Taxable Amounts",
        "data_path": "document_specific.taxable_amounts",
        "chart_type": "bar",
        "keys": [
            {"key": "standard_rated_sales",     "label_ar": "المبيعات الخاضعة",   "label_en": "Standard Sales"},
            {"key": "standard_rated_purchases", "label_ar": "المشتريات الخاضعة",  "label_en": "Standard Purchases"},
            {"key": "zero_rated_sales",         "label_ar": "المبيعات صفرية",     "label_en": "Zero-Rated Sales"},
            {"key": "exempt_sales",             "label_ar": "المبيعات المعفاة",   "label_en": "Exempt Sales"},
        ],
        "size":     4,
        "priority": 13,
        "icon":     "📈",
        "color":    "blue",
        "condition": "document_specific.taxable_amounts",
    },
]

_ASSET_SPECIFIC: list[dict] = [
    {
        "id":       "w-asset-depreciation",
        "type":     "kpi_row",
        "title_ar": "ملخص الإهلاك",
        "title_en": "Depreciation Summary",
        "data_path": "document_specific.depreciation_summary",
        "fields": [
            {"key": "total_cost",         "label_ar": "إجمالي التكلفة",       "label_en": "Total Cost",         "color": "slate",  "format": "currency"},
            {"key": "total_accumulated",  "label_ar": "الإهلاك المتراكم",     "label_en": "Accumulated Dep.",   "color": "orange", "format": "currency"},
            {"key": "total_book_value",   "label_ar": "القيمة الدفترية",      "label_en": "Book Value",         "color": "blue",   "format": "currency"},
            {"key": "fully_depreciated",  "label_ar": "مستهلك بالكامل",       "label_en": "Fully Depreciated",  "color": "slate"},
            {"key": "negative_book_value_count", "label_ar": "قيم دفترية سالبة", "label_en": "Negative BV",    "color": "red"},
        ],
        "size":     4,
        "priority": 12,
        "icon":     "🏗️",
        "color":    "amber",
        "condition": "document_specific.depreciation_summary",
    },
    {
        "id":       "w-asset-by-category",
        "type":     "donut_chart",
        "title_ar": "توزيع الأصول حسب الفئة",
        "title_en": "Assets by Category",
        "data_path": "document_specific.asset_lifecycle.by_category",
        "label_key": "category",
        "value_key": "count",
        "size":     2,
        "priority": 13,
        "icon":     "🍩",
        "color":    "amber",
        "condition": "document_specific.asset_lifecycle",
    },
]

_RECEIPT_SPECIFIC: list[dict] = [
    {
        "id":       "w-receipt-payment",
        "type":     "field_grid",
        "title_ar": "طريقة الدفع",
        "title_en": "Payment Method",
        "data_path": "document_specific.payment_validation",
        "size":     2,
        "priority": 12,
        "icon":     "💳",
        "color":    "cyan",
        "condition": "document_specific.payment_validation",
    },
    {
        "id":       "w-receipt-zatca",
        "type":     "field_grid",
        "title_ar": "مرجع ZATCA",
        "title_en": "ZATCA Reference",
        "data_path": "document_specific.zatca_reference",
        "size":     2,
        "priority": 13,
        "icon":     "🔗",
        "color":    "blue",
        "condition": "document_specific.zatca_reference",
    },
    {
        "id":       "w-receipt-line-items",
        "type":     "line_items_table",
        "title_ar": "بنود الإيصال",
        "title_en": "Receipt Line Items",
        "data_path": "document_specific.line_items",
        "size":     4,
        "priority": 14,
        "icon":     "📑",
        "color":    "slate",
        "condition": "document_specific.line_items",
    },
]


# ─── Per-document-type widget registry ───────────────────────────────────────

DOCUMENT_WIDGETS: dict[str, list[dict]] = {
    "sales_invoice":  _GENERIC_WIDGETS + _INVOICE_SPECIFIC,
    "purchase_order": _GENERIC_WIDGETS + _PO_SPECIFIC,
    "bank_statement": _GENERIC_WIDGETS + _BANK_SPECIFIC,
    "payroll":        _GENERIC_WIDGETS + _PAYROLL_SPECIFIC,
    "expense_report": _GENERIC_WIDGETS + _EXPENSE_SPECIFIC,
    "vat_return":     _GENERIC_WIDGETS + _VAT_SPECIFIC,
    "fixed_asset":    _GENERIC_WIDGETS + _ASSET_SPECIFIC,
    "sales_receipt":  _GENERIC_WIDGETS + _RECEIPT_SPECIFIC,
}


# ─── Executive Report widgets ─────────────────────────────────────────────────

EXECUTIVE_WIDGETS: list[dict] = [
    {
        "id":       "w-exec-score",
        "type":     "score_ring",
        "title_ar": "التقييم العام",
        "title_en": "Overall Score",
        "data_path": "executive_summary.overall_score",
        "size":     1,
        "priority": 1,
        "icon":     "🎯",
        "color":    "blue",
        "thresholds": {"green": 85, "yellow": 60, "red": 0},
        "invert":   True,
    },
    {
        "id":       "w-exec-kpis",
        "type":     "kpi_row",
        "title_ar": "ملخص تنفيذي",
        "title_en": "Executive KPIs",
        "data_path": "executive_summary",
        "fields": [
            {"key": "compliance_rate",    "label_ar": "نسبة الامتثال",    "label_en": "Compliance Rate",   "color": "green",  "format": "percent"},
            {"key": "total_documents",    "label_ar": "إجمالي المستندات", "label_en": "Total Documents",   "color": "blue"},
            {"key": "top_issues_count",   "label_ar": "أهم المشاكل",     "label_en": "Top Issues",         "color": "red"},
            {"key": "avg_risk_score",     "label_ar": "متوسط المخاطر",    "label_en": "Avg Risk Score",    "color": "yellow"},
        ],
        "size":     4,
        "priority": 2,
        "icon":     "📊",
        "color":    "blue",
    },
    {
        "id":       "w-financial-overview",
        "type":     "kpi_row",
        "title_ar": "النظرة المالية",
        "title_en": "Financial Overview",
        "data_path": "financial_overview",
        "fields": [
            {"key": "total_revenue",  "label_ar": "إجمالي الإيرادات",  "label_en": "Total Revenue",   "color": "green",  "format": "currency"},
            {"key": "total_expenses", "label_ar": "إجمالي المصروفات",  "label_en": "Total Expenses",  "color": "red",    "format": "currency"},
            {"key": "net_profit",     "label_ar": "صافي الربح",        "label_en": "Net Profit",       "color": "blue",   "format": "currency"},
            {"key": "total_vat_payable","label_ar":"إجمالي الضريبة",   "label_en": "Total VAT",        "color": "slate",  "format": "currency"},
        ],
        "size":     4,
        "priority": 3,
        "icon":     "💼",
        "color":    "green",
    },
    {
        "id":       "w-audit-overview",
        "type":     "kpi_row",
        "title_ar": "نظرة التدقيق",
        "title_en": "Audit Overview",
        "data_path": "audit_overview",
        "fields": [
            {"key": "total_documents_audited","label_ar": "مستندات مدققة",  "label_en": "Docs Audited",      "color": "blue"},
            {"key": "clean_documents",        "label_ar": "نظيفة",          "label_en": "Clean",             "color": "green"},
            {"key": "documents_with_issues",  "label_ar": "بها مشاكل",     "label_en": "With Issues",        "color": "yellow"},
            {"key": "blocking_documents",     "label_ar": "تمنع الاعتماد", "label_en": "Blocking",           "color": "red"},
            {"key": "pass_rate",              "label_ar": "نسبة النجاح",    "label_en": "Pass Rate",         "color": "green",  "format": "percent"},
            {"key": "failure_rate",           "label_ar": "نسبة الفشل",     "label_en": "Failure Rate",      "color": "red",    "format": "percent"},
        ],
        "size":     4,
        "priority": 4,
        "icon":     "📋",
        "color":    "slate",
    },
    {
        "id":       "w-risk-distribution",
        "type":     "donut_chart",
        "title_ar": "توزيع المخاطر",
        "title_en": "Risk Distribution",
        "data_path": "risk_analysis.distribution",
        "chart_type": "donut",
        "keys": [
            {"key": "critical", "label_ar": "حرج",    "label_en": "Critical", "color": "#7c3aed"},
            {"key": "high",     "label_ar": "عالي",   "label_en": "High",     "color": "#dc2626"},
            {"key": "medium",   "label_ar": "متوسط",  "label_en": "Medium",   "color": "#d97706"},
            {"key": "low",      "label_ar": "منخفض",  "label_en": "Low",      "color": "#16a34a"},
        ],
        "size":     2,
        "priority": 5,
        "icon":     "🍩",
        "color":    "violet",
    },
    {
        "id":       "w-doc-breakdown",
        "type":     "bar_chart",
        "title_ar": "توزيع الوثائق حسب النوع",
        "title_en": "Document Breakdown",
        "data_path": "document_breakdown",
        "chart_type": "bar",
        "label_key": "document_type",
        "value_keys": ["total", "clean", "with_issues"],
        "size":     4,
        "priority": 6,
        "icon":     "📊",
        "color":    "blue",
    },
    {
        "id":       "w-top-failed-rules",
        "type":     "bar_chart",
        "title_ar": "أكثر القواعد فشلاً",
        "title_en": "Top Failed Rules",
        "data_path": "audit_overview.top_failed_rules",
        "chart_type": "horizontal_bar",
        "label_key": "rule_code",
        "value_key": "failure_count",
        "size":     3,
        "priority": 7,
        "icon":     "📉",
        "color":    "red",
    },
    {
        "id":       "w-compliance-overview",
        "type":     "kpi_row",
        "title_ar": "الامتثال الضريبي",
        "title_en": "Tax Compliance",
        "data_path": "compliance_overview",
        "fields": [
            {"key": "zatca_compliance_rate", "label_ar": "نسبة امتثال ZATCA", "label_en": "ZATCA Rate",     "color": "blue",  "format": "percent"},
            {"key": "vat_failures",          "label_ar": "أخطاء ضريبية",     "label_en": "VAT Failures",   "color": "red"},
            {"key": "vat_total_checks",      "label_ar": "فحوصات ضريبية",    "label_en": "VAT Checks",     "color": "slate"},
        ],
        "size":     3,
        "priority": 8,
        "icon":     "🏛️",
        "color":    "blue",
    },
    {
        "id":       "w-exec-ai-insights",
        "type":     "kpi_row",
        "title_ar": "رؤى الذكاء الاصطناعي",
        "title_en": "AI Fraud Indicators",
        "data_path": "ai_insights",
        "fields": [
            {"key": "fraud_indicator_count", "label_ar": "مؤشرات الاحتيال",  "label_en": "Fraud Indicators",  "color": "red"},
            {"key": "structuring_alerts",    "label_ar": "تنظيم الأموال",    "label_en": "Structuring Alerts","color": "orange"},
            {"key": "ghost_employee_alerts", "label_ar": "موظفون وهميون",    "label_en": "Ghost Employees",   "color": "violet"},
            {"key": "duplicate_alerts",      "label_ar": "مكررات",           "label_en": "Duplicate Alerts",  "color": "yellow"},
            {"key": "self_approval_alerts",  "label_ar": "موافقة ذاتية",    "label_en": "Self-Approvals",     "color": "pink"},
        ],
        "size":     4,
        "priority": 9,
        "icon":     "🤖",
        "color":    "violet",
    },
    {
        "id":       "w-exec-recommendations",
        "type":     "violations_list",
        "title_ar": "أولويات الإصلاح",
        "title_en": "Priority Recommendations",
        "data_path": "recommendations",
        "size":     4,
        "priority": 10,
        "icon":     "🗺️",
        "color":    "yellow",
        "group_by": "priority",
    },
]


# ─── Helper: get widgets for a given report ───────────────────────────────────

def get_widgets(report_type: str, document_type: str | None = None) -> list[dict]:
    """
    Return the ordered widget list for the given report context.

    Args:
        report_type:   "document_audit" | "executive"
        document_type: Required when report_type == "document_audit"

    Returns:
        List of widget dicts sorted by priority.
    """
    if report_type == "executive":
        widgets = EXECUTIVE_WIDGETS
    elif report_type == "document_audit" and document_type:
        widgets = DOCUMENT_WIDGETS.get(document_type, _GENERIC_WIDGETS)
    else:
        widgets = _GENERIC_WIDGETS

    return sorted(widgets, key=lambda w: w.get("priority", 99))


def get_widget_ids(report_type: str, document_type: str | None = None) -> list[str]:
    """Return only the widget IDs in display order."""
    return [w["id"] for w in get_widgets(report_type, document_type)]
