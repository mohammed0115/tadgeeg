"""
DRF Serializers for storage management models.
"""
from rest_framework import serializers

from apps.storage_management.models import (
    AuditFile,
    FileStorageMapping,
    OrganizationStoragePolicy,
    StorageActivityLog,
    StorageConfig,
    StoragePolicy,
    StorageProvider,
)
from apps.storage_management.utils.encryption import encrypt_value, mask_value


class StorageProviderSerializer(serializers.ModelSerializer):
    provider_type_display = serializers.CharField(
        source="get_provider_type_display", read_only=True
    )

    class Meta:
        model = StorageProvider
        fields = [
            "id",
            "name",
            "provider_type",
            "provider_type_display",
            "description",
            "is_active",
            "is_default",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class StorageConfigSerializer(serializers.ModelSerializer):
    # Write-only plain-text inputs that get encrypted before saving
    access_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True, default=""
    )
    secret_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True, default=""
    )
    # Read-only masked view so the frontend can show "has a key set"
    access_key_masked = serializers.SerializerMethodField()
    secret_key_masked = serializers.SerializerMethodField()

    class Meta:
        model = StorageConfig
        fields = [
            "id",
            "provider",
            "organization",
            "bucket_name",
            "region",
            "endpoint_url",
            "base_path",
            "access_key",
            "secret_key",
            "access_key_masked",
            "secret_key_masked",
            "use_ssl",
            "extra_settings",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "access_key_masked", "secret_key_masked"]
        # The encrypted fields are never surfaced in reads
        extra_kwargs = {
            "access_key_encrypted": {"write_only": True},
            "secret_key_encrypted": {"write_only": True},
        }

    def get_access_key_masked(self, obj):
        return mask_value(obj.access_key_encrypted) if obj.access_key_encrypted else ""

    def get_secret_key_masked(self, obj):
        return mask_value(obj.secret_key_encrypted) if obj.secret_key_encrypted else ""

    def validate(self, attrs):
        # Pop the plain-text keys before they reach the model
        access_key = attrs.pop("access_key", "")
        secret_key = attrs.pop("secret_key", "")
        if access_key:
            attrs["access_key_encrypted"] = encrypt_value(access_key)
        if secret_key:
            attrs["secret_key_encrypted"] = encrypt_value(secret_key)
        return attrs


class OrganizationStoragePolicySerializer(serializers.ModelSerializer):
    primary_storage_name = serializers.CharField(
        source="primary_storage.name", read_only=True
    )
    backup_storage_name = serializers.SerializerMethodField()
    archive_storage_name = serializers.SerializerMethodField()
    temp_storage_name = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationStoragePolicy
        fields = [
            "id",
            "organization",
            "primary_storage",
            "primary_storage_name",
            "backup_storage",
            "backup_storage_name",
            "archive_storage",
            "archive_storage_name",
            "temp_storage",
            "temp_storage_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_backup_storage_name(self, obj):
        return obj.backup_storage.name if obj.backup_storage else None

    def get_archive_storage_name(self, obj):
        return obj.archive_storage.name if obj.archive_storage else None

    def get_temp_storage_name(self, obj):
        return obj.temp_storage.name if obj.temp_storage else None


class StoragePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = StoragePolicy
        fields = [
            "id",
            "organization",
            "max_file_size_mb",
            "allowed_extensions",
            "allowed_mime_types",
            "retention_days",
            "require_signed_urls",
            "require_encryption",
            "antivirus_scan_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class FileStorageMappingSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(
        source="storage_provider.name", read_only=True
    )
    provider_type = serializers.CharField(
        source="storage_provider.provider_type", read_only=True
    )

    class Meta:
        model = FileStorageMapping
        fields = [
            "id",
            "storage_provider",
            "provider_name",
            "provider_type",
            "storage_path",
            "storage_bucket",
            "version_number",
            "checksum",
            "file_size",
            "content_type",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class AuditFileSerializer(serializers.ModelSerializer):
    storage_mappings = FileStorageMappingSerializer(many=True, read_only=True)
    uploaded_by_email = serializers.SerializerMethodField()
    file_size_display = serializers.CharField(read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AuditFile
        fields = [
            "id",
            "organization",
            "organization_name",
            "uploaded_by",
            "uploaded_by_email",
            "original_name",
            "file_type",
            "content_type",
            "file_size",
            "file_size_display",
            "status",
            "status_display",
            "checksum",
            "storage_mappings",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "file_size_display",
            "storage_mappings",
            "organization_name",
            "uploaded_by_email",
            "status_display",
        ]

    def get_uploaded_by_email(self, obj):
        return obj.uploaded_by.email if obj.uploaded_by else None


class StorageActivityLogSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField()
    organization_name = serializers.SerializerMethodField()
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = StorageActivityLog
        fields = [
            "id",
            "user",
            "user_email",
            "organization",
            "organization_name",
            "action",
            "action_display",
            "entity_type",
            "entity_id",
            "metadata",
            "success",
            "error_message",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_user_email(self, obj):
        return obj.user.email if obj.user else None

    def get_organization_name(self, obj):
        return obj.organization.name if obj.organization else None
