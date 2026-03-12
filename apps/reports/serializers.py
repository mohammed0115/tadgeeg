from rest_framework import serializers
from .models import Report

class ReportSerializer(serializers.ModelSerializer):
    generated_by_name = serializers.CharField(source="generated_by.full_name", read_only=True)
    class Meta:
        model = Report
        fields = ["id", "title", "report_type", "language", "period_from", "period_to",
                  "generated_by", "generated_by_name", "created_at"]
        read_only_fields = ["id", "created_at"]
