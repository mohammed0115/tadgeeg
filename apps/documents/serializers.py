from rest_framework import serializers
from .models import Document, ExtractedData, DocumentPageResult

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = "__all__"
        read_only_fields = ["id", "organization", "uploaded_by", "created_at", "updated_at"]

class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    document_type = serializers.ChoiceField(choices=Document.DocumentType.choices, default="other")
    notes = serializers.CharField(required=False, allow_blank=True)

class ExtractedDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractedData
        fields = "__all__"
