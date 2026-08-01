"""Platform management API URLs for the internal console namespace.

Mounted at ``/api/platform-admin/`` — the surface the admin console's
client-side rewrite layer (templates/layouts/base_platform_admin.html) targets.

Permission contract for this module: **every path is staff-only**
(``is_platform_user`` → ``is_staff or is_superuser``). Two of the viewsets
reused here ship weaker defaults intended for organisation-scoped mounts, so
they are re-gated locally below rather than mutated in their own apps — those
apps keep their semantics for any future org-facing mount.
"""

from django.urls import include, path

from apps.activity_logs.views import ActivityLogViewSet
from apps.cms import views as cms_views
from apps.leads import views as leads_views
from apps.partners import views as partner_views
from apps.storage_management.views import StorageProviderViewSet
from core.permissions import IsPlatformAdmin

from . import api_views

app_name = "platform_admin_api"


class _PlatformActivityLogViewSet(ActivityLogViewSet):
    """Staff-only view of the activity log.

    ``ActivityLogViewSet`` defaults to ``IsAuthenticated`` and narrows the
    queryset to the caller's own organisation for non-staff. That is sensible
    for an organisation-facing mount, but on ``/api/platform-admin/`` it would
    let an ordinary customer reach a platform-console endpoint and receive
    their own tenant's logs — contradicting the staff-only contract of this
    surface. Platform authority is required here.
    """

    permission_classes = [IsPlatformAdmin]


class _PlatformStorageProviderViewSet(StorageProviderViewSet):
    """Staff-only storage-provider administration.

    ``IsOrgAdminOrSuperAdmin`` (apps/storage_management/permissions.py) allows
    *any* authenticated user to read, and allows writes to anyone whose role is
    ``admin``/``org_admin``. ``User.Role.ADMIN`` is granted to every
    self-service registrant, and ``StorageProvider.save()`` clears
    ``is_default`` on every other row — so under the original permission a
    customer could repoint the platform's default storage backend for all
    tenants. Platform authority is required here.
    """

    permission_classes = [IsPlatformAdmin]


