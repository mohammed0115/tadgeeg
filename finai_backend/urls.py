"""FinAI URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

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
    path('', include('apps.frontend.urls')),
    path("api/v1/invoices/", include("apps.invoices.urls")),
    path("api/v1/reports/", include("apps.reports.urls")),

    # Health
    path("health/", include("core.utils.health_urls")),

    # Prometheus metrics — restrict to internal network via METRICS_TOKEN env var
    path("metrics/", include("core.utils.metrics_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
