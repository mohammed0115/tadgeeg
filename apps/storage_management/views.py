"""
DRF API ViewSets for storage management.
"""
import logging

from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from apps.storage_management.exceptions import (
    StorageConfigurationError,
    StorageValidationError,
)
from apps.storage_management.models import (
    AuditFile,
    FileStorageMapping,
    OrganizationStoragePolicy,
    StorageActivityLog,
    StorageConfig,
    StoragePolicy,
    StorageProvider,
)
from apps.storage_management.permissions import BelongsToSameOrg, IsOrgAdminOrSuperAdmin, IsOrgMember
from apps.storage_management.serializers import (
    AuditFileSerializer,
    FileStorageMappingSerializer,
    OrganizationStoragePolicySerializer,
    StorageActivityLogSerializer,
    StorageConfigSerializer,
    StoragePolicySerializer,
    StorageProviderSerializer,
)
from apps.storage_management.services.storage.resolver import StorageResolver
from apps.storage_management.services.storage.service import StorageService
from apps.storage_management.models import StorageActivityLog

logger = logging.getLogger(__name__)
_service = StorageService()
_resolver = StorageResolver()


class StorageProviderViewSet(ModelViewSet):
    """
    CRUD for storage providers.
    Includes a test-connection action that verifies backend reachability.
    """

    queryset = StorageProvider.objects.all()
    serializer_class = StorageProviderSerializer
    permission_classes = [IsOrgAdminOrSuperAdmin]

    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request, pk=None):
        """
        POST /api/v1/storage/providers/{id}/test-connection/
        Instantiates the backend and calls test_connection().
        Returns {"success": bool, "message": str, "latency_ms": int}.
        """
        provider = self.get_object()
        try:
            backend = _resolver._build_backend(provider)
            result = backend.test_connection()
        except StorageConfigurationError as exc:
            result = {"success": False, "message": str(exc), "latency_ms": 0}
        except Exception as exc:
            result = {"success": False, "message": f"Unexpected error: {exc}", "latency_ms": 0}

        # Log the test attempt
        StorageActivityLog.objects.create(
            user=request.user,
            organization=getattr(request.user, "organization", None),
            action=StorageActivityLog.Action.CONNECTION_TESTED,
            entity_type="StorageProvider",
            entity_id=str(provider.id),
            metadata=result,
            success=result.get("success", False),
            error_message="" if result.get("success") else result.get("message", ""),
        )

        http_status = status.HTTP_200_OK if result.get("success") else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=http_status)

    @action(detail=True, methods=["patch"], url_path="toggle-active")
    def toggle_active(self, request, pk=None):
        """PATCH /api/v1/storage/providers/{id}/toggle-active/"""
        provider = self.get_object()
        provider.is_active = not provider.is_active
        provider.save(update_fields=["is_active", "updated_at"])
        serializer = self.get_serializer(provider)
        return Response(serializer.data)


class StorageConfigViewSet(ModelViewSet):
    """
    CRUD for storage provider configurations (credentials, endpoints, etc.).
    Non-staff users only see configs belonging to their organisation.
    """

    serializer_class = StorageConfigSerializer
    permission_classes = [IsOrgAdminOrSuperAdmin, BelongsToSameOrg]

    def get_queryset(self):
        qs = StorageConfig.objects.select_related("provider", "organization")
        if self.request.user.is_staff:
            return qs.all()
        user_org = getattr(self.request.user, "organization", None)
        if user_org:
            return qs.filter(organization=user_org)
        return qs.none()


class OrganizationStoragePolicyViewSet(ModelViewSet):
    """
    CRUD for per-organisation storage routing policies.
    """

    serializer_class = OrganizationStoragePolicySerializer
    permission_classes = [IsOrgAdminOrSuperAdmin, BelongsToSameOrg]

    def get_queryset(self):
        qs = OrganizationStoragePolicy.objects.select_related(
            "organization",
            "primary_storage",
            "backup_storage",
            "archive_storage",
            "temp_storage",
        )
        if self.request.user.is_staff:
            return qs.all()
        user_org = getattr(self.request.user, "organization", None)
        if user_org:
            return qs.filter(organization=user_org)
        return qs.none()


