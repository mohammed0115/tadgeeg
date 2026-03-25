"""
File Management Models

Extends Phase 1 storage_management with folder hierarchy, file versioning,
and a profile model that attaches additional metadata to AuditFile without
modifying the Phase 1 schema.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.authentication.models import Organization
from apps.storage_management.models import AuditFile, StorageProvider


class Folder(models.Model):
    """
    Hierarchical folder structure for organising AuditFiles within an organisation.

    Supports arbitrary nesting via the self-referential `parent` FK.
    Each (organisation, parent, name) triple must be unique to avoid name
    collisions at the same level of the tree.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="folders",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_folders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("organization", "parent", "name")]
        verbose_name = "Folder"
        verbose_name_plural = "Folders"
        indexes = [
            models.Index(fields=["organization", "parent"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_full_path(self) -> str:
        """Return the slash-delimited full path from the root to this folder."""
        if self.parent_id:
            return f"{self.parent.get_full_path()}/{self.name}"
        return self.name

    def __str__(self):
        return self.get_full_path()


class FileVersion(models.Model):
    """
    Immutable record of one version of an AuditFile stored at a specific path
    on a specific StorageProvider.

    Version numbers are monotonically increasing per AuditFile.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit_file = models.ForeignKey(
        AuditFile,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    storage_provider = models.ForeignKey(
        StorageProvider,
        on_delete=models.PROTECT,
        related_name="file_versions",
    )
    storage_path = models.TextField()
    checksum = models.CharField(max_length=64)
    file_size = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_file_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version_number"]
        unique_together = [("audit_file", "version_number")]
        verbose_name = "File Version"
        verbose_name_plural = "File Versions"
        indexes = [
            models.Index(fields=["audit_file", "version_number"]),
        ]

    def __str__(self):
        return f"{self.audit_file.original_name} v{self.version_number}"


class AuditFileProfile(models.Model):
    """
    OneToOne extension of AuditFile with folder placement, versioning state,
    archive flag, and arbitrary JSON metadata.

    This model MUST NOT modify the Phase 1 AuditFile schema; it only adds
    a companion row in a separate table.
    """

    audit_file = models.OneToOneField(
        AuditFile,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    folder = models.ForeignKey(
        Folder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files",
    )
    sanitized_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Filesystem-safe version of the original filename.",
    )
    version_number = models.PositiveIntegerField(
        default=1,
        help_text="Current (latest) version number for this file.",
    )
    is_archived = models.BooleanField(default=False)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Arbitrary key-value metadata (tags, purpose, custom fields).",
    )
    storage_path = models.TextField(
        blank=True,
        help_text="Cached storage path for the latest version — avoids an extra join.",
    )
    storage_provider = models.ForeignKey(
        StorageProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profiled_files",
        help_text="Storage provider used for the latest version.",
    )

    class Meta:
        verbose_name = "Audit File Profile"
        verbose_name_plural = "Audit File Profiles"

    def __str__(self):
        return f"Profile: {self.audit_file.original_name}"
