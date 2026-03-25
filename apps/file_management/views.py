"""
DRF ViewSets for the file management app.

FolderViewSet   — CRUD for Folder, plus a `tree` action.
AuditFileViewSet — CRUD for AuditFile (destroy = archive), plus:
                   archive, restore, download_url, move, versions.
"""
import logging

from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.file_management.exceptions import (
    FileMoveError,
    FileProcessingError,
    FileValidationError,
    FolderNotFoundError,
)
from apps.file_management.models import AuditFileProfile, FileVersion, Folder
from apps.file_management.permissions import CanManageFiles, CanManageFolders
from apps.file_management.selectors import (
    get_file_storage_stats,
    get_files_for_org,
    get_folder_tree,
)
from apps.file_management.serializers import (
    AuditFileDetailSerializer,
    AuditFileListSerializer,
    FileUploadSerializer,
    FileVersionSerializer,
    FileMoveSerializer,
    FolderCreateSerializer,
    FolderSerializer,
    FolderTreeSerializer,
)
from apps.file_management.services.file_service import FileManagementService
from apps.storage_management.exceptions import StorageUploadError, StorageValidationError
from apps.storage_management.models import AuditFile

logger = logging.getLogger(__name__)


class FolderViewSet(viewsets.ModelViewSet):
    """
    Manage folders within the authenticated user's organisation.

    list   GET    /folders/
    create POST   /folders/
    retrieve GET  /folders/{id}/
    update PUT    /folders/{id}/
    partial_update PATCH /folders/{id}/
    destroy DELETE /folders/{id}/
    tree   GET    /folders/tree/   — full nested tree
    """

    permission_classes = [CanManageFolders]
    serializer_class = FolderSerializer
    lookup_field = "id"

    def _get_organization(self):
        org = getattr(self.request.user, "organization", None)
        if org is None:
            raise PermissionDenied("Your account is not associated with an organisation.")
        return org

    def get_queryset(self):
        org = self._get_organization()
        return Folder.objects.filter(organization=org).select_related(
            "parent", "created_by", "organization"
        )

    def create(self, request, *args, **kwargs):
        serializer = FolderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org = self._get_organization()
        try:
            folder = FileManagementService().create_folder(
                organization=org,
                name=serializer.validated_data["name"],
                parent_id=serializer.validated_data.get("parent_id"),
                created_by=request.user,
            )
        except FolderNotFoundError as exc:
            raise NotFound(detail=str(exc))
        except FileValidationError as exc:
            raise ValidationError(detail=str(exc))

        return Response(
            FolderSerializer(folder).data,
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, *args, **kwargs):
        folder = self.get_object()
        try:
            FileManagementService().delete_folder(folder, deleted_by=request.user)
        except FolderNotFoundError as exc:
            raise ValidationError(detail=str(exc))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        """Return the complete nested folder tree for the organisation."""
        org = self._get_organization()
        tree_data = get_folder_tree(org)
        serializer = FolderTreeSerializer(tree_data, many=True)
        return Response(serializer.data)


