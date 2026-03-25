"""
FileManagementService

Orchestrates all high-level file management operations:
  - Uploading files and creating AuditFileProfile + FileVersion records
  - Folder creation and validation
  - Moving files between folders
  - Archiving and restoring files
  - Creating new file versions
  - Generating download URLs
  - Listing files with filters and pagination
  - Deleting empty folders

All storage I/O is delegated to StorageService (Phase 1). This service only
handles the file_management layer (profiles, folders, versions).
"""
import logging
import re
from typing import Optional

from django.db import transaction
from django.db.models import Max

from apps.file_management.exceptions import (
    FileMoveError,
    FileProcessingError,
    FileValidationError,
    FolderNotFoundError,
)
from apps.file_management.models import AuditFileProfile, FileVersion, Folder
from apps.file_management.selectors import get_files_for_org
from apps.storage_management.models import AuditFile, StorageProvider

logger = logging.getLogger(__name__)

# Regex for acceptable folder names: unicode letters/digits, spaces, hyphens, underscores, dots.
_FOLDER_NAME_RE = re.compile(r'^[\w\s\-\.]+$', re.UNICODE)


def _sanitize_filename(name: str) -> str:
    """Return a filesystem-safe version of a filename, preserving the extension."""
    # Replace any character that is not alphanumeric, dash, underscore, or dot with underscore.
    return re.sub(r'[^\w\-.]', '_', name)


