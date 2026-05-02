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
