"""Organization dashboard URLs for tenant-facing routes."""

from django.urls import path

from . import views

app_name = "vendor_dashboard"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("files/", views.files, name="files"),
    path("folders/", views.folders, name="folders"),
    path("upload/", views.upload, name="upload"),
    path("audits/", views.audits, name="audits"),
    path("audit-results/", views.audit_results, name="audit_results"),
    path("reports/", views.reports, name="reports"),
    path("team/", views.team, name="team"),
    path("settings/", views.org_settings, name="settings"),
    path("storage/", views.storage_usage, name="storage"),
    path("billing/", views.billing, name="billing"),
    path("notifications/", views.notifications, name="notifications"),
]
