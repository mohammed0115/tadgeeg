"""
Invoice Auditing App — Models
Covers all 30 invoice auditing rules from the business requirements.
"""

import uuid
from django.db import models
from apps.authentication.models import User, Organization


# ─── Risk / Severity choices shared across models ─────────────────────────────
class Severity(models.TextChoices):
    LOW      = "low",      "Low"
    MEDIUM   = "medium",   "Medium"
    HIGH     = "high",     "High"
    CRITICAL = "critical", "Critical"


# ─── Invoice ──────────────────────────────────────────────────────────────────

class Invoice(models.Model):
    """Core invoice record — populated by OCR + AI extraction."""

    class Status(models.TextChoices):
        PENDING    = "pending",    "Pending Review"
        PROCESSING = "processing", "Processing"
        VALIDATED  = "validated",  "Validated"
        FLAGGED    = "flagged",    "Flagged"
        APPROVED   = "approved",   "Approved"
        REJECTED   = "rejected",   "Rejected"

    class Currency(models.TextChoices):
        SAR = "SAR", "Saudi Riyal"
        AED = "AED", "UAE Dirham"
        USD = "USD", "US Dollar"
        EUR = "EUR", "Euro"
        GBP = "GBP", "British Pound"
        KWD = "KWD", "Kuwaiti Dinar"
        QAR = "QAR", "Qatari Riyal"
        OMR = "OMR", "Omani Rial"
        BHD = "BHD", "Bahraini Dinar"

    # Identity
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization      = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invoices")
    uploaded_by       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="uploaded_invoices")
    audit_session     = models.ForeignKey("audit.AuditSession", on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")
    batch             = models.ForeignKey("InvoiceBatch", on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")

    # Source file
    file              = models.FileField(upload_to="invoices/%Y/%m/", null=True, blank=True)
    original_filename = models.CharField(max_length=255)
    file_size         = models.PositiveIntegerField(default=0)
    mime_type         = models.CharField(max_length=100, blank=True)

    # ── Rule Group 1: Invoice Header Fields (MUST exist) ──────────────────────
    invoice_number    = models.CharField(max_length=100, blank=True)   # Rule 1
    invoice_date      = models.DateField(null=True, blank=True)         # Rule 2
    due_date          = models.DateField(null=True, blank=True)
    vendor_name       = models.CharField(max_length=255, blank=True)    # Rule 3
    vendor_name_ar    = models.CharField(max_length=255, blank=True)
    vendor_vat_number = models.CharField(max_length=20,  blank=True)   # Rule 4
    vendor_cr_number  = models.CharField(max_length=20,  blank=True)
    vendor_address    = models.TextField(blank=True)
    vendor_phone      = models.CharField(max_length=30,  blank=True)
    customer_name     = models.CharField(max_length=255, blank=True)
    customer_vat_number = models.CharField(max_length=20, blank=True)

    # ── Rule Group 3: Financial Amounts ───────────────────────────────────────
    currency          = models.CharField(max_length=3, choices=Currency.choices, blank=True)   # Rule 5 / 6
    subtotal          = models.DecimalField(max_digits=18, decimal_places=2, default=0)         # Rule 7 / Subtotal+VAT=Total
    vat_rate          = models.DecimalField(max_digits=5,  decimal_places=2, default=15)        # Rule: 15% in SA
    vat_amount        = models.DecimalField(max_digits=18, decimal_places=2, default=0)         # Rule 3 VAT present
    discount          = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount      = models.DecimalField(max_digits=18, decimal_places=2, default=0)         # Rule 8 > 0

    # ── Line items (JSON array) ────────────────────────────────────────────────
    line_items        = models.JSONField(default=list)

    # ── Document quality fields ────────────────────────────────────────────────
    has_qr_code       = models.BooleanField(default=False)       # Rule 7.4 - ZATCA QR
    qr_code_valid     = models.BooleanField(default=False)
    qr_code_image     = models.TextField(blank=True)             # Base64-encoded QR code image (data:image/png;base64,...)
    qr_code_data      = models.TextField(blank=True)             # Base64-encoded TLV data for the QR
    is_handwritten    = models.BooleanField(default=False)
    is_clear          = models.BooleanField(default=True)        # Rule 7.1
    has_alterations   = models.BooleanField(default=False)       # Rule 7.3 - tampered
    ocr_confidence    = models.FloatField(default=0.0)
    language          = models.CharField(max_length=10, default="unknown")
    raw_text          = models.TextField(blank=True)
    extracted_data    = models.JSONField(default=dict)

    # ── Accounting linkage ─────────────────────────────────────────────────────
    cost_center       = models.CharField(max_length=50,  blank=True)   # Rule 5.1
    account_code      = models.CharField(max_length=50,  blank=True)   # Rule 5.2
    budget_code       = models.CharField(max_length=50,  blank=True)   # Rule 5.3
    department        = models.CharField(max_length=100, blank=True)

    # ── Workflow ───────────────────────────────────────────────────────────────
    status            = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    approved_by       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_invoices")
    approved_at       = models.DateTimeField(null=True, blank=True)
    rejected_reason   = models.TextField(blank=True)

    # ── AI Risk Assessment ─────────────────────────────────────────────────────
    risk_score        = models.FloatField(default=0.0)          # 0-100
    risk_level        = models.CharField(max_length=10, choices=Severity.choices, default=Severity.LOW)
    is_duplicate      = models.BooleanField(default=False)
    duplicate_of      = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="duplicates")
    ai_summary        = models.TextField(blank=True)            # AI智能摘要
    ai_recommendations = models.JSONField(default=list)         # AI recommendations

    # ── Metadata ───────────────────────────────────────────────────────────────
    processing_error  = models.TextField(blank=True)
    tags              = models.JSONField(default=list)
    notes             = models.TextField(blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)    
    # ── Soft Delete (GDPR Compliance) ───────────────────────────────────────────────────
    is_deleted        = models.BooleanField(default=False, db_index=True)  # Soft delete flag
    deleted_at        = models.DateTimeField(null=True, blank=True)        # When deleted
    deleted_by        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="deleted_invoices")  # Who deleted

    # ── IAS 7 Cash Flow Classification (Statement of Cash Flows) ────────────────
    class CashFlowClass(models.TextChoices):
        OPERATING  = "operating",  "Operating Activities (IAS 7 §15)"
        INVESTING  = "investing",  "Investing Activities (IAS 7 §16)"
        FINANCING  = "financing",  "Financing Activities (IAS 7 §17)"
        UNCLASSIFIED = "unclassified", "Unclassified (Pending Manual Review)"

    class CashFlowSubCategory(models.TextChoices):
        # Operating
        OP_REVENUE         = "op_revenue",         "Sales Revenue"
        OP_SUPPLIES        = "op_supplies",        "Supplies & Materials"
        OP_UTILITIES       = "op_utilities",       "Utilities (Water, Electricity, Gas)"
        OP_RENT            = "op_rent",            "Rent & Leasing"
        OP_SALARY          = "op_salary",          "Salaries & Wages"
        OP_PROFESSIONAL    = "op_professional",    "Professional Services (Legal, Consulting)"
        OP_MAINTENANCE     = "op_maintenance",     "Repairs & Maintenance"
        OP_INSURANCE       = "op_insurance",       "Insurance"
        OP_TRAVEL          = "op_travel",          "Travel & Transportation"
        OP_OTHER           = "op_other",           "Other Operating Expenses"
        
        # Investing
        INV_EQUIPMENT      = "inv_equipment",      "Equipment & Machinery"
        INV_PROPERTY       = "inv_property",       "Property (Real Estate)"
        INV_INTANGIBLE     = "inv_intangible",     "Intangible Assets (Software, Patents)"
        INV_INVESTMENTS    = "inv_investments",    "Investment Securities"
        INV_OTHER          = "inv_other",          "Other Investing Activities"
        
        # Financing
        FIN_LOAN_PROCEEDS  = "fin_loan",           "Loan Proceeds"
        FIN_DEBT_REPAY     = "fin_debt_repay",     "Debt Repayment"
        FIN_EQUITY         = "fin_equity",         "Equity Financing"
        FIN_DIVIDENDS      = "fin_dividends",      "Dividend Payments"
        FIN_OTHER          = "fin_other",          "Other Financing Activities"

    cash_flow_class      = models.CharField(
        max_length=20, 
        choices=CashFlowClass.choices,
        default=CashFlowClass.UNCLASSIFIED,
        db_index=True,
        help_text="IAS 7 cash flow statement classification per operating/investing/financing"
    )
    cash_flow_subcategory = models.CharField(
        max_length=30,
        choices=CashFlowSubCategory.choices,
        blank=True,
        help_text="Detailed subcategory for cash flow reporting"
    )
    cash_flow_confidence  = models.FloatField(
        default=0.0,
        help_text="Auto-classification confidence (0.0-1.0); manually set invoices have 1.0"
    )
    cash_flow_verified    = models.BooleanField(
        default=False,
        help_text="Whether cash flow classification was manually verified by accounting"
    )
    cash_flow_verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_invoices_cashflow"
    )
    cash_flow_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "invoices"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "invoice_number"]),
            models.Index(fields=["organization", "vendor_name"]),
            models.Index(fields=["organization", "invoice_date"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["risk_level"]),
            models.Index(fields=["is_duplicate"]),
        ]

    def save(self, *args, **kwargs):
        # Keep uploads and tests resilient by inheriting ownership/session from the batch.
        if self.batch_id:
            if not self.organization_id and self.batch.organization_id:
                self.organization = self.batch.organization
            if not self.audit_session_id and self.batch.audit_session_id:
                self.audit_session = self.batch.audit_session
            if not self.uploaded_by_id and self.batch.uploaded_by_id:
                self.uploaded_by = self.batch.uploaded_by
        super().save(*args, **kwargs)

    def __str__(self):
        return f"INV-{self.invoice_number or self.id} | {self.vendor_name} | {self.total_amount} {self.currency}"

    @property
    def expected_vat(self):
        """Calculated expected VAT based on subtotal and rate."""
        return round(float(self.subtotal) * float(self.vat_rate) / 100, 2)

    @property
    def vat_is_correct(self):
        """Check if subtotal + vat_amount ≈ total_amount."""
        diff = abs(float(self.subtotal) + float(self.vat_amount) - float(self.total_amount))
        return diff < 1.0  # tolerance of 1 currency unit

    @property
    def vat_rate_is_correct(self):
        """Check if VAT rate matches expected (15% for Saudi Arabia)."""
        if float(self.subtotal) == 0:
            return True
        actual_rate = float(self.vat_amount) / float(self.subtotal) * 100
        return abs(actual_rate - float(self.vat_rate)) < 0.5

    def generate_zatca_qr(self):
        """
        Generate ZATCA Phase 2 QR code for this invoice.
        Stores the QR code image and data in the model.
        
        Returns:
            Dict with keys: status, message, qr_base64, qr_hash
        """
        from apps.compliance.zatca_qr_service import generate_invoice_qr
        
        # Generate QR code
        result = generate_invoice_qr(
            self,
            previous_invoice_hash=self.extracted_data.get('file_hash') if self.extracted_data else None
        )
        
        # Update invoice with QR data
        if result['status'] == 'success':
            self.qr_code_image = result['qr_base64']
            self.qr_code_data = result['tlv_data']
            self.has_qr_code = True
            self.qr_code_valid = True
        else:
            self.has_qr_code = False
            self.qr_code_valid = False
        
        return result


