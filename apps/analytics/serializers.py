from rest_framework import serializers

from .models import NLQueryHistory


class NLQueryHistorySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = NLQueryHistory
        fields = [
            "id",
            "organization",
            "user",
            "user_name",
            "query",
            "interpretation",
            "filters",
            "excludes",
            "order_by",
            "result_count",
            "created_at",
        ]
        read_only_fields = fields
