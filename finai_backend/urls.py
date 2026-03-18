"""FinAI URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from core.health_check_views import HealthCheckView, PipelineStatusView
from apps.audit.views import AuditDashboardOverviewView
from apps.invoices.views import (
    InvoiceApproveView,
    InvoiceDetailView,
    InvoiceManualReviewView,
    InvoiceRevalidateView,
)

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),
    path("django-admin/", RedirectView.as_view(pattern_name="admin:index", permanent=False)),
    path("accounts/login/", RedirectView.as_view(url="/login/", permanent=False)),
    path("accounts/register/", RedirectView.as_view(url="/register/", permanent=False)),
    path("accounts/logout/", RedirectView.as_view(url="/logout/", permanent=False)),

    # API Schema
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    # API v1
    path("api/v1/auth/", include("apps.authentication.urls")),
    path("api/v1/documents/", include("apps.documents.urls")),
    path("api/v1/transactions/", include("apps.transactions.urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/compliance/", include("apps.compliance.urls")),
    path("audit/dashboard/overview/", AuditDashboardOverviewView.as_view(), name="dashboard-overview-compat"),
    path("invoices/<uuid:pk>/", InvoiceDetailView.as_view(), name="invoice-detail-compat"),
    path("invoices/<uuid:pk>/review/", InvoiceManualReviewView.as_view(), name="invoice-review-compat"),
    path("invoices/<uuid:pk>/approve/", InvoiceApproveView.as_view(), name="invoice-approve-compat"),
    path("invoices/<uuid:pk>/revalidate/", InvoiceRevalidateView.as_view(), name="invoice-revalidate-compat"),
    path('', include('apps.frontend.urls')),
    path("api/v1/invoices/", include("apps.invoices.urls")),
    path("api/v1/reports/", include("apps.reports.urls")),
    path("api/v1/health/", HealthCheckView.as_view(), name="api-health"),
    path("api/v1/status/", PipelineStatusView.as_view(), name="api-status"),

    # Health
    path("health/", include("core.utils.health_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
