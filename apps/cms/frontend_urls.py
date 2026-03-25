"""Frontend URL patterns for CMS admin dashboard."""
from django.urls import path
from apps.cms import frontend_views as views

urlpatterns = [
    path("", views.cms_dashboard, name="cms_dashboard"),
    path("homepage/", views.cms_homepage, name="cms_homepage"),
    path("about/", views.cms_about, name="cms_about"),
    path("pages/", views.cms_pages, name="cms_pages"),
    path("services/", views.cms_services, name="cms_services"),
    path("pricing/", views.cms_pricing, name="cms_pricing"),
    path("faq/", views.cms_faq, name="cms_faq"),
    path("jobs/", views.cms_jobs, name="cms_jobs"),
    path("leads/", views.cms_leads, name="cms_leads"),
    path("media/", views.cms_media, name="cms_media"),
    path("seo/", views.cms_seo, name="cms_seo"),
    path("settings/", views.cms_settings, name="cms_settings"),
]
