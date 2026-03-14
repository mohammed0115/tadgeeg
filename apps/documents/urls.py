"""Documents URLs — base + typed endpoints for all 7 financial document types."""
from django.urls import path
from . import views
from .typed_views import (
    TypedDocumentUploadView, DocumentStatsView,
    PurchaseOrderListView, PurchaseOrderDetailView, PurchaseOrderApproveView,
    BankStatementListView, BankStatementDetailView,
    PayrollListView, PayrollDetailView,
    ExpenseReportListView, ExpenseReportDetailView,
    VATReturnListView, VATReturnDetailView,
    FixedAssetListView, FixedAssetDetailView,
    SalesReceiptListView, SalesReceiptDetailView,
)

urlpatterns = [
    path("",        views.DocumentListView.as_view(),    name="document-list"),
    path("upload/", views.DocumentUploadView.as_view(),  name="document-upload"),
    path("<uuid:pk>/",          views.DocumentDetailView.as_view(),        name="document-detail"),
    path("<uuid:pk>/process/",  views.DocumentProcessView.as_view(),       name="document-process"),
    path("<uuid:pk>/analyse/",  views.DocumentAnalyseView.as_view(),       name="document-analyse"),
    path("<uuid:pk>/analysis/", views.DocumentAnalysisResultView.as_view(),name="document-analysis-result"),
    path("<uuid:pk>/validate/", views.DocumentValidateView.as_view(),      name="document-validate"),
    path("upload/typed/",      TypedDocumentUploadView.as_view(),   name="typed-document-upload"),
    path("stats/",             DocumentStatsView.as_view(),         name="document-stats"),
    path("purchase-orders/",                   PurchaseOrderListView.as_view(),    name="purchase-order-list"),
    path("purchase-orders/<uuid:pk>/",         PurchaseOrderDetailView.as_view(),  name="purchase-order-detail"),
    path("purchase-orders/<uuid:pk>/approve/", PurchaseOrderApproveView.as_view(), name="purchase-order-approve"),
    path("bank-statements/",           BankStatementListView.as_view(),   name="bank-statement-list"),
    path("bank-statements/<uuid:pk>/", BankStatementDetailView.as_view(), name="bank-statement-detail"),
    path("payroll/",           PayrollListView.as_view(),   name="payroll-list"),
    path("payroll/<uuid:pk>/", PayrollDetailView.as_view(), name="payroll-detail"),
    path("expense-reports/",           ExpenseReportListView.as_view(),   name="expense-report-list"),
    path("expense-reports/<uuid:pk>/", ExpenseReportDetailView.as_view(), name="expense-report-detail"),
    path("vat-returns/",           VATReturnListView.as_view(),   name="vat-return-list"),
    path("vat-returns/<uuid:pk>/", VATReturnDetailView.as_view(), name="vat-return-detail"),
    path("fixed-assets/",           FixedAssetListView.as_view(),   name="fixed-asset-list"),
    path("fixed-assets/<uuid:pk>/", FixedAssetDetailView.as_view(), name="fixed-asset-detail"),
    path("sales-receipts/",           SalesReceiptListView.as_view(),   name="sales-receipt-list"),
    path("sales-receipts/<uuid:pk>/", SalesReceiptDetailView.as_view(), name="sales-receipt-detail"),
]