# ─── Invoice Batch ────────────────────────────────────────────────────────────

class InvoiceBatch(models.Model):
    """A batch upload — single file, multiple files, or ZIP archive."""

    class BatchStatus(models.TextChoices):
        PENDING    = "pending",    "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED  = "completed",  "Completed"
        PARTIAL    = "partial",    "Partial (some failed)"
        FAILED     = "failed",     "Failed"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization    = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invoice_batches")
    uploaded_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="invoice_batches")
    audit_session   = models.ForeignKey("audit.AuditSession", on_delete=models.SET_NULL, null=True, blank=True, related_name="invoice_batches")
    batch_name      = models.CharField(max_length=255, blank=True)
    status          = models.BatchStatus if False else models.CharField(max_length=15, choices=BatchStatus.choices, default=BatchStatus.PENDING)
    total_files     = models.PositiveIntegerField(default=0)
    processed_files = models.PositiveIntegerField(default=0)
    failed_files    = models.PositiveIntegerField(default=0)
    source_zip      = models.FileField(upload_to="batches/%Y/%m/", null=True, blank=True)
    processing_log  = models.JSONField(default=list)
    created_at      = models.DateTimeField(auto_now_add=True)
    completed_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "invoice_batches"
        ordering = ["-created_at"]

    def __init__(self, *args, **kwargs):
        legacy_name = kwargs.pop("name", None)
        if legacy_name is not None and "batch_name" not in kwargs:
            kwargs["batch_name"] = legacy_name
        super().__init__(*args, **kwargs)

    @property
    def name(self):
        return self.batch_name

    @name.setter
    def name(self, value):
        self.batch_name = value or ""

    def save(self, *args, **kwargs):
        # Allow callers to provide only an audit session and derive the organization safely.
        if self.audit_session_id and not self.organization_id and self.audit_session.organization_id:
            self.organization = self.audit_session.organization
        if self.audit_session_id and not self.uploaded_by_id and self.audit_session.created_by_id:
            self.uploaded_by = self.audit_session.created_by
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Batch {self.id} | {self.total_files} files | {self.status}"