class FileManagementService:
    """
    High-level service for the file_management app.

    All methods that mutate state are wrapped in atomic transactions.
    """

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    @transaction.atomic
    def upload_file(
        self,
        file_obj,
        organization,
        uploaded_by,
        folder_id=None,
        purpose: str = "uploads",
    ) -> dict:
        """
        Upload a file via StorageService and create the associated
        AuditFileProfile and FileVersion records.

        Parameters
        ----------
        file_obj : InMemoryUploadedFile | TemporaryUploadedFile
            The Django upload file object from request.FILES.
        organization : Organization
            The owning organisation.
        uploaded_by : User
            The user performing the upload.
        folder_id : UUID | None
            Optional target folder within the organisation.
        purpose : str
            Storage purpose label forwarded to StorageService (default: "uploads").

        Returns
        -------
        dict
            file     : AuditFile instance
            path     : str  — storage path of the first version
            version  : int  — always 1 for a fresh upload

        Raises
        ------
        FileValidationError
            If the folder_id is supplied but does not belong to the organisation.
        FileProcessingError
            If profile or version creation fails for any reason.
        StorageValidationError / StorageUploadError
            Re-raised from StorageService on backend failures.
        """
        from apps.storage_management.services.storage.service import StorageService

        # Validate target folder ownership
        if folder_id is not None:
            try:
                folder = Folder.objects.get(id=folder_id, organization=organization)
            except Folder.DoesNotExist:
                raise FileValidationError(
                    f"Folder '{folder_id}' does not exist within this organisation."
                )
        else:
            folder = None

        # Delegate actual storage to Phase 1 service
        result = StorageService().upload_file(
            file_obj,
            organization,
            uploaded_by,
            purpose=purpose,
        )

        # Retrieve the AuditFile created by StorageService
        try:
            audit_file = AuditFile.objects.select_related("organization").get(
                id=result["file_id"]
            )
        except AuditFile.DoesNotExist as exc:
            raise FileProcessingError(
                f"AuditFile '{result['file_id']}' not found after upload."
            ) from exc

        # Resolve StorageProvider by name (StorageService returns provider name, not ID)
        try:
            provider = StorageProvider.objects.get(name=result["provider"])
        except StorageProvider.DoesNotExist:
            provider = None

        sanitized = _sanitize_filename(audit_file.original_name)

        # Create AuditFileProfile
        profile = AuditFileProfile.objects.create(
            audit_file=audit_file,
            folder=folder,
            sanitized_name=sanitized,
            version_number=1,
            storage_path=result["path"],
            storage_provider=provider,
        )

        # Create the first FileVersion
        FileVersion.objects.create(
            audit_file=audit_file,
            version_number=1,
            storage_provider=provider,
            storage_path=result["path"],
            checksum=result["checksum"],
            file_size=result["size"],
            created_by=uploaded_by,
        )

        logger.info(
            "File uploaded: %s (org=%s, folder=%s, version=1)",
            audit_file.original_name,
            organization.id,
            folder_id,
        )

        return {
            "file": audit_file,
            "path": result["path"],
            "version": 1,
        }

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    @transaction.atomic
    def create_folder(
        self,
        organization,
        name: str,
        parent_id=None,
        created_by=None,
    ) -> Folder:
        """
        Create a new folder within an organisation.

        Parameters
        ----------
        organization : Organization
        name : str
            Folder display name. Must be non-empty and contain only
            alphanumeric characters, spaces, hyphens, underscores, or dots.
        parent_id : UUID | None
            Parent folder UUID. None means root-level folder.
        created_by : User | None

        Returns
        -------
        Folder

        Raises
        ------
        FileValidationError
            On empty name, invalid characters, or duplicate sibling name.
        FolderNotFoundError
            If parent_id is supplied but the parent does not exist in the org.
        """
        name = name.strip()
        if not name:
            raise FileValidationError("Folder name must not be empty.")

        if not _FOLDER_NAME_RE.match(name):
            raise FileValidationError(
                "Folder name contains invalid characters. "
                "Allowed: letters, digits, spaces, hyphens, underscores, dots."
            )

        parent = None
        if parent_id is not None:
            try:
                parent = Folder.objects.get(id=parent_id, organization=organization)
            except Folder.DoesNotExist:
                raise FolderNotFoundError(
                    f"Parent folder '{parent_id}' does not exist within this organisation."
                )

        # Enforce uniqueness at the same level
        duplicate = Folder.objects.filter(
            organization=organization, parent=parent, name__iexact=name
        ).exists()
        if duplicate:
            raise FileValidationError(
                f"A folder named '{name}' already exists at this level."
            )

        folder = Folder.objects.create(
            organization=organization,
            parent=parent,
            name=name,
            created_by=created_by,
        )
        logger.info("Folder created: %s (org=%s, parent=%s)", name, organization.id, parent_id)
        return folder

    @transaction.atomic
    def delete_folder(self, folder: Folder, deleted_by=None) -> None:
        """
        Delete a folder only if it contains no files.

        Parameters
        ----------
        folder : Folder
        deleted_by : User | None

        Raises
        ------
        FolderNotFoundError
            If the folder still contains files (guards against orphan profiles).
        """
        file_count = AuditFileProfile.objects.filter(folder=folder).count()
        if file_count > 0:
            raise FolderNotFoundError(
                f"Cannot delete folder '{folder.name}': it still contains {file_count} file(s). "
                "Move or archive all files before deleting the folder."
            )

        folder_name = folder.name
        folder.delete()
        logger.info(
            "Folder deleted: %s (deleted_by=%s)",
            folder_name,
            getattr(deleted_by, "id", None),
        )

    # ------------------------------------------------------------------
    # Move
    # ------------------------------------------------------------------

    @transaction.atomic
    def move_file(self, audit_file: AuditFile, target_folder_id, moved_by=None) -> AuditFileProfile:
        """
        Move a file to a different folder (or to the root by passing None).

        Parameters
        ----------
        audit_file : AuditFile
        target_folder_id : UUID | None
            Target folder UUID, or None to move to the root.
        moved_by : User | None

        Returns
        -------
        AuditFileProfile

        Raises
        ------
        FileMoveError
            If the target folder is not found within the organisation.
        """
        if target_folder_id is not None:
            try:
                target_folder = Folder.objects.get(
                    id=target_folder_id, organization=audit_file.organization
                )
            except Folder.DoesNotExist:
                raise FileMoveError(
                    f"Target folder '{target_folder_id}' does not exist within this organisation."
                )
        else:
            target_folder = None

        profile, _ = AuditFileProfile.objects.get_or_create(
            audit_file=audit_file,
            defaults={"sanitized_name": _sanitize_filename(audit_file.original_name)},
        )
        profile.folder = target_folder
        profile.save(update_fields=["folder"])

        logger.info(
            "File moved: %s → folder=%s (moved_by=%s)",
            audit_file.original_name,
            target_folder_id,
            getattr(moved_by, "id", None),
        )
        return profile

    # ------------------------------------------------------------------
    # Archive / Restore
    # ------------------------------------------------------------------

    @transaction.atomic
    def archive_file(self, audit_file: AuditFile, archived_by=None) -> AuditFile:
        """
        Mark a file as archived.

        Sets AuditFile.status = "archived" and AuditFileProfile.is_archived = True.

        Returns
        -------
        AuditFile  (refreshed instance)
        """
        audit_file.status = AuditFile.Status.ARCHIVED
        audit_file.save(update_fields=["status", "updated_at"])

        profile, _ = AuditFileProfile.objects.get_or_create(
            audit_file=audit_file,
            defaults={"sanitized_name": _sanitize_filename(audit_file.original_name)},
        )
        profile.is_archived = True
        profile.save(update_fields=["is_archived"])

        logger.info(
            "File archived: %s (archived_by=%s)",
            audit_file.original_name,
            getattr(archived_by, "id", None),
        )
        return audit_file

    @transaction.atomic
    def restore_file(self, audit_file: AuditFile, restored_by=None) -> AuditFile:
        """
        Restore a previously archived file.

        Sets AuditFile.status = "stored" and AuditFileProfile.is_archived = False.

        Returns
        -------
        AuditFile  (refreshed instance)
        """
        audit_file.status = AuditFile.Status.STORED
        audit_file.save(update_fields=["status", "updated_at"])

        try:
            profile = audit_file.profile
            profile.is_archived = False
            profile.save(update_fields=["is_archived"])
        except AuditFileProfile.DoesNotExist:
            AuditFileProfile.objects.create(
                audit_file=audit_file,
                sanitized_name=_sanitize_filename(audit_file.original_name),
                is_archived=False,
            )

        logger.info(
            "File restored: %s (restored_by=%s)",
            audit_file.original_name,
            getattr(restored_by, "id", None),
        )
        return audit_file

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    @transaction.atomic
    def create_new_version(
        self,
        audit_file: AuditFile,
        file_obj,
        uploaded_by,
        purpose: str = "uploads",
    ) -> FileVersion:
        """
        Upload a replacement file and register it as a new FileVersion.

        The AuditFileProfile is updated with the new version number and path.

        Parameters
        ----------
        audit_file : AuditFile
            The existing file to version.
        file_obj : file-like
            New file content.
        uploaded_by : User
        purpose : str

        Returns
        -------
        FileVersion  — the newly created version record.
        """
        from apps.storage_management.services.storage.service import StorageService

        profile, _ = AuditFileProfile.objects.get_or_create(
            audit_file=audit_file,
            defaults={"sanitized_name": _sanitize_filename(audit_file.original_name)},
        )

        # Determine next version number
        max_version = (
            FileVersion.objects.filter(audit_file=audit_file)
            .aggregate(max_v=Max("version_number"))["max_v"]
        ) or 0
        next_version = max_version + 1

        # Upload the new file content
        result = StorageService().upload_file(
            file_obj,
            audit_file.organization,
            uploaded_by,
            purpose=purpose,
        )

        # Resolve provider
        try:
            provider = StorageProvider.objects.get(name=result["provider"])
        except StorageProvider.DoesNotExist:
            provider = None

        # Create the new FileVersion record
        file_version = FileVersion.objects.create(
            audit_file=audit_file,
            version_number=next_version,
            storage_provider=provider,
            storage_path=result["path"],
            checksum=result["checksum"],
            file_size=result["size"],
            created_by=uploaded_by,
        )

        # Update profile to reflect the latest version
        profile.version_number = next_version
        profile.storage_path = result["path"]
        profile.storage_provider = provider
        profile.save(update_fields=["version_number", "storage_path", "storage_provider"])

        logger.info(
            "New version created: %s v%s (org=%s)",
            audit_file.original_name,
            next_version,
            audit_file.organization_id,
        )
        return file_version

    # ------------------------------------------------------------------
    # Download URL
    # ------------------------------------------------------------------

    def get_download_url(self, audit_file: AuditFile, expires_in: int = 300) -> str:
        """
        Generate a time-limited download URL for the latest stored version.

        Parameters
        ----------
        audit_file : AuditFile
        expires_in : int
            Seconds until the URL expires (default 300).

        Returns
        -------
        str — pre-signed or direct download URL.

        Raises
        ------
        StorageNotFoundError
            If no storage mapping exists for this file.
        """
        from apps.storage_management.services.storage.service import StorageService

        return StorageService().generate_download_url(audit_file, expires_in=expires_in)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_files(
        self,
        organization,
        filters: Optional[dict] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """
        Return a paginated, filtered list of AuditFile records for the organisation.

        Parameters
        ----------
        organization : Organization
        filters : dict | None
            Forwarded directly to `get_files_for_org`.
        page : int
            1-based page number.
        page_size : int
            Number of results per page.

        Returns
        -------
        dict
            results   : list of AuditFile instances for the current page
            count     : total number of matching files
            page      : current page number
            page_size : requested page size
        """
        page = max(1, page)
        page_size = max(1, min(page_size, 200))  # hard cap at 200

        qs = get_files_for_org(organization, filters)
        total = qs.count()

        offset = (page - 1) * page_size
        results = list(qs[offset : offset + page_size])

        return {
            "results": results,
            "count": total,
            "page": page,
            "page_size": page_size,
        }
