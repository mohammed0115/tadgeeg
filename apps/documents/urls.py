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
from .bulk_upload_views import (
    BulkUploadJobListCreateView, BulkUploadJobDetailView,
    BulkUploadJobRetryFailedView,
)
from .phase2_views import (
    ContractListView, ContractDetailView,
    JournalEntryListView, JournalEntryDetailView,
    SalesOrderListView, SalesOrderDetailView,
    QuotationListView, QuotationDetailView,
    ProformaInvoiceListView, ProformaInvoiceDetailView,
    ReceiptVoucherListView, ReceiptVoucherDetailView,
    CashVoucherListView, CashVoucherDetailView,
    GeneralLedgerListView, GeneralLedgerDetailView,
    LedgerListView, LedgerDetailView,
    SupplierStatementListView, SupplierStatementDetailView,
    CustomerStatementListView, CustomerStatementDetailView,
)

urlpatterns = [
    path("",        views.DocumentListView.as_view(),    name="document-list"),
    path("upload/", views.DocumentUploadView.as_view(),  name="document-upload"),
    path("<uuid:pk>/",          views.DocumentDetailView.as_view(),        name="document-detail"),
    path("<uuid:pk>/download/", views.DocumentDownloadView.as_view(),      name="document-download"),
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

    # ── Bulk upload tracking ──────────────────────────────────────────────────
    # POST   /api/v1/documents/bulk-upload-jobs/                — create job
    # GET    /api/v1/documents/bulk-upload-jobs/                — list jobs
    # GET    /api/v1/documents/bulk-upload-jobs/<id>/           — detail + items
    # POST   /api/v1/documents/bulk-upload-jobs/<id>/retry-failed/ — re-run failures
    path("bulk-upload-jobs/",                BulkUploadJobListCreateView.as_view(),  name="bulk-upload-job-list-create"),
    path("bulk-upload-jobs/<uuid:pk>/",      BulkUploadJobDetailView.as_view(),      name="bulk-upload-job-detail"),
    path("bulk-upload-jobs/<uuid:pk>/retry-failed/", BulkUploadJobRetryFailedView.as_view(), name="bulk-upload-job-retry"),

    # ── Phase-2 typed doc-type APIs ───────────────────────────────────────────
    # First 3 of the 13 phase-2 types — Contract, JournalEntry, SalesOrder.
    # Remaining 8 follow the same pattern when product priorities call for them.
    path("contracts/",                  ContractListView.as_view(),       name="contract-list"),
    path("contracts/<uuid:pk>/",        ContractDetailView.as_view(),     name="contract-detail"),
    path("journal-entries/",            JournalEntryListView.as_view(),   name="journal-entry-list"),
    path("journal-entries/<uuid:pk>/",  JournalEntryDetailView.as_view(), name="journal-entry-detail"),
    path("sales-orders/",               SalesOrderListView.as_view(),     name="sales-order-list"),
    path("sales-orders/<uuid:pk>/",     SalesOrderDetailView.as_view(),   name="sales-order-detail"),

    # ── Remaining 8 phase-2 doc types ──────────────────────────────────────────
    path("quotations/",                 QuotationListView.as_view(),         name="quotation-list"),
    path("quotations/<uuid:pk>/",       QuotationDetailView.as_view(),       name="quotation-detail"),
    path("proforma-invoices/",          ProformaInvoiceListView.as_view(),   name="proforma-invoice-list"),
    path("proforma-invoices/<uuid:pk>/",ProformaInvoiceDetailView.as_view(), name="proforma-invoice-detail"),
    path("receipt-vouchers/",           ReceiptVoucherListView.as_view(),    name="receipt-voucher-list"),
    path("receipt-vouchers/<uuid:pk>/", ReceiptVoucherDetailView.as_view(),  name="receipt-voucher-detail"),
    path("cash-vouchers/",              CashVoucherListView.as_view(),       name="cash-voucher-list"),
    path("cash-vouchers/<uuid:pk>/",    CashVoucherDetailView.as_view(),     name="cash-voucher-detail"),
    path("general-ledgers/",            GeneralLedgerListView.as_view(),     name="general-ledger-list"),
    path("general-ledgers/<uuid:pk>/",  GeneralLedgerDetailView.as_view(),   name="general-ledger-detail"),
    path("ledgers/",                    LedgerListView.as_view(),            name="ledger-list"),
    path("ledgers/<uuid:pk>/",          LedgerDetailView.as_view(),          name="ledger-detail"),
    path("supplier-statements/",        SupplierStatementListView.as_view(), name="supplier-statement-list"),
    path("supplier-statements/<uuid:pk>/", SupplierStatementDetailView.as_view(), name="supplier-statement-detail"),
    path("customer-statements/",        CustomerStatementListView.as_view(), name="customer-statement-list"),
    path("customer-statements/<uuid:pk>/", CustomerStatementDetailView.as_view(), name="customer-statement-detail"),
]