# ─── Validation Result ────────────────────────────────────────────────────────

class InvoiceValidationResult(models.Model):
    """Results of running all 30 validation rules on an invoice."""

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name="validation")

    # ── Group 1: Invoice Header Validation (8 rules) ──────────────────────────
    has_invoice_number   = models.BooleanField(default=False)
    has_invoice_date     = models.BooleanField(default=False)
    has_vendor_name      = models.BooleanField(default=False)
    has_vendor_vat       = models.BooleanField(default=False)
    has_total_amount     = models.BooleanField(default=False)
    has_currency         = models.BooleanField(default=False)
    total_greater_zero   = models.BooleanField(default=False)
    no_vat_without_base  = models.BooleanField(default=False)  # VAT not present without subtotal

    # ── Group 2: Duplicate Detection (5 rules) ────────────────────────────────
    duplicate_invoice_number    = models.BooleanField(default=False)  # True = problem found
    duplicate_vendor_and_number = models.BooleanField(default=False)
    duplicate_vendor_amount_date = models.BooleanField(default=False)
    duplicate_file_hash         = models.BooleanField(default=False)
    duplicate_across_months     = models.BooleanField(default=False)

    # ── Group 3: VAT Validation (5 rules) ─────────────────────────────────────
    vat_rate_correct       = models.BooleanField(default=False)  # 15% for SA
    vat_calculation_correct = models.BooleanField(default=False)  # subtotal+vat=total
    vat_subtotal_correct   = models.BooleanField(default=False)
    vat_number_present     = models.BooleanField(default=False)
    qr_code_valid          = models.BooleanField(default=False)

    # ── Group 4: Anomaly Detection (6 rules) ─────────────────────────────────
    amount_unusually_high      = models.BooleanField(default=False)  # True = anomaly found
    new_unknown_vendor         = models.BooleanField(default=False)
    many_invoices_same_day     = models.BooleanField(default=False)
    sudden_price_change        = models.BooleanField(default=False)
    many_invoices_year_end     = models.BooleanField(default=False)
    vendor_dominates_invoices  = models.BooleanField(default=False)

    # ── Group 5: Financial Control (6 rules) ─────────────────────────────────
    has_cost_center      = models.BooleanField(default=False)
    has_account_code     = models.BooleanField(default=False)
    within_budget        = models.BooleanField(default=True)
    no_edit_after_approve = models.BooleanField(default=True)
    has_approver         = models.BooleanField(default=False)
    has_audit_trail      = models.BooleanField(default=True)

    # ── Group 6: Document Quality (4 rules) ──────────────────────────────────
    document_is_clear    = models.BooleanField(default=False)
    appears_genuine      = models.BooleanField(default=False)
    no_alterations       = models.BooleanField(default=False)
    has_qr_code          = models.BooleanField(default=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_rules          = models.PositiveSmallIntegerField(default=30)
    rules_passed         = models.PositiveSmallIntegerField(default=0)
    rules_failed         = models.PositiveSmallIntegerField(default=0)
    validation_score     = models.FloatField(default=0.0)   # 0-100
    failed_rule_codes    = models.JSONField(default=list)   # list of failed rule IDs
    validation_details   = models.JSONField(default=dict)   # per-rule detail
    validated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "invoice_validation_results"

    def __str__(self):
        return f"Validation for {self.invoice} | Score: {self.validation_score}%"


# ─── Vendor Profile ───────────────────────────────────────────────────────────

class VendorProfile(models.Model):
    """Aggregated, tenant-isolated vendor intelligence used by audit and risk scoring."""

    class RiskTier(models.TextChoices):
        LOW      = "low",      "Low Risk"
        MEDIUM   = "medium",   "Medium Risk"
        HIGH     = "high",     "High Risk"
        BLOCKED  = "blocked",  "Blocked"

    id                 = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization       = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="vendor_profiles")
    vendor_name        = models.CharField(max_length=255)
    vendor_vat_number  = models.CharField(max_length=20, blank=True)
    vendor_cr_number   = models.CharField(max_length=20, blank=True)
    first_seen         = models.DateField(null=True, blank=True)
    last_seen          = models.DateField(null=True, blank=True)
    invoice_count      = models.PositiveIntegerField(default=0)
    total_amount       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    avg_invoice_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    max_invoice_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    duplicate_count    = models.PositiveIntegerField(default=0)
    flagged_count      = models.PositiveIntegerField(default=0)
    compliance_issue_count = models.PositiveIntegerField(default=0)
    high_risk_audit_count = models.PositiveIntegerField(default=0)
    transaction_frequency_30d = models.FloatField(default=0.0, help_text="Recent document frequency for this vendor over the last 30 days.")
    last_transaction_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    is_new             = models.BooleanField(default=True)     # new = first time vendor
    is_suspicious      = models.BooleanField(default=False)
    is_approved        = models.BooleanField(null=True, blank=True)
    risk_score         = models.FloatField(default=0.0, help_text="Dynamic vendor risk score (0-100) derived from audit history.")
    risk_tier          = models.CharField(max_length=10, choices=RiskTier.choices, default=RiskTier.LOW)
    risk_notes         = models.TextField(blank=True)
    tags               = models.JSONField(default=list)
    transaction_history = models.JSONField(default=dict, blank=True)
    compliance_history  = models.JSONField(default=dict, blank=True)
    last_audit_at      = models.DateTimeField(null=True, blank=True)
    last_compliance_issue_at = models.DateTimeField(null=True, blank=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vendor_profiles"
        unique_together = [("organization", "vendor_name")]
        ordering = ["-risk_score", "-total_amount"]

    @property
    def vendor_risk_score(self):
        return float(self.risk_score or 0)

    @property
    def average_transaction_value(self):
        return self.avg_invoice_amount

    def __str__(self):
        return f"{self.vendor_name} | score={self.risk_score:.1f} | {self.risk_tier}"


# ─── Invoice Audit Trail ──────────────────────────────────────────────────────

class InvoiceAuditEvent(models.Model):
    """Every action on an invoice is recorded here (Rule Group 8)."""

    class EventType(models.TextChoices):
        UPLOADED   = "uploaded",   "Invoice Uploaded"
        PROCESSED  = "processed",  "OCR / AI Processed"
        VALIDATED  = "validated",  "Validation Run"
        FLAGGED    = "flagged",    "Flagged"
        EDITED     = "edited",     "Edited"
        APPROVED   = "approved",   "Approved"
        REJECTED   = "rejected",   "Rejected"
        COMMENTED  = "commented",  "Comment Added"
        EXPORTED   = "exported",   "Exported"
        REPROCESSED = "reprocessed", "Re-processed"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice    = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="audit_events")
    user       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="invoice_events")
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    description = models.TextField(blank=True)
    before_data = models.JSONField(default=dict)  # snapshot before change
    after_data  = models.JSONField(default=dict)   # snapshot after change
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    timestamp   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "invoice_audit_events"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.event_type} on {self.invoice_id} by {self.user} at {self.timestamp}"
