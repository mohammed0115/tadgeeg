"""
URL configuration for the file management app.

Mount this under a prefix in the project's main urls.py, e.g.::

    path("api/file-management/", include("apps.file_management.urls")),
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.file_management.views import AuditFileViewSet, FolderViewSet

router = DefaultRouter()
router.register("folders", FolderViewSet, basename="folder")
router.register("files", AuditFileViewSet, basename="managed-file")

urlpatterns = [
    path("", include(router.urls)),
]
