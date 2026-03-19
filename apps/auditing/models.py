"""Auditing App Models."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Case, IntegerField, Value, When


class AuditDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class DocumentType(models.TextChoices):
        INVOICE = "invoice", "Invoice"
        PURCHASE_ORDER = "purchase_order", "Purchase Order"
        BANK_STATEMENT = "bank_statement", "Bank Statement"
        PAYROLL = "payroll", "Payroll Report"
        EXPENSE_REPORT = "expense_report", "Expense Report"
        TAX_DECLARATION = "tax_declaration", "Tax Declaration"
        FIXED_ASSET = "fixed_asset", "Fixed Asset Record"
        SALES_RECEIPT = "sales_receipt", "Sales Receipt"
        OTHER = "other", "Other"

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_documents",
    )
    file = models.FileField(upload_to="auditing/%Y/%m/")
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, blank=True)
    selected_doc_type = models.CharField(
        max_length=30, choices=DocumentType.choices, default=DocumentType.OTHER
    )
    detected_doc_type = models.CharField(
        max_length=30, choices=DocumentType.choices, blank=True
    )
    language = models.CharField(max_length=10, default="unknown")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    extracted_text = models.TextField(blank=True)
    normalized_text = models.TextField(blank=True)
    ai_result = models.JSONField(null=True, blank=True)
    overall_confidence = models.FloatField(null=True, blank=True)
    overall_risk_level = models.CharField(
        max_length=10, choices=RiskLevel.choices, blank=True
    )
    executive_summary = models.TextField(blank=True)
    processing_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_name} ({self.status})"

    @property
    def doc_type_display(self) -> str:
        """Return detected or selected doc type label for display."""
        dtype = self.detected_doc_type or self.selected_doc_type or "other"
        for value, label in self.DocumentType.choices:
            if value == dtype:
                return label
        return dtype

    @property
    def risk_badge_color(self) -> str:
        colors = {
            "low": "green",
            "medium": "amber",
            "high": "red",
            "critical": "rose",
        }
        return colors.get(self.overall_risk_level, "slate")


class AuditFinding(models.Model):
    class FindingType(models.TextChoices):
        ANOMALY = "anomaly", "Anomaly"
        VALIDATION = "validation", "Validation"
        COMPLIANCE = "compliance", "Compliance"
        RISK = "risk", "Risk"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    document = models.ForeignKey(
        AuditDocument, on_delete=models.CASCADE, related_name="findings"
    )
    finding_type = models.CharField(max_length=20, choices=FindingType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    title = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    source = models.CharField(max_length=50, default="ai")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [
            Case(
                When(severity="critical", then=Value(0)),
                When(severity="high", then=Value(1)),
                When(severity="medium", then=Value(2)),
                When(severity="low", then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            ),
            "finding_type",
        ]

    def __str__(self):
        return f"[{self.severity}] {self.title}"
