"""Documents App Models"""

import uuid
from django.db import models
from apps.authentication.models import User, Organization


class Document(models.Model):
    """Uploaded financial document with metadata."""

    class DocumentType(models.TextChoices):
        INVOICE = "invoice", "Invoice"
        RECEIPT = "receipt", "Receipt"
        BANK_STATEMENT = "bank_statement", "Bank Statement"
        LEDGER = "ledger", "General Ledger"
        CONTRACT = "contract", "Contract"
        PURCHASE_ORDER = "purchase_order", "Purchase Order"
        EXPENSE_REPORT = "expense_report", "Expense Report"
        TAX_DOCUMENT = "tax_document", "Tax Document"
        FINANCIAL_STATEMENT = "financial_statement", "Financial Statement"
        OTHER = "other", "Other"

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        NEEDS_REVIEW = "needs_review", "Needs Manual Review"

    class Language(models.TextChoices):
        ARABIC = "ar", "Arabic"
        ENGLISH = "en", "English"
        MIXED = "mixed", "Arabic + English"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="uploaded_documents")
    file = models.FileField(upload_to="documents/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(help_text="Size in bytes")
    mime_type = models.CharField(max_length=100)
    document_type = models.CharField(
        max_length=30, choices=DocumentType.choices, default=DocumentType.OTHER
    )
    processing_status = models.CharField(
        max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.PENDING
    )
    language = models.CharField(
        max_length=10, choices=Language.choices, default=Language.UNKNOWN
    )
    is_handwritten = models.BooleanField(default=False)
    page_count = models.PositiveIntegerField(default=1)
    ocr_confidence = models.FloatField(null=True, blank=True, help_text="0-100 confidence score")
    processing_error = models.TextField(blank=True)
    processing_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    tags = models.JSONField(default=list)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "documents"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "document_type"]),
            models.Index(fields=["processing_status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.document_type})"


class ExtractedData(models.Model):
    """Structured data extracted from a document via OCR / AI."""

    class ValidationStatus(models.TextChoices):
        PENDING = "pending", "Pending Validation"
        VALIDATED = "validated", "Validated"
        REJECTED = "rejected", "Rejected"
        AUTO_VALIDATED = "auto_validated", "Auto-Validated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="extracted_data")
    raw_text = models.TextField(blank=True, help_text="Full OCR text output")
    structured_data = models.JSONField(default=dict, help_text="Parsed structured fields")
    validation_status = models.CharField(
        max_length=20, choices=ValidationStatus.choices, default=ValidationStatus.PENDING
    )
    validated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="validated_extractions"
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    corrections = models.JSONField(default=dict, help_text="Human corrections applied")
    extraction_method = models.CharField(max_length=50, default="tesseract", help_text="tesseract | openai | hybrid")
    ai_model_used = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "extracted_data"

    def __str__(self):
        return f"Extraction for {self.document.original_filename}"


class DocumentPageResult(models.Model):
    """Per-page OCR results for multi-page documents."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="page_results")
    page_number = models.PositiveSmallIntegerField()
    raw_text = models.TextField()
    confidence = models.FloatField(default=0.0)
    image_path = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "document_page_results"
        unique_together = [("document", "page_number")]
        ordering = ["page_number"]


class DocumentAnalysisResult(models.Model):
    """
    Persisted output of the full Financial AI + Audit pipeline for one document.

    Created by process_document_full_pipeline Celery task after:
      DocumentEngine.ingest() → FinancialAIEngine.analyse() → AuditEngine.evaluate()

    This model is the single source of truth for AI-derived risk and compliance data
    attached to a Document record.
    """

    class RiskLevel(models.TextChoices):
        LOW      = "low",      "Low"
        MEDIUM   = "medium",   "Medium"
        HIGH     = "high",     "High"
        CRITICAL = "critical", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="analysis_result"
    )

    # ── Classification ─────────────────────────────────────────────────────────
    ai_document_type       = models.CharField(max_length=50, default="other")
    classification_confidence = models.FloatField(default=0.0)
    classification_method  = models.CharField(max_length=50, default="unknown")

    # ── Key extracted fields (queryable, denormalised) ─────────────────────────
    vendor_name     = models.CharField(max_length=255, blank=True)
    document_number = models.CharField(max_length=100, blank=True)
    doc_date        = models.DateField(null=True, blank=True)
    currency        = models.CharField(max_length=10, default="SAR")
    total_amount    = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    tax_amount      = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    # ── Risk & intelligence scores ─────────────────────────────────────────────
    risk_score       = models.PositiveSmallIntegerField(default=0, help_text="0–100")
    risk_level       = models.CharField(max_length=10, choices=RiskLevel.choices, default=RiskLevel.LOW)
    fraud_score      = models.FloatField(default=0.0, help_text="0.0–1.0")
    duplicate_score  = models.FloatField(default=0.0, help_text="0.0–1.0")
    compliance_score = models.FloatField(default=1.0, help_text="0.0–1.0")
    is_duplicate     = models.BooleanField(default=False)
    requires_review  = models.BooleanField(default=False)
    escalate         = models.BooleanField(default=False)

    # ── Full serialised output ─────────────────────────────────────────────────
    analysis_data    = models.JSONField(default=dict, help_text="Full FinancialAnalysisResult.to_dict()")
    audit_report     = models.JSONField(default=dict, help_text="Serialised AuditReport from AuditEngine")

    # ── Processing metadata ────────────────────────────────────────────────────
    pipeline_version    = models.CharField(max_length=20, default="2.0")
    processing_errors   = models.JSONField(default=list)
    processing_time_ms  = models.PositiveIntegerField(null=True, blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_analysis_results"
        indexes  = [
            models.Index(fields=["risk_level"]),
            models.Index(fields=["is_duplicate"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Analysis[{self.document.original_filename}] risk={self.risk_level}"


class DocumentStateHistory(models.Model):
    """
    Immutable audit trail of every processing_status change on a Document.

    Written by DocumentStateHistoryService whenever a Document transitions
    states.  Never updated after creation — append-only by design.

    Usage:
        from apps.documents.services import DocumentStateHistoryService
        DocumentStateHistoryService.record(
            document=doc,
            from_state=old_status,
            to_state=new_status,
            changed_by=request.user,   # or None for system transitions
            reason="Pipeline stage 1 complete",
            metadata={"pipeline_version": "2.0", "processing_time_ms": 340},
        )
    """

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document    = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="state_history"
    )
    from_state  = models.CharField(
        max_length=20, choices=Document.ProcessingStatus.choices,
        blank=True,    # Blank on initial PENDING creation
    )
    to_state    = models.CharField(
        max_length=20, choices=Document.ProcessingStatus.choices,
    )
    changed_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="document_state_changes",
        help_text="Null = system / Celery worker",
    )
    reason      = models.CharField(max_length=500, blank=True)
    metadata    = models.JSONField(
        default=dict, blank=True,
        help_text="Arbitrary context: pipeline_version, processing_time_ms, worker_id …",
    )
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table   = "document_state_history"
        ordering   = ["created_at"]
        indexes    = [
            models.Index(fields=["document", "created_at"]),
            models.Index(fields=["to_state", "created_at"]),
        ]

    def __str__(self) -> str:
        who = self.changed_by.email if self.changed_by_id else "system"
        return (
            f"{self.document.original_filename}: "
            f"{self.from_state or '—'} → {self.to_state} [{who}]"
        )


from .typed_models import (
    PurchaseOrder,
    PurchaseOrderValidation,
    BankStatement,
    BankStatementValidation,
    PayrollSheet,
    PayrollValidation,
    ExpenseReport,
    ExpenseReportValidation,
    VATReturn,
    VATReturnValidation,
    FixedAsset,
    FixedAssetValidation,
    SalesReceipt,
    SalesReceiptValidation,
)
