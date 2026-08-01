"""Tadgeeg AI URL configuration."""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from core.health_check_views import FullHealthCheckView, HealthCheckView, OpenAIHealthView, PipelineStatusView, ExtendedHealthView
from apps.audit.views import AuditDashboardOverviewView
from apps.invoices.views import (
    InvoiceApproveView,
    InvoiceBulkActionView,
    InvoiceDetailView,
    InvoiceEscalateView,
    InvoiceManualReviewView,
    InvoiceRevalidateView,
    VendorListView,
)
from apps.compliance.views import ComplianceDashboardView
from apps.authentication.views import UserListView
from apps.payments import views as payments_views

urlpatterns = [
    # Public, no-/api/v1 payment redirect + webhook URLs. Payment providers
    # (Moyasar) redirect the customer to the callback and POST webhooks to
    # these short paths (configured in MOYASAR_CALLBACK_URL / dashboard); the
    # full payments API stays mounted under /api/v1/payments/ below.
    path("payments/callback/<str:provider>/", payments_views.PaymentCallbackView.as_view(), name="payments-callback-public"),
    path("payments/webhooks/moyasar/", payments_views.webhook_moyasar, name="payments-webhook-moyasar-public"),

    # Internationalization (language switching)
    path("i18n/", include("django.conf.urls.i18n")),

    # Admin
    path(getattr(settings, "ADMIN_URL", "admin/"), admin.site.urls),
    path("django-admin/", RedirectView.as_view(pattern_name="admin:index", permanent=False)),
    path("accounts/login/", RedirectView.as_view(url="/login/", permanent=False)),
    path("accounts/register/", RedirectView.as_view(url="/register/", permanent=False)),
    path("accounts/logout/", RedirectView.as_view(url="/logout/", permanent=False)),

    # API Schema / docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    # API v1
    path("api/v1/auth/", include("apps.authentication.urls")),
    path("api/v1/mobile/", include("apps.api_mobile.urls")),
    path("api/v1/alerts/", include("apps.alerts.urls")),
    path("api/v1/zatca/", include("apps.zatca.urls")),
    path("api/v1/banking/", include("apps.banking.urls")),
    path("api/v1/ledger/", include("apps.ledger.urls")),
    path("api/v1/procurement/", include("apps.procurement.urls")),
    path("api/v1/documents/", include("apps.documents.urls")),
    path("api/v1/transactions/", include("apps.transactions.urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/compliance/", include("apps.compliance.urls")),
    path("api/v1/compliance/dashboard/", ComplianceDashboardView.as_view(), name="compliance-dashboard-compat"),
    path("api/v1/payments/", include(("apps.payments.urls", "payments"), namespace="payments")),
    path("billing/", include(("apps.billing.urls", "billing"), namespace="billing")),
    path("audit/dashboard/overview/", AuditDashboardOverviewView.as_view(), name="dashboard-overview-compat"),
    path("invoices/<uuid:pk>/",            InvoiceDetailView.as_view(),        name="invoice-detail-compat"),
    path("invoices/<uuid:pk>/review/",     InvoiceManualReviewView.as_view(),  name="invoice-review-compat"),
    path("invoices/<uuid:pk>/approve/",    InvoiceApproveView.as_view(),       name="invoice-approve-compat"),
    path("invoices/<uuid:pk>/revalidate/", InvoiceRevalidateView.as_view(),    name="invoice-revalidate-compat"),
    path("invoices/<uuid:pk>/escalate/",   InvoiceEscalateView.as_view(),      name="invoice-escalate-compat"),
    path("invoices/bulk/",                 InvoiceBulkActionView.as_view(),    name="invoice-bulk-compat"),
    # Auditing app (AI document auditor)
    path("auditor/", include("apps.auditing.urls")),
    # ── Platform admin console API (staff / Get Solution internal) ──────────
    # namespace = "platform_admin_api" → reverse("platform_admin_api:stats")
    #
    # This prefix is not arbitrary: the admin console's client-side rewrite
    # layer (templates/layouts/base_platform_admin.html) translates every
    # legacy /api/v1/cms/admin/* and /api/v1/platform/* call to
    # /api/platform-admin/*, and this module's prefixes match that table
    # element for element. Before this mount existed, all 61 admin API call
    # sites in the console returned 404 — the console rendered but could not
    # load or save anything.
    #
    # Every path here is staff-only; see the permission contract documented in
    # apps/platform_management/api_urls.py. There is no middleware fronting
    # this prefix: core/namespace_access.py defines PLATFORM_PREFIXES covering
    # it, but NamespaceAccessControlMiddleware is NOT in settings.MIDDLEWARE,
    # so per-view permission classes are the only layer. Do not add a path
    # here without a test that executes the view body as staff and asserts
    # 403 for a non-staff authenticated user.
    path(
        "api/platform-admin/",
        include("apps.platform_management.api_urls", namespace="platform_admin_api"),
    ),

    # ── Platform admin console (staff / Get Solution internal) ──────────────
    # namespace = "platform_admin"  →  reverse("platform_admin:dashboard")
    # IMPORTANT: must come before the frontend catch-all include
    path(
        "platform-admin/",
        include("apps.platform_management.urls", namespace="platform_admin"),
    ),

    # Frontend pages (includes the executive `/dashboard/` landing page).
    # Keep this before the vendor dashboard include so the exact `/dashboard/`
    # route resolves to `frontend:dashboard`, while `/dashboard/files/` and the
    # rest of the organisation workspace still resolve to `vendor_dashboard:*`.
    path('', include('apps.frontend.urls')),

    # ── Vendor / Organisation dashboard ─────────────────────────────────────
    # namespace = "vendor_dashboard"  →  reverse("vendor_dashboard:dashboard")
    path(
        "dashboard/",
        include("apps.vendor_dashboard.urls", namespace="vendor_dashboard"),
    ),

    path("api/v1/invoices/", include("apps.invoices.urls")),
    path("api/v1/reports/", include("apps.reports.urls")),
    path("api/v1/rule-engine/", include("apps.rule_engine.api.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    path("api/v1/assistant/", include("apps.assistant.urls")),
    path("api/v1/webhooks/", include("apps.webhooks.urls")),
    # Public partner application submission (Phase 2B). Unauthenticated and
    # file-accepting — throttled per IP via the partner_application scope.
    path("api/v1/partners/", include(("apps.partners.urls", "partners"), namespace="partners")),
    path("api/v1/export/", include("apps.data_export.urls")),
    path("api/v1/health/", HealthCheckView.as_view(), name="api-health"),
    path("api/v1/health/full/", FullHealthCheckView.as_view(), name="api-health-full"),
    path("api/v1/health/openai/", OpenAIHealthView.as_view(), name="api-health-openai"),
    path("api/v1/health/extended/", ExtendedHealthView.as_view(), name="api-health-extended"),
    path("api/v1/status/", PipelineStatusView.as_view(), name="api-status"),
    path("api/v1/users/", UserListView.as_view(), name="user-list-compat"),
    path("api/v1/vendors/", VendorListView.as_view(), name="vendor-list-compat"),

    # Health
    path("health/", include("core.utils.health_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "apps.frontend.page_views.page_not_found"
handler500 = "apps.frontend.page_views.server_error"
handler403 = "apps.frontend.page_views.permission_denied"
