from rest_framework import serializers
from .models import ComplianceRule, ComplianceViolation

class ComplianceRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceRule
        fields = "__all__"
        read_only_fields = ["id", "created_at"]

class ComplianceViolationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = ComplianceViolation
        fields = "__all__"
