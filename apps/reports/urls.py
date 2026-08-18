from django.urls import path
from . import views
from . import document_views as dv
from . import executive_report_views as ev
from . import invoice_report_views as iv

urlpatterns = [
    # ── Legacy / Existing Report Endpoints ────────────────────────────────────
    path("", views.ReportListView.as_view(), name="report-list"),
    path("export/", views.ReportExportView.as_view(), name="report-export"),
    path("<uuid:pk>/", views.ReportDetailView.as_view(), name="report-detail"),
    path("<uuid:pk>/pdf/", views.ReportPDFView.as_view(), name="report-pdf"),
    path("<uuid:pk>/excel/", views.ReportExcelExportView.as_view(), name="report-excel"),
    path("<uuid:pk>/email/", views.ReportEmailView.as_view(), name="report-email"),
    path("generate/", views.GenerateAuditReportView.as_view(), name="report-generate"),
    path("invoices/", views.InvoiceAuditReportView.as_view(), name="invoice-audit-report"),
    path("invoices/rules-summary/", views.ValidationRulesSummaryReportView.as_view(), name="rules-summary-report"),

    # 3-way match (PO ↔ Invoice ↔ GRN) — service exists at
    # apps/rule_engine/services/three_way_match.py; this is the HTTP wrapper.
    path("three-way-match/", views.ThreeWayMatchReportView.as_view(), name="three-way-match-report"),

    # P&L + Balance Sheet — derived from Ledger rows. See
    # ProfitAndLossReportView / BalanceSheetReportView in views.py for the
    # classification rules. Both endpoints surface an 'unclassified' bucket
    # so operators can clean up source data without losing visibility.
    path("profit-and-loss/", views.ProfitAndLossReportView.as_view(), name="profit-and-loss-report"),
    path("balance-sheet/",   views.BalanceSheetReportView.as_view(),  name="balance-sheet-report"),

    # Async PDF: POST queues a render task, GET polls status. Once "done",
    # client downloads from the existing sync /pdf/ endpoint (warm cache).
    path("<uuid:pk>/pdf/async/", views.ReportPDFAsyncView.as_view(), name="report-pdf-async"),
    path("pdf-jobs/<str:task_id>/", views.ReportPDFStatusView.as_view(), name="report-pdf-status"),

    # ── Document Report Endpoints (v2 — all 8 document types) ─────────────────
    # POST: generate a report for a single document
    path("document/", dv.DocumentReportGenerateView.as_view(), name="document-report-generate"),
    # GET: retrieve saved document report as JSON
    path("document/<uuid:pk>/", dv.DocumentReportDetailView.as_view(), name="document-report-detail"),
    # GET: download saved document report as PDF
    path("document/<uuid:pk>/pdf/", dv.DocumentReportPDFView.as_view(), name="document-report-pdf"),
    # GET: view saved document report as HTML
    path("document/<uuid:pk>/html/", dv.DocumentReportHTMLView.as_view(), name="document-report-html"),

    # ── Invoice Audit Report v2 Endpoints (clean service layer) ──────────────
    # POST: generate invoice audit report from InvoiceAuditReportService
    path("invoice-audit/", iv.InvoiceAuditReportGenerateView.as_view(), name="invoice-audit-generate"),
    # GET: retrieve full saved report as JSON
    path("invoice-audit/<uuid:pk>", iv.InvoiceAuditReportDetailView.as_view()),
    path("invoice-audit/<uuid:pk>/", iv.InvoiceAuditReportDetailView.as_view(), name="invoice-audit-detail"),
    # GET: view report as HTML
    path("invoice-audit/<uuid:pk>/html/", iv.InvoiceAuditReportHTMLView.as_view(), name="invoice-audit-html"),
    # GET: download report as PDF
    path("invoice-audit/<uuid:pk>/pdf/", iv.InvoiceAuditReportPDFView.as_view(), name="invoice-audit-pdf"),
    # GET: high-risk invoices sub-endpoint (?limit=N)
    path("invoice-audit/<uuid:pk>/high-risk/", iv.HighRiskInvoicesView.as_view(), name="invoice-audit-high-risk"),
    # GET: failed rules aggregate sub-endpoint (?category=X&limit=N)
    path("invoice-audit/<uuid:pk>/failed-rules/", iv.FailedRulesView.as_view(), name="invoice-audit-failed-rules"),
    # GET: supplier analysis sub-endpoint (?risk_tier=X&limit=N)
    path("invoice-audit/<uuid:pk>/supplier-analysis/", iv.SupplierAnalysisView.as_view(), name="invoice-audit-supplier-analysis"),
    # GET: compliance engine summary sub-endpoint
    path("invoice-audit/<uuid:pk>/compliance/", iv.ComplianceEngineView.as_view(), name="invoice-audit-compliance"),

    # ── Executive Report Endpoints ────────────────────────────────────────────
    # POST: generate an executive report for the organization
    path("executive/", dv.ExecutiveReportGenerateView.as_view(), name="executive-report-generate"),
    # GET: latest saved executive report
    path("executive/latest/", dv.ExecutiveReportLatestView.as_view(), name="executive-report-latest"),
    # GET: download executive report as PDF
    path("executive/<uuid:pk>/pdf/", dv.ExecutiveReportPDFView.as_view(), name="executive-report-pdf"),
    # GET: view executive report as HTML
    path("executive/<uuid:pk>/html/", dv.ExecutiveReportHTMLView.as_view(), name="executive-report-html"),
    # GET: executive report for one document, rather than for the organization.
    # Placed after the `executive/...` routes above: <str:document_type> matches
    # any single segment, and putting it first would have it swallow them.
    path(
        "<str:document_type>/<uuid:document_id>/executive-report/",
        ev.ExecutiveReportDetailView.as_view(),
        name="document-executive-report",
    ),

    # ── Dashboard Config Endpoints ────────────────────────────────────────────
    # GET: widget config for a report type/document type
    path("widgets/", dv.ReportWidgetsView.as_view(), name="report-widgets"),
    # GET: JSON Schema for report validation / frontend type generation
    path("schema/", dv.ReportSchemaView.as_view(), name="report-schema"),
]
