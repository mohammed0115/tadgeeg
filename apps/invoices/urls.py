"""Invoice Auditing URL Patterns"""

from django.urls import path
from . import views

urlpatterns = [
    # ── Upload (single / multiple / ZIP) ──────────────────────────────────────
    path("upload/",                     views.InvoiceUploadView.as_view(),           name="invoice-upload"),

    # ── Invoice CRUD ───────────────────────────────────────────────────────────
    path("",                            views.InvoiceListView.as_view(),             name="invoice-list"),
    path("<uuid:pk>/",                  views.InvoiceDetailView.as_view(),           name="invoice-detail"),
    path("<uuid:pk>/download/",         views.InvoiceDownloadView.as_view(),         name="invoice-download"),
    path("<uuid:pk>/review/",           views.InvoiceManualReviewView.as_view(),     name="invoice-review"),
    path("<uuid:pk>/approve/",          views.InvoiceApproveView.as_view(),          name="invoice-approve"),
    path("<uuid:pk>/escalate/",         views.InvoiceEscalateView.as_view(),         name="invoice-escalate"),
    path("<uuid:pk>/revalidate/",       views.InvoiceRevalidateView.as_view(),       name="invoice-revalidate"),

    # ── Batches ────────────────────────────────────────────────────────────────
    path("batches/",                    views.InvoiceBatchListView.as_view(),        name="batch-list"),
    path("batches/<uuid:pk>/",          views.InvoiceBatchDetailView.as_view(),      name="batch-detail"),

    # ── Vendor Intelligence ───────────────────────────────────────────────────
    path("vendors/",                    views.VendorListView.as_view(),              name="vendor-list"),
    path("vendors/high-risk/",          views.HighRiskVendorListView.as_view(),      name="vendor-high-risk-list"),
    path("vendors/<uuid:pk>/",          views.VendorDetailView.as_view(),            name="vendor-detail"),

    # ── Reports ────────────────────────────────────────────────────────────────
    path("reports/risk/",               views.InvoiceRiskReportView.as_view(),       name="invoice-risk-report"),
    path("reports/duplicates/",         views.DuplicateInvoiceReportView.as_view(),  name="invoice-duplicate-report"),
    path("reports/vendors/",            views.VendorRiskReportView.as_view(),        name="vendor-risk-report"),
    path("reports/spend/",              views.SpendAnalysisReportView.as_view(),     name="spend-analysis-report"),

    # ── Reference ─────────────────────────────────────────────────────────────
    path("rules/",                      views.ValidationRulesListView.as_view(),     name="validation-rules"),
]
