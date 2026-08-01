"""URL entrypoints for the internal Get Solution platform console."""

from django.urls import include, path

from . import views

app_name = "platform_admin"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # CRM-1C: read-only Platform CRM shell → namespace platform_admin:crm
    path("crm/", include("apps.platform_admin.crm_urls")),
    path("organizations/", views.organizations, name="organizations"),
    path("cms/", views.cms_pages, name="cms_pages"),
    path("homepage/", views.homepage_editor, name="homepage"),
    path("about/", views.about_editor, name="about"),
    path("services/", views.services_editor, name="services"),
    path("pricing/", views.pricing_editor, name="pricing"),
    path("faq/", views.faq_editor, name="faq"),
    path("intro-video/", views.intro_video_editor, name="intro_video"),
    path("jobs/", views.jobs_manager, name="jobs"),
    path("partner-applications/", views.partner_applications, name="partner_applications"),
    path("partners/", views.partners_manager, name="partners"),
    path("trial-users/", views.trial_users, name="trial_users"),
    path("leads/", views.leads_manager, name="leads"),
    path("seo/", views.seo_settings, name="seo"),
    path("media/", views.media_library, name="media"),
    path("storage/", views.storage_providers, name="storage"),
    path("settings/", views.platform_settings, name="settings"),
    path("monitoring/", views.monitoring, name="monitoring"),
    path("activity-logs/", views.activity_logs, name="activity_logs"),
]
