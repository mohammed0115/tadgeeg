"""
Storage Management Models
Handles storage providers, configurations, policies, and file tracking.
"""
import uuid

from django.conf import settings
from django.db import models

from apps.authentication.models import Organization


class StorageProvider(models.Model):
    class ProviderType(models.TextChoices):
        LOCAL = "local", "Local Storage"
        S3 = "s3", "Amazon S3"
        MINIO = "minio", "MinIO"
        AZURE = "azure", "Azure Blob"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    provider_type = models.CharField(max_length=20, choices=ProviderType.choices)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "name"]
        verbose_name = "Storage Provider"
        verbose_name_plural = "Storage Providers"

    def save(self, *args, **kwargs):
        # Only one provider can be default at a time
        if self.is_default:
            StorageProvider.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"


class StorageConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.OneToOneField(
        StorageProvider, on_delete=models.CASCADE, related_name="config"
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="storage_configs",
        help_text="Null = global config",
    )
    bucket_name = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=50, blank=True)
    endpoint_url = models.URLField(blank=True)
    base_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="For LOCAL: filesystem path. For S3/MinIO: key prefix",
    )
    access_key_encrypted = models.TextField(blank=True)
    secret_key_encrypted = models.TextField(blank=True)
    use_ssl = models.BooleanField(default=True)
    extra_settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Storage Config"
        verbose_name_plural = "Storage Configs"

    def __str__(self):
        scope = self.organization.name if self.organization else "Global"
        return f"{self.provider.name} config [{scope}]"


class OrganizationStoragePolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="storage_policy"
    )
    primary_storage = models.ForeignKey(
        StorageProvider,
        on_delete=models.PROTECT,
        related_name="primary_for",
    )
    backup_storage = models.ForeignKey(
        StorageProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backup_for",
    )
    archive_storage = models.ForeignKey(
        StorageProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archive_for",
    )
    temp_storage = models.ForeignKey(
        StorageProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="temp_for",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organization Storage Policy"
        verbose_name_plural = "Organization Storage Policies"

    def __str__(self):
        return f"{self.organization.name} storage policy"


class StoragePolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="file_policy"
    )
    max_file_size_mb = models.PositiveIntegerField(default=50)
    allowed_extensions = models.JSONField(default=list)
    allowed_mime_types = models.JSONField(default=list)
    retention_days = models.PositiveIntegerField(default=365)
    require_signed_urls = models.BooleanField(default=False)
    require_encryption = models.BooleanField(default=False)
    antivirus_scan_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Storage Policy"
        verbose_name_plural = "Storage Policies"

    def __str__(self):
        return f"{self.organization.name} file policy"


class AuditFile(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PROCESSING = "processing", "Processing"
        STORED = "stored", "Stored"
        FAILED = "failed", "Failed"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="audit_files"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_audit_files",
    )
    original_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    checksum = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit File"
        verbose_name_plural = "Audit Files"
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["checksum"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return self.original_name

    @property
    def file_size_display(self):
        size = self.file_size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class FileStorageMapping(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.ForeignKey(
        AuditFile, on_delete=models.CASCADE, related_name="storage_mappings"
    )
    storage_provider = models.ForeignKey(StorageProvider, on_delete=models.PROTECT)
    storage_path = models.TextField()
    storage_bucket = models.CharField(max_length=255, blank=True)
    version_number = models.PositiveIntegerField(default=1)
    checksum = models.CharField(max_length=64, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version_number"]
        verbose_name = "File Storage Mapping"
        verbose_name_plural = "File Storage Mappings"

    def __str__(self):
        return f"{self.file.original_name} → {self.storage_provider.name}"


class StorageActivityLog(models.Model):
    class Action(models.TextChoices):
        PROVIDER_CREATED = "provider_created", "Provider Created"
        PROVIDER_UPDATED = "provider_updated", "Provider Updated"
        PROVIDER_DELETED = "provider_deleted", "Provider Deleted"
        CONFIG_UPDATED = "config_updated", "Config Updated"
        CONNECTION_TESTED = "connection_tested", "Connection Tested"
        FILE_UPLOADED = "file_uploaded", "File Uploaded"
        FILE_DELETED = "file_deleted", "File Deleted"
        POLICY_UPDATED = "policy_updated", "Policy Updated"
        FILE_MOVED = "file_moved", "File Moved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Storage Activity Log"
        verbose_name_plural = "Storage Activity Logs"
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["action"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.user} at {self.created_at:%Y-%m-%d %H:%M}"
