"""Auditing App Models."""

import uuid

from django.conf import settings
from django.db import models


DOC_TYPE_CHOICES = [
    ("auto", "Auto Detect"),
    ("purchase_order", "Purchase Order"),
    ("bank_statement", "Bank Statement"),
    ("payroll", "Payroll Report"),
    ("expense_report", "Expense Report"),
    ("vat_return", "Tax Declaration"),
    ("fixed_asset", "Fixed Asset Record"),
    ("sales_receipt", "Sales Receipt"),
    ("invoice", "Invoice"),
    ("other", "Other"),
]


class AuditDocument(models.Model):
    """Represents a financial document uploaded for AI auditing."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_documents",
    )
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_documents",
    )
    file = models.FileField(upload_to="auditing/documents/%Y/%m/")
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveIntegerField(default=0)

    # Document type
    selected_doc_type = models.CharField(max_length=50, blank=True, help_text="User-provided hint")
    detected_doc_type = models.CharField(max_length=50, blank=True, help_text="AI-detected type")
    language = models.CharField(max_length=20, blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Extracted content
    extracted_text = models.TextField(blank=True)
    normalized_text = models.TextField(blank=True)

    # AI results
    ai_result = models.JSONField(default=dict, blank=True)
    overall_confidence = models.FloatField(default=0.0)
    overall_risk_level = models.CharField(max_length=20, default="low")

    # Error tracking
    processing_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit Document"
        verbose_name_plural = "Audit Documents"

    def __str__(self) -> str:
        return f"{self.original_name} [{self.status}]"

    @property
    def doc_type_display(self) -> str:
        """Return detected or selected doc type for display."""
        dtype = self.detected_doc_type or self.selected_doc_type or "auto"
        for key, label in DOC_TYPE_CHOICES:
            if key == dtype:
                return label
        return dtype

    @property
    def risk_badge_color(self) -> str:
        colors = {
            "low": "green",
            "medium": "amber",
            "high": "red",
            "critical": "red",
        }
        return colors.get(self.overall_risk_level, "slate")


class AuditFinding(models.Model):
    """Individual finding from the AI audit of a document."""

    FINDING_TYPE_CHOICES = [
        ("anomaly", "Anomaly"),
        ("validation", "Validation"),
        ("compliance", "Compliance"),
        ("recommendation", "Recommendation"),
    ]

    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    document = models.ForeignKey(
        AuditDocument,
        on_delete=models.CASCADE,
        related_name="findings",
    )
    finding_type = models.CharField(max_length=50, choices=FINDING_TYPE_CHOICES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="low")
    title = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "severity"]
        verbose_name = "Audit Finding"
        verbose_name_plural = "Audit Findings"

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.title} — {self.document.original_name}"
