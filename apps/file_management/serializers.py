"""
DRF Serializers for the file management app.
"""
from rest_framework import serializers

from apps.file_management.models import AuditFileProfile, FileVersion, Folder
from apps.storage_management.models import AuditFile
from apps.storage_management.serializers import AuditFileSerializer


# ---------------------------------------------------------------------------
# Folder serializers
# ---------------------------------------------------------------------------

class FolderSerializer(serializers.ModelSerializer):
    """Full folder representation including computed fields."""

    full_path = serializers.SerializerMethodField(read_only=True)
    children_count = serializers.SerializerMethodField(read_only=True)
    files_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Folder
        fields = [
            "id",
            "organization",
            "parent",
            "name",
            "slug",
            "full_path",
            "children_count",
            "files_count",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "full_path", "children_count", "files_count", "created_at", "updated_at"]

    def get_full_path(self, obj: Folder) -> str:
        return obj.get_full_path()

    def get_children_count(self, obj: Folder) -> int:
        return obj.children.count()

    def get_files_count(self, obj: Folder) -> int:
        return obj.files.count()


class FolderTreeSerializer(serializers.Serializer):
    """Recursive representation of a folder node for the tree endpoint."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    children = serializers.SerializerMethodField()

    def get_children(self, obj: dict) -> list:
        # obj["children"] is already a list of dicts from get_folder_tree()
        return FolderTreeSerializer(obj.get("children", []), many=True).data


# ---------------------------------------------------------------------------
# Profile serializers
# ---------------------------------------------------------------------------

class AuditFileProfileSerializer(serializers.ModelSerializer):
    """Serializer for the AuditFileProfile companion model."""

    folder_id = serializers.UUIDField(source="folder.id", read_only=True, allow_null=True)
    folder_name = serializers.CharField(source="folder.name", read_only=True, allow_null=True)

    class Meta:
        model = AuditFileProfile
        fields = [
            "folder_id",
            "folder_name",
            "sanitized_name",
            "version_number",
            "is_archived",
            "metadata",
            "storage_path",
        ]
        read_only_fields = ["folder_id", "folder_name", "version_number", "storage_path"]


# ---------------------------------------------------------------------------
# AuditFile serializers
# ---------------------------------------------------------------------------

class AuditFileListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — avoids heavy nested data."""

    file_size_display = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    folder_id = serializers.SerializerMethodField(read_only=True)
    folder_name = serializers.SerializerMethodField(read_only=True)
    uploaded_by_email = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = AuditFile
        fields = [
            "id",
            "original_name",
            "file_type",
            "content_type",
            "file_size",
            "file_size_display",
            "status",
            "status_display",
            "checksum",
            "folder_id",
            "folder_name",
            "uploaded_by_email",
            "created_at",
        ]
        read_only_fields = fields

    def get_folder_id(self, obj: AuditFile):
        try:
            folder = obj.profile.folder
            return str(folder.id) if folder else None
        except AuditFileProfile.DoesNotExist:
            return None

    def get_folder_name(self, obj: AuditFile):
        try:
            folder = obj.profile.folder
            return folder.name if folder else None
        except AuditFileProfile.DoesNotExist:
            return None

    def get_uploaded_by_email(self, obj: AuditFile):
        return obj.uploaded_by.email if obj.uploaded_by else None


class AuditFileDetailSerializer(AuditFileSerializer):
    """
    Full detail serializer — extends Phase 1's AuditFileSerializer and
    injects the AuditFileProfile as a nested object.
    """

    profile = AuditFileProfileSerializer(read_only=True)

    class Meta(AuditFileSerializer.Meta):
        fields = AuditFileSerializer.Meta.fields + ["profile"]
        read_only_fields = AuditFileSerializer.Meta.read_only_fields + ["profile"]


# ---------------------------------------------------------------------------
# FileVersion serializer
# ---------------------------------------------------------------------------

class FileVersionSerializer(serializers.ModelSerializer):
    """Immutable record of a single stored version."""

    storage_provider_name = serializers.CharField(
        source="storage_provider.name", read_only=True
    )
    created_by_email = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = FileVersion
        fields = [
            "id",
            "audit_file",
            "version_number",
            "storage_provider",
            "storage_provider_name",
            "storage_path",
            "checksum",
            "file_size",
            "created_by",
            "created_by_email",
            "created_at",
        ]
        read_only_fields = fields

    def get_created_by_email(self, obj: FileVersion):
        return obj.created_by.email if obj.created_by else None


# ---------------------------------------------------------------------------
# Write / action serializers
# ---------------------------------------------------------------------------

class FileUploadSerializer(serializers.Serializer):
    """Input serializer for the file upload endpoint."""

    file = serializers.FileField(
        write_only=True,
        help_text="The file to upload.",
    )
    folder_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of the target folder. Omit to upload to the root.",
    )
    purpose = serializers.CharField(
        required=False,
        default="uploads",
        max_length=50,
        help_text="Storage purpose label (uploads, backup, archive, temp).",
    )

    def validate_purpose(self, value: str) -> str:
        allowed = {"uploads", "backup", "archive", "temp"}
        if value not in allowed:
            raise serializers.ValidationError(
                f"Invalid purpose '{value}'. Allowed values: {', '.join(sorted(allowed))}."
            )
        return value


class FileMoveSerializer(serializers.Serializer):
    """Input serializer for the file move endpoint."""

    target_folder_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of the destination folder. Pass null to move to root.",
    )


class FolderCreateSerializer(serializers.Serializer):
    """Input serializer for creating a folder."""

    name = serializers.CharField(
        max_length=255,
        help_text="Display name of the new folder.",
    )
    parent_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="UUID of the parent folder. Omit for a root-level folder.",
    )