class StoragePolicyViewSet(ModelViewSet):
    """
    CRUD for per-organisation file policies (size limits, allowed types, etc.).
    """

    serializer_class = StoragePolicySerializer
    permission_classes = [IsOrgAdminOrSuperAdmin, BelongsToSameOrg]

    def get_queryset(self):
        qs = StoragePolicy.objects.select_related("organization")
        if self.request.user.is_staff:
            return qs.all()
        user_org = getattr(self.request.user, "organization", None)
        if user_org:
            return qs.filter(organization=user_org)
        return qs.none()


class AuditFileViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    GenericViewSet,
):
    """
    File upload, listing, and deletion.
    Files are immutable once stored — update/partial_update are intentionally disabled.
    """

    serializer_class = AuditFileSerializer
    permission_classes = [IsOrgMember, BelongsToSameOrg]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        qs = AuditFile.objects.select_related(
            "organization", "uploaded_by"
        ).prefetch_related("storage_mappings__storage_provider")
        if self.request.user.is_staff:
            return qs.all()
        user_org = getattr(self.request.user, "organization", None)
        if user_org:
            return qs.filter(organization=user_org)
        return qs.none()

    def create(self, request, *args, **kwargs):
        """
        POST /api/v1/storage/files/
        Expects multipart/form-data with a 'file' field.
        """
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"detail": "No file provided. Use multipart/form-data with a 'file' field."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_org = getattr(request.user, "organization", None)
        if not user_org and not request.user.is_staff:
            return Response(
                {"detail": "Your account is not associated with an organisation."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Allow staff to specify an org; default to user's org
        organization = user_org
        if request.user.is_staff and request.data.get("organization_id"):
            from apps.authentication.models import Organization
            try:
                organization = Organization.objects.get(pk=request.data["organization_id"])
            except Organization.DoesNotExist:
                return Response(
                    {"detail": "Organisation not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        purpose = request.data.get("purpose", "upload")

        try:
            result = _service.upload_file(
                file_obj=uploaded_file,
                organization=organization,
                uploaded_by=request.user,
                purpose=purpose,
                original_name=uploaded_file.name,
                content_type=uploaded_file.content_type,
            )
        except StorageValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except StorageConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception("Unexpected error during file upload: %s", exc)
            return Response(
                {"detail": "File upload failed due to an internal error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Return the full AuditFile representation
        audit_file = AuditFile.objects.prefetch_related(
            "storage_mappings__storage_provider"
        ).get(pk=result["file_id"])
        serializer = self.get_serializer(audit_file)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """DELETE /api/v1/storage/files/{id}/"""
        audit_file = self.get_object()
        try:
            _service.delete_file(audit_file)
        except Exception as exc:
            logger.exception("Error deleting file: %s", exc)
            return Response(
                {"detail": f"Deletion failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="download-url")
    def download_url(self, request, pk=None):
        """
        GET /api/v1/storage/files/{id}/download-url/
        Returns {"url": "<presigned-or-relative-url>"}.
        """
        audit_file = self.get_object()
        expires_in = int(request.query_params.get("expires_in", 300))
        try:
            url = _service.generate_download_url(audit_file, expires_in=expires_in)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"url": url})

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        """POST /api/v1/storage/files/{id}/archive/"""
        audit_file = self.get_object()
        try:
            _service.move_to_archive(audit_file)
        except StorageConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception("Error archiving file: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        serializer = self.get_serializer(audit_file)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="storage-details")
    def storage_details(self, request, pk=None):
        """GET /api/v1/storage/files/{id}/storage-details/"""
        audit_file = self.get_object()
        return Response(_service.get_storage_details(audit_file))


class StorageActivityLogViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet
):
    """
    Read-only access to storage activity logs.
    Non-staff users see only their organisation's logs.
    """

    serializer_class = StorageActivityLogSerializer
    permission_classes = [IsOrgAdminOrSuperAdmin]

    def get_queryset(self):
        qs = StorageActivityLog.objects.select_related("user", "organization")
        if self.request.user.is_staff:
            return qs.all()
        user_org = getattr(self.request.user, "organization", None)
        if user_org:
            return qs.filter(organization=user_org)
        return qs.none()
