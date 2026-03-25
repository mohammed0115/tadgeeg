"""Platform admin API URL configuration."""

from django.urls import path

from apps.activity_logs.views import ActivityLogViewSet
from apps.cms import views as cms_views
from apps.jobs import views as jobs_views
from apps.leads import views as leads_views
from apps.storage_management.views import StorageProviderViewSet

from . import api_views

app_name = "platform_admin_api"

activity_log_list = ActivityLogViewSet.as_view({"get": "list"})
activity_log_detail = ActivityLogViewSet.as_view({"get": "retrieve"})
storage_provider_list = StorageProviderViewSet.as_view({"get": "list", "post": "create"})
storage_provider_detail = StorageProviderViewSet.as_view(
    {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
)
storage_provider_test = StorageProviderViewSet.as_view({"post": "test_connection"})

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
    path("jobs/", jobs_views.AdminJobListView.as_view(), name="jobs"),
    path("jobs/<uuid:pk>/", jobs_views.AdminJobDetailView.as_view(), name="job-detail"),
    path("jobs/<uuid:pk>/publish/", jobs_views.AdminJobPublishView.as_view(), name="job-publish"),
    path("jobs/<uuid:pk>/close/", jobs_views.AdminJobCloseView.as_view(), name="job-close"),
    path("jobs/stats/", jobs_views.JobStatsView.as_view(), name="jobs-stats"),
    path("jobs/applications/", jobs_views.AdminApplicationListView.as_view(), name="job-applications"),
    path("jobs/applications/<uuid:pk>/", jobs_views.AdminApplicationDetailView.as_view(), name="job-application-detail"),
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
    path("monitoring/health/", api_views.PlatformMonitoringHealthView.as_view(), name="monitoring-health"),
    path("monitoring/metrics/", api_views.PlatformMonitoringMetricsView.as_view(), name="monitoring-metrics"),
    path("monitoring/errors/", api_views.PlatformMonitoringErrorsView.as_view(), name="monitoring-errors"),
    path("activity-logs/", activity_log_list, name="activity-logs"),
    path("activity-logs/stats/", api_views.PlatformActivityLogStatsView.as_view(), name="activity-logs-stats"),
    path("activity-logs/<uuid:pk>/", activity_log_detail, name="activity-log-detail"),
]
