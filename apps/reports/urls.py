from django.urls import path
from . import views

urlpatterns = [
    # قائمة وتفاصيل التقارير المحفوظة
    path("", views.ReportListView.as_view(), name="report-list"),
    path("export/", views.ReportExportView.as_view(), name="report-export"),
    path("<uuid:pk>/", views.ReportDetailView.as_view(), name="report-detail"),
    path("<uuid:pk>/pdf/", views.ReportPDFView.as_view(), name="report-pdf"),

    # توليد تقرير شامل (فواتير + معاملات + AI narrative)
    path("generate/", views.GenerateAuditReportView.as_view(), name="report-generate"),

    # تقرير تدقيق الفواتير المخصص (البنود الـ 30 كاملة)
    path("invoices/", views.InvoiceAuditReportView.as_view(), name="invoice-audit-report"),

    # تقرير تفصيلي: معدل نجاح/فشل كل بند من البنود الـ 30
    path("invoices/rules-summary/", views.ValidationRulesSummaryReportView.as_view(), name="rules-summary-report"),
]
