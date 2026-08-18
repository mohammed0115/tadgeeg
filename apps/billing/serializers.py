from rest_framework import serializers

from apps.billing.choices import PlanCode
from apps.billing.models import OrganizationSubscription, Plan


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "code", "name_ar", "name_en",
            "description_ar", "description_en",
            "invoice_limit", "user_limit", "retention_months", "backup_frequency",
            "feature_tiers", "is_custom_quote",
            "price", "currency", "duration_days",
            "is_free", "is_trial",
        )
        read_only_fields = fields


class SelectPlanSerializer(serializers.Serializer):
    """Input contract for POST /billing/select-plan/."""
    plan_code = serializers.ChoiceField(choices=PlanCode.choices)


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    remaining_invoices = serializers.IntegerField(read_only=True)

    class Meta:
        model = OrganizationSubscription
        fields = (
            "id", "plan", "status",
            "starts_at", "ends_at",
            "invoice_limit", "user_limit", "retention_months_snapshot",
            "backup_frequency_snapshot", "feature_tiers_snapshot", "used_invoices",
            "reserved_invoices", "remaining_invoices",
        )
        read_only_fields = fields
