"""
URL patterns for storage management template (HTML) views.

Include in your main/frontend urls.py:
    path("", include("apps.storage_management.frontend_urls")),
"""
from django.urls import path

from apps.storage_management import frontend_views as views

urlpatterns = [
    path(
        "storage/providers/",
        views.providers,
        name="storage_providers",
    ),
    path(
        "storage/providers/new/",
        views.provider_form,
        name="storage_provider_new",
    ),
    path(
        "storage/providers/<uuid:pk>/edit/",
        views.provider_form,
        name="storage_provider_edit",
    ),
    path(
        "storage/org-policies/",
        views.org_policies,
        name="storage_org_policies",
    ),
    path(
        "storage/file-policies/",
        views.file_policies,
        name="storage_file_policies",
    ),
    path(
        "storage/files/",
        views.file_monitor,
        name="storage_file_monitor",
    ),
]
