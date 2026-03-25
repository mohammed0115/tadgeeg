"""Auditing App URL Configuration."""

from django.urls import path

from .views import (
    AuditDocumentUploadView,
    AuditDocumentResultView,
    AuditDocumentHistoryView,
    AccountingRuleEvaluationListView,
    ReportAccountingRulesListView,
    InvoiceAccountingRulesListView,
    invoice_gaap_evaluation_view,
    invoice_ifrs_evaluation_view,
    report_accounting_rules_summary_view,
    report_failed_rules_view,
    compare_standards_view,
)

app_name = "auditor"

urlpatterns = [
    # Existing document auditor endpoints
    path("upload/", AuditDocumentUploadView.as_view(), name="upload"),
    path("result/<uuid:pk>/", AuditDocumentResultView.as_view(), name="result"),
    path("history/", AuditDocumentHistoryView.as_view(), name="history"),
    
    # Accounting rules evaluation endpoints
    # List all accounting rule evaluations with optional filters
    path(
        "accounting-rules/",
        AccountingRuleEvaluationListView.as_view(),
        name="accounting-rules-list",
    ),
    # Get accounting rules for a specific report
    path(
        "reports/<uuid:report_id>/accounting-rules/",
        ReportAccountingRulesListView.as_view(),
        name="report-accounting-rules",
    ),
    # Get accounting rules summary for a report
    path(
        "reports/<uuid:report_id>/accounting-rules-summary/",
        report_accounting_rules_summary_view,
        name="report-accounting-rules-summary",
    ),
    # Get failed rules for a report
    path(
        "reports/<uuid:report_id>/failed-rules/",
        report_failed_rules_view,
        name="report-failed-rules",
    ),
    # Get accounting rules for a specific invoice
    path(
        "invoices/<uuid:invoice_id>/accounting-rules/",
        InvoiceAccountingRulesListView.as_view(),
        name="invoice-accounting-rules",
    ),
    # Evaluate a single invoice against GAAP rules
    path(
        "invoices/<uuid:invoice_id>/evaluate/gaap/",
        invoice_gaap_evaluation_view,
        name="invoice-gaap-evaluation",
    ),
    # Evaluate a single invoice against IFRS rules
    path(
        "invoices/<uuid:invoice_id>/evaluate/ifrs/",
        invoice_ifrs_evaluation_view,
        name="invoice-ifrs-evaluation",
    ),
    # Compare GAAP vs IFRS compliance for an invoice
    path(
        "invoices/<uuid:invoice_id>/compare-standards/",
        compare_standards_view,
        name="invoice-compare-standards",
    ),
]
