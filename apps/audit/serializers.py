from rest_framework import serializers
from .models import AuditCase, CaseComment

class CaseCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    class Meta:
        model = CaseComment
        fields = ["id", "case", "author", "author_name", "text", "is_internal", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

class AuditCaseSerializer(serializers.ModelSerializer):
    comments = CaseCommentSerializer(many=True, read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = AuditCase
        fields = "__all__"
        read_only_fields = ["id", "case_number", "organization", "created_at", "updated_at"]
