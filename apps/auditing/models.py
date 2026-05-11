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
        # Phase 1 (legacy keys)
        INVOICE = "invoice", "Invoice"
        PURCHASE_ORDER = "purchase_order", "Purchase Order"
        BANK_STATEMENT = "bank_statement", "Bank Statement"
        PAYROLL = "payroll", "Payroll Report"
        EXPENSE_REPORT = "expense_report", "Expense Report"
        TAX_DECLARATION = "tax_declaration", "Tax Declaration"
        FIXED_ASSET = "fixed_asset", "Fixed Asset Record"
        SALES_RECEIPT = "sales_receipt", "Sales Receipt"
        # Phase 2/3 — full 20-type catalog
        SALES_INVOICE = "sales_invoice", "Sales Invoice"
        PURCHASE_INVOICE = "purchase_invoice", "Purchase Invoice"
        SALES_ORDER = "sales_order", "Sales Order"
        QUOTATION = "quotation", "Quotation"
        PROFORMA_INVOICE = "proforma_invoice", "Proforma Invoice"
        GOODS_RECEIPT_NOTE = "goods_receipt_note", "Goods Receipt Note"
        PAYMENT_VOUCHER = "payment_voucher", "Payment Voucher"
        RECEIPT_VOUCHER = "receipt_voucher", "Receipt Voucher"
        CASH_VOUCHER = "cash_voucher", "Cash Voucher"
        JOURNAL_ENTRY = "journal_entry", "Journal Entry"
        GENERAL_LEDGER = "general_ledger", "General Ledger"
        LEDGER = "ledger", "Ledger"
        CONTRACT = "contract", "Contract"
        SUPPLIER_STATEMENT = "supplier_statement", "Supplier Statement"
        CUSTOMER_STATEMENT = "customer_statement", "Customer Statement"
        VAT_RETURN = "vat_return", "VAT Return"
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


