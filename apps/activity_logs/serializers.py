from rest_framework import serializers

from apps.activity_logs.models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    """Full read-only serializer for ActivityLog.

    ``user_email`` and ``organization_name`` are derived read-only fields
    that avoid an extra round-trip to the User / Organization tables when
    select_related is used in the view queryset.
    """

    user_email = serializers.SerializerMethodField()
    organization_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "organization",
            "organization_name",
            "user",
            "user_email",
            "action",
            "entity_type",
            "entity_id",
            "description",
            "metadata",
            "ip_address",
            "created_at",
        ]
        read_only_fields = fields

    def get_user_email(self, obj: ActivityLog) -> str | None:
        return obj.user.email if obj.user_id else None

    def get_organization_name(self, obj: ActivityLog) -> str | None:
        return obj.organization.name if obj.organization_id else None
