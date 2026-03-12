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