class AccountingRuleEvaluation(models.Model):
    """Persisted accounting rule evaluation results (GAAP/IFRS compliance checks)."""

    class Standard(models.TextChoices):
        GAAP = "gaap", "GAAP"
        IFRS = "ifrs", "IFRS"

    class RuleCategory(models.TextChoices):
        RECOGNITION = "recognition", "Recognition"
        CLASSIFICATION = "classification", "Classification"
        COMPLETENESS = "completeness", "Completeness"
        CONSISTENCY = "consistency", "Consistency"
        CUTOFF = "cutoff", "Cutoff"
        DOCUMENTATION = "documentation", "Documentation"
        ANOMALY = "anomaly", "Anomaly"
        DISCLOSURE = "disclosure", "Disclosure"

    class RuleStatus(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        WARNING = "warning", "Warning"
        NOT_APPLICABLE = "not_applicable", "Not Applicable"
        INSUFFICIENT_DATA = "insufficient_data", "Insufficient Data"

    class RuleSeverity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"
        INFO = "info", "Info"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="accounting_rule_evaluations",
    )
    report = models.ForeignKey(
        "reports.Report",
        on_delete=models.CASCADE,
        related_name="accounting_rule_evaluations",
        null=True,
        blank=True,
    )
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.CASCADE,
        related_name="accounting_rule_evaluations",
        null=True,
        blank=True,
    )
    audit_document = models.ForeignKey(
        AuditDocument,
        on_delete=models.SET_NULL,
        related_name="accounting_rule_evaluations",
        null=True,
        blank=True,
    )
    standard = models.CharField(max_length=10, choices=Standard.choices)
    rule_code = models.CharField(max_length=50, db_index=True)
    rule_title = models.CharField(max_length=255)
    rule_category = models.CharField(max_length=30, choices=RuleCategory.choices)
    rule_status = models.CharField(max_length=20, choices=RuleStatus.choices)
    rule_severity = models.CharField(max_length=10, choices=RuleSeverity.choices)
    observation = models.TextField(blank=True)
    failure_reason = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    score_impact = models.FloatField(default=0.0)
    confidence = models.FloatField(default=1.0)
    related_fields = models.JSONField(default=list, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    evaluated_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounting_rule_evaluations"
        ordering = ["-evaluated_at"]
        indexes = [
            models.Index(fields=["organization", "standard"]),
            models.Index(fields=["organization", "rule_code"]),
            models.Index(fields=["organization", "report"]),
            models.Index(fields=["organization", "invoice"]),
            models.Index(fields=["rule_status"]),
        ]

    def __str__(self):
        return f"[{self.standard}] {self.rule_code}: {self.rule_status}"


# ─── AI Validation Harness ────────────────────────────────────────────────────
# Scaffolding to track AI-component validation runs (OCR, fraud detection,
# duplicate detection, forecasting). The README pack mandates evidence
# behind every public accuracy claim — these models store that evidence.
# Datasets themselves live outside the codebase (CSV uploads or S3); the
# model just persists the metrics so the platform can answer "what's the
# current measured precision/recall of duplicate detection?" honestly.

class AIValidationDataset(models.Model):
    """A labeled dataset used for one validation run.

    The actual rows / files are uploaded by an operator (out of band) and
    referenced by `source_uri`. The model carries only metadata: name,
    version, language, document count, plus a description so operators
    can audit which dataset produced which metric.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="ai_validation_datasets",
        null=True, blank=True,
        help_text="NULL = platform-wide dataset shared across tenants.",
    )
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=32, default="1.0")
    description = models.TextField(blank=True)
    language = models.CharField(max_length=8, default="ar",
                                help_text="ISO 639-1 — 'ar', 'en', 'mixed'")
    document_type = models.CharField(max_length=64, blank=True,
                                     help_text="e.g. 'invoice', 'purchase_order'")
    source_uri = models.URLField(blank=True,
                                 help_text="S3/local path to the labeled CSV/JSONL file.")
    document_count = models.PositiveIntegerField(default=0)
    labeling_method = models.CharField(max_length=64, blank=True,
                                        help_text="manual / semi-auto / vendor")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_validation_datasets"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization"]),
            models.Index(fields=["document_type"]),
        ]

    def __str__(self):
        return f"{self.name} v{self.version} ({self.document_count} docs)"


class AIValidationRun(models.Model):
    """One execution of a validation suite against a dataset.

    Stores the metrics the AI_MODEL_VALIDATION_REPORT spec requires:
    precision / recall / F1 / false-positive / false-negative for
    classifier-type claims; MAPE / MAE / RMSE / bias for forecasting
    claims; document/field accuracy for OCR.

    All metric fields are nullable — different claims surface different
    subsets. Operators populate via the `validate_ai_claim` management
    command (see apps/auditing/management/commands/).
    """

    class Component(models.TextChoices):
        OCR              = "ocr",              "Invoice OCR / extraction"
        HANDWRITING      = "handwriting",      "Handwritten receipt recognition"
        DUPLICATE        = "duplicate",        "Duplicate invoice detection"
        FRAUD            = "fraud",            "Fraud / anomaly detection"
        VAT_CHECK        = "vat_check",        "VAT recalculation"
        CASH_FORECAST    = "cash_forecast",    "Cash-flow forecasting"
        VENDOR_RISK      = "vendor_risk",      "Vendor risk scoring"
        BENFORD          = "benford",          "Benford's law"
        OTHER            = "other",            "Other"

    class Decision(models.TextChoices):
        APPROVED       = "approved",       "Approved"
        WITH_LIMITS    = "with_limits",    "Approved with limitations"
        NOT_APPROVED   = "not_approved",   "Not approved"
        PENDING        = "pending",        "Pending review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey(
        AIValidationDataset, on_delete=models.PROTECT,
        related_name="runs",
    )
    component = models.CharField(max_length=32, choices=Component.choices,
                                  db_index=True)
    model_version = models.CharField(max_length=64,
                                      help_text="e.g. 'gpt-4o-2026-05', "
                                                "'pyocr-tesseract-5.3'")
    # Classifier metrics — all 0..1 except counts.
    precision = models.FloatField(null=True, blank=True)
    recall    = models.FloatField(null=True, blank=True)
    f1_score  = models.FloatField(null=True, blank=True)
    accuracy  = models.FloatField(null=True, blank=True)
    false_positive_rate = models.FloatField(null=True, blank=True)
    false_negative_rate = models.FloatField(null=True, blank=True)
    # Forecasting metrics.
    mape = models.FloatField(null=True, blank=True)
    mae  = models.FloatField(null=True, blank=True)
    rmse = models.FloatField(null=True, blank=True)
    bias = models.FloatField(null=True, blank=True)
    # OCR-specific.
    field_accuracy        = models.FloatField(null=True, blank=True)
    document_accuracy     = models.FloatField(null=True, blank=True)
    character_error_rate  = models.FloatField(null=True, blank=True)
    word_error_rate       = models.FloatField(null=True, blank=True)
    average_processing_ms = models.PositiveIntegerField(null=True, blank=True)
    # Counts for explainability.
    true_positives  = models.PositiveIntegerField(null=True, blank=True)
    false_positives = models.PositiveIntegerField(null=True, blank=True)
    true_negatives  = models.PositiveIntegerField(null=True, blank=True)
    false_negatives = models.PositiveIntegerField(null=True, blank=True)
    # Decision + approver.
    decision  = models.CharField(max_length=16, choices=Decision.choices,
                                 default=Decision.PENDING)
    approver  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    approver_notes = models.TextField(blank=True)
    # Free-form raw metrics for one-off claims.
    raw_metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ai_validation_runs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["component", "-created_at"]),
            models.Index(fields=["dataset", "-created_at"]),
            models.Index(fields=["decision"]),
        ]

    def __str__(self):
        return f"{self.component} v{self.model_version} ({self.decision})"

    def headline_metric(self) -> float | None:
        """Return the most useful single metric for the component."""
        if self.component == self.Component.OCR:
            return self.field_accuracy or self.document_accuracy
        if self.component in (self.Component.CASH_FORECAST,):
            return self.mape
        return self.f1_score or self.accuracy