class AuditFileViewSet(viewsets.ModelViewSet):
    """
    Manage files within the authenticated user's organisation.

    list     GET    /files/
    create   POST   /files/            — upload a new file
    retrieve GET    /files/{id}/
    destroy  DELETE /files/{id}/       — archives instead of hard-delete

    archive       POST   /files/{id}/archive/
    restore       POST   /files/{id}/restore/
    download_url  GET    /files/{id}/download-url/
    move          POST   /files/{id}/move/
    versions      GET    /files/{id}/versions/
    stats         GET    /files/stats/
    """

    permission_classes = [CanManageFiles]
    parser_classes = [MultiPartParser, FormParser]
    lookup_field = "id"

    def _get_organization(self):
        org = getattr(self.request.user, "organization", None)
        if org is None:
            raise PermissionDenied("Your account is not associated with an organisation.")
        return org

    def get_queryset(self):
        org = self._get_organization()
        filters = self._extract_filters()
        return get_files_for_org(org, filters)

    def _extract_filters(self) -> dict:
        params = self.request.query_params
        filters = {}

        if params.get("folder_id"):
            filters["folder_id"] = params["folder_id"]
        if params.get("file_type"):
            filters["file_type"] = params["file_type"]
        if params.get("status"):
            filters["status"] = params["status"]
        if params.get("search"):
            filters["search"] = params["search"]
        if params.get("date_from"):
            dt = parse_datetime(params["date_from"])
            if dt:
                filters["date_from"] = dt
        if params.get("date_to"):
            dt = parse_datetime(params["date_to"])
            if dt:
                filters["date_to"] = dt
        return filters

    def get_serializer_class(self):
        if self.action == "list":
            return AuditFileListSerializer
        return AuditFileDetailSerializer

    def create(self, request, *args, **kwargs):
        """Upload a new file. Expects multipart/form-data with a `file` field."""
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org = self._get_organization()
        file_obj = serializer.validated_data["file"]
        folder_id = serializer.validated_data.get("folder_id")
        purpose = serializer.validated_data.get("purpose", "uploads")

        try:
            result = FileManagementService().upload_file(
                file_obj=file_obj,
                organization=org,
                uploaded_by=request.user,
                folder_id=folder_id,
                purpose=purpose,
            )
        except (StorageValidationError, FileValidationError) as exc:
            raise ValidationError(detail=str(exc))
        except (StorageUploadError, FileProcessingError) as exc:
            logger.error("File upload failed: %s", exc, exc_info=True)
            return Response(
                {"detail": "File upload failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        audit_file = result["file"]
        return Response(
            AuditFileDetailSerializer(audit_file).data,
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, *args, **kwargs):
        """Archive the file instead of performing a hard delete."""
        audit_file = self.get_object()
        self.check_object_permissions(request, audit_file)

        FileManagementService().archive_file(audit_file, archived_by=request.user)
        return Response(
            {"detail": f"File '{audit_file.original_name}' has been archived."},
            status=status.HTTP_200_OK,
        )

    # ------------------------------------------------------------------
    # Extra actions
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, id=None):
        """Explicitly archive a file."""
        audit_file = self.get_object()
        self.check_object_permissions(request, audit_file)

        if audit_file.status == AuditFile.Status.ARCHIVED:
            return Response(
                {"detail": "File is already archived."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        FileManagementService().archive_file(audit_file, archived_by=request.user)
        return Response(
            AuditFileDetailSerializer(audit_file).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, id=None):
        """Restore a previously archived file."""
        audit_file = self.get_object()
        self.check_object_permissions(request, audit_file)

        if audit_file.status != AuditFile.Status.ARCHIVED:
            return Response(
                {"detail": "Only archived files can be restored."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        FileManagementService().restore_file(audit_file, restored_by=request.user)
        return Response(
            AuditFileDetailSerializer(audit_file).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="download-url")
    def download_url(self, request, id=None):
        """Return a time-limited pre-signed download URL for the file."""
        audit_file = self.get_object()
        self.check_object_permissions(request, audit_file)

        expires_in = int(request.query_params.get("expires_in", 300))
        expires_in = max(60, min(expires_in, 86400))  # clamp: 1 min – 24 hours

        try:
            url = FileManagementService().get_download_url(audit_file, expires_in=expires_in)
        except Exception as exc:
            logger.error("Failed to generate download URL for %s: %s", audit_file.id, exc)
            return Response(
                {"detail": "Could not generate a download URL for this file."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"url": url, "expires_in": expires_in})

    @action(detail=True, methods=["post"], url_path="move")
    def move(self, request, id=None):
        """Move the file to a different folder (or to root when target_folder_id is null)."""
        audit_file = self.get_object()
        self.check_object_permissions(request, audit_file)

        serializer = FileMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_folder_id = serializer.validated_data.get("target_folder_id")

        try:
            profile = FileManagementService().move_file(
                audit_file=audit_file,
                target_folder_id=target_folder_id,
                moved_by=request.user,
            )
        except FileMoveError as exc:
            raise ValidationError(detail=str(exc))

        return Response(
            AuditFileDetailSerializer(audit_file).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="versions")
    def versions(self, request, id=None):
        """Return all stored versions of the file, ordered newest-first."""
        audit_file = self.get_object()
        self.check_object_permissions(request, audit_file)

        versions_qs = (
            FileVersion.objects.filter(audit_file=audit_file)
            .select_related("storage_provider", "created_by")
            .order_by("-version_number")
        )
        return Response(FileVersionSerializer(versions_qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """Return aggregate storage statistics for the organisation."""
        org = self._get_organization()
        data = get_file_storage_stats(org)
        return Response(data)