activity_log_list = _PlatformActivityLogViewSet.as_view({"get": "list"})
activity_log_detail = _PlatformActivityLogViewSet.as_view({"get": "retrieve"})
storage_provider_list = _PlatformStorageProviderViewSet.as_view({"get": "list", "post": "create"})
storage_provider_detail = _PlatformStorageProviderViewSet.as_view(
    {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
)
storage_provider_test = _PlatformStorageProviderViewSet.as_view({"post": "test_connection"})

urlpatterns = [
    path("stats/", api_views.PlatformDashboardStatsView.as_view(), name="stats"),
    path("organizations/", api_views.PlatformOrganizationListView.as_view(), name="organizations"),
    path("organizations/<uuid:pk>/", api_views.PlatformOrganizationDetailView.as_view(), name="organization-detail"),
    path("intro-video/", api_views.PlatformIntroVideoCompatView.as_view(), name="intro-video"),
    path("faq/", api_views.PlatformFAQCompatView.as_view(), name="faq-compat"),
    path("seo/", api_views.PlatformSEOCompatView.as_view(), name="seo-compat"),
    path("cms/pages/", cms_views.CMSPageListView.as_view(), name="cms-pages"),
    path("cms/pages/stats/", api_views.PlatformCMSPageStatsView.as_view(), name="cms-pages-stats"),
    path("cms/pages/<slug:slug>/", cms_views.CMSPageDetailView.as_view(), name="cms-page-detail"),
    path("cms/pages/<slug:slug>/publish/", cms_views.CMSPagePublishView.as_view(), name="cms-page-publish"),
    path("cms/pages/<slug:slug>/archive/", cms_views.CMSPageArchiveView.as_view(), name="cms-page-archive"),
    path("homepage/", cms_views.HomepageContentView.as_view(), name="homepage"),
    path("about/", cms_views.AboutSectionView.as_view(), name="about"),
    path("services/", cms_views.ServiceListView.as_view(), name="services"),
    path("services/<int:pk>/", cms_views.ServiceDetailView.as_view(), name="service-detail"),
    path("pricing/", cms_views.PricingPlanListView.as_view(), name="pricing"),
    path("pricing/<int:pk>/", cms_views.PricingPlanDetailView.as_view(), name="pricing-detail"),
    path("pricing/<int:plan_id>/features/", cms_views.PricingFeatureCreateView.as_view(), name="pricing-feature-create"),
    path("pricing/features/<int:pk>/", cms_views.PricingFeatureDeleteView.as_view(), name="pricing-feature-delete"),
    path("faq/categories/", cms_views.FAQCategoryListView.as_view(), name="faq-categories"),
    path("faq/categories/<int:pk>/", cms_views.FAQCategoryDetailView.as_view(), name="faq-category-detail"),
    path("faq/items/", cms_views.FAQItemListView.as_view(), name="faq-items"),
    path("faq/items/<int:pk>/", cms_views.FAQItemDetailView.as_view(), name="faq-item-detail"),
    # ── jobs/* — intentionally NOT routed ────────────────────────────────
    # apps.jobs is quarantined (absent from INSTALLED_APPS). Importing
    # apps.jobs.views raises RuntimeError at import time, and because
    # include() imports this module while the URL tree is built, restoring
    # these seven paths would stop the whole process from booting — not just
    # break /jobs/. The recruitment UI is disabled at the template level so
    # nothing requests them. See docs/adr/0003-quarantine-apps-jobs.md.
    # ── Trial Users Dashboard (Phase 1, §B) ──────────────────────────────
    # Staff-only like everything else on this prefix. Declared before
    # leads/<uuid:pk>/ so the literal segments win over the uuid converter.
    path("trial-users/summary/", api_views.TrialUsersSummaryView.as_view(), name="trial-users-summary"),
    path("trial-users/export.xlsx", api_views.TrialUsersExportXlsxView.as_view(), name="trial-users-export-xlsx"),
    path("trial-users/export.pdf", api_views.TrialUsersExportPdfView.as_view(), name="trial-users-export-pdf"),
    path("trial-users/<uuid:pk>/convert/", api_views.TrialUserConvertView.as_view(), name="trial-user-convert"),
    path("trial-users/", api_views.TrialUsersListView.as_view(), name="trial-users"),

    # ── Partner administration (Phase 2A, §C/§F) ─────────────────────────
    # Staff-only. Publish/hide are audited via apps.partners.services.
    # Applications (Phase 2B). Literal segments declared before <uuid:pk> so
    # they win over the converter.
    path("partner-applications/export.xlsx", api_views.PartnerApplicationExportXlsxView.as_view(), name="partner-applications-export-xlsx"),
    path("partner-applications/export.pdf", api_views.PartnerApplicationExportPdfView.as_view(), name="partner-applications-export-pdf"),
    path("partner-applications/<uuid:pk>/notes/", api_views.PartnerApplicationNoteView.as_view(), name="partner-application-note"),
    path("partner-applications/<uuid:pk>/<str:action>/", api_views.PartnerApplicationTransitionView.as_view(), name="partner-application-transition"),
    path("partner-applications/<uuid:pk>/", api_views.PartnerApplicationDetailView.as_view(), name="partner-application-detail"),
    path("partner-applications/", api_views.PartnerApplicationListView.as_view(), name="partner-applications"),
    path("partner-attachments/<uuid:pk>/download/", partner_views.PartnerApplicationAttachmentDownloadView.as_view(), name="partner-attachment-download"),

    path("partners/reorder/", api_views.PartnerReorderView.as_view(), name="partner-reorder"),
    path("partners/<uuid:pk>/publish/", api_views.PartnerPublishView.as_view(), name="partner-publish"),
    path("partners/<uuid:pk>/hide/", api_views.PartnerHideView.as_view(), name="partner-hide"),
    path("partners/<uuid:pk>/", api_views.PartnerDetailView.as_view(), name="partner-detail"),
    path("partners/", api_views.PartnerListCreateView.as_view(), name="partners"),

    path("leads/", leads_views.AdminLeadListView.as_view(), name="leads"),
    path("leads/stats/", leads_views.LeadStatsView.as_view(), name="leads-stats"),
    path("leads/mark-all-read/", api_views.PlatformMarkAllLeadsReadView.as_view(), name="leads-mark-all-read"),
    path("leads/<uuid:pk>/", leads_views.AdminLeadDetailView.as_view(), name="lead-detail"),
    path("leads/<uuid:pk>/status/", leads_views.AdminLeadStatusView.as_view(), name="lead-status"),
    path("leads/<uuid:pk>/assign/", leads_views.AdminLeadAssignView.as_view(), name="lead-assign"),
    path("leads/<uuid:pk>/read/", leads_views.AdminLeadMarkReadView.as_view(), name="lead-read"),
    path("leads/<uuid:pk>/notes/", leads_views.AdminLeadNoteListView.as_view(), name="lead-notes"),
    path("leads/<uuid:pk>/spam/", leads_views.AdminLeadSpamView.as_view(), name="lead-spam"),
    path("seo/list/", cms_views.SEOSettingListView.as_view(), name="seo"),
    path("seo/<str:page_key>/", cms_views.SEOSettingDetailView.as_view(), name="seo-detail"),
    path("media/", cms_views.MediaAssetListView.as_view(), name="media"),
    path("media/<uuid:pk>/", cms_views.MediaAssetDetailView.as_view(), name="media-detail"),
    path("storage/providers/", storage_provider_list, name="storage-providers"),
    path("storage/providers/<uuid:pk>/", storage_provider_detail, name="storage-provider-detail"),
    path("storage/providers/<uuid:pk>/test-connection/", storage_provider_test, name="storage-provider-test"),
    path("settings/", api_views.PlatformSettingListView.as_view(), name="settings"),
    path("settings/<str:key>/", api_views.PlatformSettingDetailView.as_view(), name="setting-detail"),
    path("monitoring/", include("apps.system_monitoring.api_urls")),
    path("activity-logs/", activity_log_list, name="activity-logs"),
    path("activity-logs/stats/", api_views.PlatformActivityLogStatsView.as_view(), name="activity-logs-stats"),
    path("activity-logs/<uuid:pk>/", activity_log_detail, name="activity-log-detail"),
]
