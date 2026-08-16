"""
StorageService — high-level file operations orchestrating validation,
backend I/O, model persistence, and activity logging.
"""
import hashlib
import logging
import os
import subprocess
from typing import IO, Optional

from apps.storage_management.exceptions import (
    StorageNotFoundError,
    StorageUploadError,
    StorageValidationError,
)
from apps.storage_management.models import (
    AuditFile,
    FileStorageMapping,
    StorageActivityLog,
    StoragePolicy,
)
from apps.storage_management.utils.path_builder import build_storage_path
from .resolver import StorageResolver

logger = logging.getLogger(__name__)

_resolver = StorageResolver()


class StorageService:
    """
    Orchestrates all file storage operations for the platform.

    Flow for upload:
        policy validation → checksum → path generation → backend save →
        AuditFile + FileStorageMapping creation → activity log
    """

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_file(
        self,
        file_obj: IO,
        organization,
        uploaded_by,
        purpose: str = "upload",
        original_name: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> dict:
        """
        Upload a file for an organisation.

        Args:
            file_obj: File-like object (must support .read() and .seek()).
            organization: Organisation model instance.
            uploaded_by: User model instance.
            purpose: Storage purpose ('upload', 'backup', 'archive', 'temp').
            original_name: Override the filename (e.g. from request.FILES).
            content_type: MIME type override.

        Returns:
            dict with keys: file_id, path, provider, size, checksum.

        Raises:
            StorageValidationError: if the file fails policy checks.
            StorageUploadError: if the backend write fails.
        """
        # Resolve original filename
        name = original_name or getattr(file_obj, "name", "unnamed_file")
        mime = content_type or getattr(file_obj, "content_type", "application/octet-stream")
        ext = os.path.splitext(name)[1].lower().lstrip(".")

        # 1. Get or create StoragePolicy for org (use defaults when absent)
        policy = self._get_policy(organization)

        # 2. Validate
        self.validate_file(file_obj, policy, name=name, mime=mime)

        # 3. Compute checksum (MD5, cheap for file integrity)
        checksum = self._compute_checksum(file_obj)

        # 4. Build storage path
        path = build_storage_path(str(organization.id), name, purpose=purpose)

        # 5. Get backend
        backend = _resolver.get_backend(organization, purpose=purpose)
        provider = _resolver.get_provider(organization, purpose=purpose)

        # 6. Measure file size
        file_obj.seek(0, 2)  # seek to end
        file_size = file_obj.tell()
        file_obj.seek(0)  # rewind

        # 7. Create AuditFile (status = PROCESSING)
        audit_file = AuditFile.objects.create(
            organization=organization,
            uploaded_by=uploaded_by,
            original_name=name,
            file_type=ext,
            content_type=mime,
            file_size=file_size,
            status=AuditFile.Status.PROCESSING,
            checksum=checksum,
        )

        # 8. Save to backend
        try:
            stored_path = backend.save(
                file_obj, path, metadata={"content_type": mime}
            )
        except Exception as exc:
            audit_file.status = AuditFile.Status.FAILED
            audit_file.save(update_fields=["status", "updated_at"])
            self._log(
                user=uploaded_by,
                organization=organization,
                action=StorageActivityLog.Action.FILE_UPLOADED,
                entity_type="AuditFile",
                entity_id=str(audit_file.id),
                metadata={"name": name, "error": str(exc)},
                success=False,
                error_message=str(exc),
            )
            raise StorageUploadError(f"Backend save failed: {exc}") from exc

        # 9. Create FileStorageMapping
        FileStorageMapping.objects.create(
            file=audit_file,
            storage_provider=provider,
            storage_path=stored_path,
            storage_bucket=getattr(backend, "bucket", ""),
            version_number=1,
            checksum=checksum,
            file_size=file_size,
            content_type=mime,
        )

        # 10. Update AuditFile to STORED
        audit_file.status = AuditFile.Status.STORED
        audit_file.save(update_fields=["status", "updated_at"])

        # 11. Log success
        self._log(
            user=uploaded_by,
            organization=organization,
            action=StorageActivityLog.Action.FILE_UPLOADED,
            entity_type="AuditFile",
            entity_id=str(audit_file.id),
            metadata={
                "name": name,
                "path": stored_path,
                "provider": provider.name,
                "size": file_size,
                "checksum": checksum,
            },
        )

        return {
            "file_id": str(audit_file.id),
            "path": stored_path,
            "provider": provider.name,
            "size": file_size,
            "checksum": checksum,
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_file(
        self,
        file_obj: IO,
        policy: StoragePolicy,
        name: str = "",
        mime: str = "",
    ) -> None:
        """
        Validate a file against the organisation's StoragePolicy.

        Args:
            file_obj: File-like object (must support seek/tell).
            policy: The StoragePolicy instance.
            name: Filename string.
            mime: MIME type string.

        Raises:
            StorageValidationError: with a descriptive message if validation fails.
        """
        # Size check
        try:
            file_obj.seek(0, 2)
            size_bytes = file_obj.tell()
            file_obj.seek(0)
        except (AttributeError, OSError):
            size_bytes = 0

        max_bytes = policy.max_file_size_mb * 1024 * 1024
        if size_bytes > max_bytes:
            raise StorageValidationError(
                f"File size {size_bytes / (1024 * 1024):.1f} MB exceeds the maximum "
                f"allowed size of {policy.max_file_size_mb} MB."
            )

        # Extension check
        if policy.allowed_extensions:
            ext = os.path.splitext(name)[1].lower().lstrip(".")
            if ext and ext not in [e.lower().lstrip(".") for e in policy.allowed_extensions]:
                raise StorageValidationError(
                    f"File extension '.{ext}' is not permitted. "
                    f"Allowed: {', '.join(policy.allowed_extensions)}."
                )

        # MIME type check
        if policy.allowed_mime_types and mime:
            if mime not in policy.allowed_mime_types:
                raise StorageValidationError(
                    f"MIME type '{mime}' is not permitted. "
                    f"Allowed: {', '.join(policy.allowed_mime_types)}."
                )

        if policy.antivirus_scan_enabled:
            self._scan_antivirus(file_obj)

    def _scan_antivirus(self, file_obj: IO) -> None:
        """Fail closed when a policy requires antivirus scanning."""
        try:
            file_obj.seek(0)
            scan = subprocess.run(
                ["clamscan", "--no-summary", "-"],
                input=file_obj.read(), capture_output=True, check=False, timeout=60,
            )
            file_obj.seek(0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StorageValidationError("Antivirus scan is required but unavailable.") from exc
        if scan.returncode == 0:
            return
        if scan.returncode == 1:
            raise StorageValidationError("Uploaded file failed antivirus scanning.")
        raise StorageValidationError("Antivirus scan could not complete safely.")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_file(self, audit_file: AuditFile) -> None:
        """
        Delete all storage mappings for an AuditFile and update its status.

        Args:
            audit_file: The AuditFile model instance to delete.
        """
        mappings = audit_file.storage_mappings.select_related("storage_provider").all()
        for mapping in mappings:
            try:
                backend = _resolver._build_backend(mapping.storage_provider)
                backend.delete(mapping.storage_path)
            except Exception as exc:
                logger.warning(
                    "Failed to delete file from backend '%s': %s",
                    mapping.storage_provider.name,
                    exc,
                )

        audit_file.status = AuditFile.Status.FAILED
        audit_file.save(update_fields=["status", "updated_at"])

        self._log(
            user=None,
            organization=audit_file.organization,
            action=StorageActivityLog.Action.FILE_DELETED,
            entity_type="AuditFile",
            entity_id=str(audit_file.id),
            metadata={"name": audit_file.original_name},
        )

    # ------------------------------------------------------------------
    # Download URL
    # ------------------------------------------------------------------

    def generate_download_url(self, audit_file: AuditFile, expires_in: int = 300) -> str:
        """
        Generate a download URL for the latest version of a stored file.

        Args:
            audit_file: The AuditFile model instance.
            expires_in: URL validity in seconds.

        Returns:
            A URL string.

        Raises:
            StorageNotFoundError: if no storage mapping exists.
        """
        mapping = (
            audit_file.storage_mappings
            .select_related("storage_provider")
            .order_by("-version_number")
            .first()
        )
        if not mapping:
            raise StorageNotFoundError(
                f"No storage mapping found for file '{audit_file.original_name}'."
            )
        backend = _resolver._build_backend(mapping.storage_provider)
        return backend.generate_download_url(mapping.storage_path, expires_in=expires_in)

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def move_to_archive(self, audit_file: AuditFile) -> None:
        """
        Copy a file to the archive storage and update the mapping.

        Args:
            audit_file: The AuditFile model instance to archive.
        """
        current_mapping = (
            audit_file.storage_mappings
            .select_related("storage_provider")
            .order_by("-version_number")
            .first()
        )
        if not current_mapping:
            raise StorageNotFoundError(
                f"No storage mapping found for file '{audit_file.original_name}'."
            )

        source_backend = _resolver._build_backend(current_mapping.storage_provider)
        archive_backend = _resolver.get_backend(audit_file.organization, purpose="archive")
        archive_provider = _resolver.get_provider(audit_file.organization, purpose="archive")

        archive_path = build_storage_path(
            str(audit_file.organization_id),
            audit_file.original_name,
            purpose="archive",
        )

        file_obj = source_backend.open(current_mapping.storage_path)
        try:
            archive_backend.save(
                file_obj,
                archive_path,
                metadata={"content_type": audit_file.content_type},
            )
        finally:
            if hasattr(file_obj, "close"):
                file_obj.close()

        next_version = current_mapping.version_number + 1
        FileStorageMapping.objects.create(
            file=audit_file,
            storage_provider=archive_provider,
            storage_path=archive_path,
            storage_bucket=getattr(archive_backend, "bucket", ""),
            version_number=next_version,
            checksum=audit_file.checksum,
            file_size=audit_file.file_size,
            content_type=audit_file.content_type,
        )

        audit_file.status = AuditFile.Status.ARCHIVED
        audit_file.save(update_fields=["status", "updated_at"])

        self._log(
            user=None,
            organization=audit_file.organization,
            action=StorageActivityLog.Action.FILE_MOVED,
            entity_type="AuditFile",
            entity_id=str(audit_file.id),
            metadata={
                "name": audit_file.original_name,
                "archive_path": archive_path,
                "archive_provider": archive_provider.name,
            },
        )

    # ------------------------------------------------------------------
    # Details
    # ------------------------------------------------------------------

    def get_storage_details(self, audit_file: AuditFile) -> dict:
        """
        Return a comprehensive dict describing where and how a file is stored.

        Args:
            audit_file: The AuditFile model instance.

        Returns:
            dict with file metadata and all storage mapping details.
        """
        mappings = list(
            audit_file.storage_mappings
            .select_related("storage_provider")
            .order_by("-version_number")
        )
        return {
            "file_id": str(audit_file.id),
            "original_name": audit_file.original_name,
            "file_type": audit_file.file_type,
            "content_type": audit_file.content_type,
            "file_size": audit_file.file_size,
            "file_size_display": audit_file.file_size_display,
            "status": audit_file.status,
            "checksum": audit_file.checksum,
            "organization": str(audit_file.organization_id),
            "uploaded_by": str(audit_file.uploaded_by_id) if audit_file.uploaded_by_id else None,
            "created_at": audit_file.created_at.isoformat(),
            "storage_locations": [
                {
                    "provider": m.storage_provider.name,
                    "provider_type": m.storage_provider.provider_type,
                    "path": m.storage_path,
                    "bucket": m.storage_bucket,
                    "version": m.version_number,
                    "checksum": m.checksum,
                    "size": m.file_size,
                    "stored_at": m.created_at.isoformat(),
                }
                for m in mappings
            ],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_policy(self, organization) -> StoragePolicy:
        """Return the StoragePolicy for the org, or a transient default."""
        try:
            return StoragePolicy.objects.get(organization=organization)
        except StoragePolicy.DoesNotExist:
            # Return an unsaved default policy so upload can proceed
            return StoragePolicy(
                organization=organization,
                max_file_size_mb=50,
                allowed_extensions=[],
                allowed_mime_types=[],
                retention_days=365,
            )

    def _compute_checksum(self, file_obj: IO) -> str:
        """Compute MD5 checksum of the file content."""
        md5 = hashlib.md5()
        file_obj.seek(0)
        for chunk in iter(lambda: file_obj.read(8192), b""):
            md5.update(chunk)
        file_obj.seek(0)
        return md5.hexdigest()

    def _log(
        self,
        user,
        organization,
        action: str,
        entity_type: str = "",
        entity_id: str = "",
        metadata: Optional[dict] = None,
        success: bool = True,
        error_message: str = "",
    ) -> None:
        """Create a StorageActivityLog entry."""
        try:
            StorageActivityLog.objects.create(
                user=user,
                organization=organization,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata=metadata or {},
                success=success,
                error_message=error_message,
            )
        except Exception as exc:
            logger.warning("Failed to write StorageActivityLog: %s", exc)
