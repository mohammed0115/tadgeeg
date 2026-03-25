"""
API URL router for storage management.
Include in main urls.py with:
    path("api/v1/storage/", include("apps.storage_management.urls")),
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.storage_management.views import (
    AuditFileViewSet,
    OrganizationStoragePolicyViewSet,
    StorageActivityLogViewSet,
    StorageConfigViewSet,
    StoragePolicyViewSet,
    StorageProviderViewSet,
)

router = DefaultRouter()
router.register("providers", StorageProviderViewSet, basename="storage-provider")
router.register("configs", StorageConfigViewSet, basename="storage-config")
router.register(
    "organization-policies",
    OrganizationStoragePolicyViewSet,
    basename="org-storage-policy",
)
router.register("policies", StoragePolicyViewSet, basename="storage-policy")
router.register("files", AuditFileViewSet, basename="audit-file")
router.register("activity-logs", StorageActivityLogViewSet, basename="storage-activity-log")

urlpatterns = [
    path("", include(router.urls)),
]
