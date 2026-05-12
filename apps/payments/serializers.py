from decimal import Decimal
from rest_framework import serializers

from apps.payments.choices import PaymentPurpose
from apps.payments.models import PaymentTransaction


class CreatePaymentRequestSerializer(serializers.Serializer):
    """Input contract for POST /api/v1/payments/create/.

    Notably MISSING: ``provider`` — the active gateway is read from
    ``settings.PAYMENT_PROVIDER`` and clients cannot override it.
    """
    amount         = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    currency       = serializers.CharField(min_length=3, max_length=3, default="SAR")
    purpose        = serializers.ChoiceField(choices=PaymentPurpose.choices)
    reference_type = serializers.CharField(max_length=64, allow_blank=True, required=False, default="")
    reference_id   = serializers.CharField(max_length=64, allow_blank=True, required=False, default="")
    success_url    = serializers.URLField(allow_blank=True, required=False, default="")
    cancel_url     = serializers.URLField(allow_blank=True, required=False, default="")
    failure_url    = serializers.URLField(allow_blank=True, required=False, default="")
    idempotency_key = serializers.CharField(max_length=128, allow_blank=False, required=False)
    metadata       = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        attrs["currency"] = attrs["currency"].upper()
        return attrs


class PaymentTransactionSerializer(serializers.ModelSerializer):
    transaction_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model  = PaymentTransaction
        fields = [
            "transaction_id", "organization", "user", "provider", "purpose",
            "reference_type", "reference_id", "amount", "currency",
            "status", "provider_payment_id", "provider_reference",
            "checkout_url", "paid_at", "failed_reason", "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CreatePaymentResponseSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField()
    provider       = serializers.CharField()
    status         = serializers.CharField()
    checkout_url   = serializers.CharField(allow_blank=True)
    amount         = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency       = serializers.CharField()
