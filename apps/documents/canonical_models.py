"""
Canonical Schema Layer — Document Field Definitions & Mapping.

These models define the shared vocabulary for all document types.
No existing models are removed. This is an additive layer.
"""
from __future__ import annotations
import uuid
from django.db import models


class CanonicalFieldDefinition(models.Model):
    """
    Master dictionary of all fields the system understands.
    Rules reference these field codes, not raw AI output keys.
    """
    class DataType(models.TextChoices):
        STRING  = "string",  "String"
        DECIMAL = "decimal", "Decimal"
        INTEGER = "integer", "Integer"
        DATE    = "date",    "Date"
        BOOLEAN = "boolean", "Boolean"
        JSON    = "json",    "JSON Array/Object"

    class FieldGroup(models.TextChoices):
        IDENTITY       = "identity",      "Core Identity"
        COUNTERPARTY   = "counterparty",  "Counterparty"
        FINANCIAL      = "financial",     "Financial"
        COMPLIANCE     = "compliance",    "Compliance / ZATCA"
        TIMELINE       = "timeline",      "Timeline"
        CLASSIFICATION = "classification","Classification"
        HR_PAYROLL     = "hr_payroll",    "HR / Payroll"
        ASSET          = "asset",         "Fixed Asset"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    field_code = models.CharField(max_length=100, unique=True, db_index=True)
    label_en   = models.CharField(max_length=200)
    label_ar   = models.CharField(max_length=200)
    data_type  = models.CharField(max_length=20, choices=DataType.choices)
    field_group = models.CharField(max_length=30, choices=FieldGroup.choices)

    is_nullable              = models.BooleanField(default=True)
    default_value            = models.JSONField(null=True, blank=True)
    applicable_document_types = models.JSONField(
        default=list,
        help_text='["invoice","purchase_order",...] or ["*"] for all types'
    )

    required_for_storage        = models.BooleanField(default=False)
    required_for_rule_execution = models.BooleanField(default=False)
    required_for_reporting      = models.BooleanField(default=False)

    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "documents"
        ordering  = ["field_group", "sort_order"]
        verbose_name = "Canonical Field Definition"
        verbose_name_plural = "Canonical Field Definitions"

    def __str__(self):
        return f"{self.field_code} ({self.label_en})"


class DocumentTypeFieldMapping(models.Model):
    """
    Maps raw uploaded file / AI output column names → canonical field codes.
    Multiple source names can map to the same canonical field (priority-ordered).
    """
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    canonical_field = models.ForeignKey(
        CanonicalFieldDefinition, on_delete=models.CASCADE,
        related_name="source_mappings"
    )
    document_type   = models.CharField(max_length=50, db_index=True)

    source_column    = models.CharField(max_length=200, db_index=True)
    source_column_ar = models.CharField(max_length=200, blank=True)

    # Transform: "direct", "string", "decimal", "date_parse", "bool",
    #            "uppercase", "first_non_null", "integer"
    transform      = models.CharField(max_length=50, default="direct")
    transform_args = models.JSONField(default=dict, blank=True)

    priority   = models.PositiveSmallIntegerField(default=0)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "documents"
        unique_together = [("canonical_field", "document_type", "source_column")]
        ordering = ["-priority"]
        verbose_name = "Document Type Field Mapping"
        verbose_name_plural = "Document Type Field Mappings"

    def __str__(self):
        return f"{self.document_type}: {self.source_column} → {self.canonical_field.field_code}"


class DocumentCanonicalData(models.Model):
    """
    Canonical normalized snapshot of any document after upload.
    Single source of truth for rule execution.
    Additive — linked to existing typed models by name + UUID.
    """
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_type    = models.CharField(max_length=50, db_index=True)
    typed_model_name = models.CharField(max_length=100)
    typed_object_id  = models.UUIDField(db_index=True)

    # Full canonical field set: {field_code: value_or_null}
    canonical_data = models.JSONField(default=dict)

    # Per-field extraction metadata
    extraction_confidence = models.JSONField(
        default=dict,
        help_text="{field_code: 0.0-1.0}"
    )
    extraction_source = models.JSONField(
        default=dict,
        help_text="{field_code: 'ai'|'ocr'|'direct'|'default'|'human'}"
    )

    # Immutable original AI output — never overwritten
    raw_ai_output = models.JSONField(default=dict)

    version    = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "documents"
        unique_together = [("typed_model_name", "typed_object_id")]
        indexes = [
            models.Index(fields=["document_type"]),
            models.Index(fields=["typed_object_id"]),
        ]
        verbose_name = "Document Canonical Data"
        verbose_name_plural = "Document Canonical Data"

    def __str__(self):
        return f"{self.document_type} / {self.typed_object_id} (v{self.version})"

    def get(self, field_code: str, default=None):
        """Convenience accessor for canonical fields."""
        return self.canonical_data.get(field_code, default)
