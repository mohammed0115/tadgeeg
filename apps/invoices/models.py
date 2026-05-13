"""
Invoice Auditing App — Models
Covers all 30 invoice auditing rules from the business requirements.
"""

import uuid
from django.db import models
from apps.audit.integrity import HashChainMixin
from apps.authentication.models import User, Organization
from core.constants import VAT_MATH_TOLERANCE, VAT_RATE_TOLERANCE
from core.mixins import SoftDeleteModel


# ─── Risk / Severity choices shared across models ─────────────────────────────
class Severity(models.TextChoices):
    LOW      = "low",      "Low"
    MEDIUM   = "medium",   "Medium"
    HIGH     = "high",     "High"
    CRITICAL = "critical", "Critical"


# ─── Invoice ──────────────────────────────────────────────────────────────────

class Invoice(SoftDeleteModel):
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

    # ── Workflow (with Segregation of Duties) ──────────────────────────────────
    # SoD three-eyes pattern: uploaded_by (Maker) → reviewed_by (Checker) →
    # approved_by (Approver). The triple must consist of distinct users on
    # any fully-approved invoice — enforced at the service layer in
    # apps.invoices.services.sod_service. See that module for the rationale.
    status            = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    reviewed_by       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_invoices")
    reviewed_at       = models.DateTimeField(null=True, blank=True)
    approved_by       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_invoices")
    approved_at       = models.DateTimeField(null=True, blank=True)
    rejected_reason   = models.TextField(blank=True)

    # ── AI Risk Assessment ─────────────────────────────────────────────────────
    risk_score        = models.FloatField(default=0.0)          # 0-100
    risk_level        = models.CharField(max_length=10, choices=Severity.choices, default=Severity.LOW)
    is_duplicate      = models.BooleanField(default=False)
    duplicate_of      = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="duplicates")
    ai_summary        = models.TextField(blank=True)
    ai_summary_ar     = models.TextField(blank=True)
    ai_summary_en     = models.TextField(blank=True)
    ai_recommendations = models.JSONField(default=list)
    ai_recommendations_ar = models.JSONField(default=list)
    ai_recommendations_en = models.JSONField(default=list)

    # ── Metadata ───────────────────────────────────────────────────────────────
    processing_error  = models.TextField(blank=True)
    tags              = models.JSONField(default=list)
    notes             = models.TextField(blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)    
    # ── Soft Delete (GDPR Compliance) — fields from SoftDeleteModel mixin ────────
    # is_deleted / deleted_at inherited from SoftDeleteModel
    deleted_by        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="deleted_invoices")

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
        return diff < VAT_MATH_TOLERANCE  # tolerance of 1 currency unit

    @property
    def vat_rate_is_correct(self):
        """Check if VAT rate matches expected (15% for Saudi Arabia)."""
        if float(self.subtotal) == 0:
            return True
        actual_rate = float(self.vat_amount) / float(self.subtotal) * 100
        return abs(actual_rate - float(self.vat_rate)) < VAT_RATE_TOLERANCE

    # generate_zatca_qr() was removed from this model — models are pure data
    # containers and must not call external services.
    # Use apps.compliance.zatca_qr_service.attach_qr_to_invoice(invoice) instead.


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
    status          = models.CharField(max_length=15, choices=BatchStatus.choices, default=BatchStatus.PENDING)
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
    """
    Results of running all validation rules on an invoice.

    Schema change (2026-04-09):
      The previous schema had 30+ individual boolean columns — one per rule.
      This made every new/renamed rule require a database migration and forced
      serializer and admin changes in lockstep.

      The new schema stores rule results in ``rule_results`` (a JSON array) so
      the rule set can grow without schema changes.

      ``rule_results`` format:
          [
              {
                  "rule_code":  "INV-001",
                  "rule_name":  "Invoice Number Present",
                  "group":      "INV",
                  "severity":   "high",
                  "passed":     true,
                  "detail":     ""
              },
              ...
          ]

      The boolean columns are retained below as read-only computed properties
      so that any existing code that reads them still works without modification.
      They are NOT stored in the database any more — do not add them to
      migrations.

    Migration required: see apps/invoices/migrations/ for 0xxx_validation_json.
    """

    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name="validation")

    # ── Rule results (JSON array — replaces the 30 boolean columns) ───────────
    rule_results     = models.JSONField(
        default=list,
        help_text=(
            "List of per-rule result dicts: "
            "[{rule_code, rule_name, group, severity, passed, detail}, ...]"
        ),
    )

    # ── Summary counters ───────────────────────────────────────────────────────
    total_rules      = models.PositiveSmallIntegerField(default=0)
    rules_passed     = models.PositiveSmallIntegerField(default=0)
    rules_failed     = models.PositiveSmallIntegerField(default=0)
    validation_score = models.FloatField(default=0.0)         # 0-100
    failed_rule_codes = models.JSONField(default=list)         # ["INV-001", ...]
    validation_details = models.JSONField(default=dict)        # legacy extra detail blob
    validated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "invoice_validation_results"

    def __str__(self):
        return f"Validation for {self.invoice} | Score: {self.validation_score}%"

    # ── Backward-compat helpers (read-only, not stored) ───────────────────────

    def _rule_passed(self, code: str) -> bool:
        for r in (self.rule_results or []):
            if r.get("rule_code") == code:
                return bool(r.get("passed", False))
        return False

    def _rule_failed(self, code: str) -> bool:
        return not self._rule_passed(code)

    @property
    def has_invoice_number(self):    return self._rule_passed("INV-001")
    @property
    def has_invoice_date(self):      return self._rule_passed("INV-002")
    @property
    def has_vendor_name(self):       return self._rule_passed("INV-003")
    @property
    def has_vendor_vat(self):        return self._rule_passed("INV-004")
    @property
    def has_total_amount(self):      return self._rule_passed("INV-008")
    @property
    def has_currency(self):          return self._rule_passed("INV-005")
    @property
    def total_greater_zero(self):    return self._rule_passed("INV-007")
    @property
    def duplicate_file_hash(self):   return self._rule_failed("DUP-004")
    @property
    def vat_rate_correct(self):      return self._rule_passed("VAT-001")
    @property
    def vat_calculation_correct(self): return self._rule_passed("VAT-002")
    @property
    def vat_number_present(self):    return self._rule_passed("VAT-004")
    @property
    def qr_code_valid(self):         return self._rule_passed("VAT-005")
    @property
    def has_cost_center(self):       return self._rule_passed("CTL-001")
    @property
    def has_account_code(self):      return self._rule_passed("CTL-002")
    @property
    def document_is_clear(self):     return self._rule_passed("DOC-001")
    @property
    def appears_genuine(self):       return self._rule_passed("DOC-002")
    @property
    def no_alterations(self):        return self._rule_passed("DOC-003")
    @property
    def has_qr_code(self):           return self._rule_passed("DOC-004")


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

class OverrideRequest(models.Model):
    """Pending two-approver override on a high-value invoice (F-2).

    The InvoiceApproveView's Golden-Rule override path was previously
    single-approver. For invoices at/above ``APPROVAL_OVERRIDE_THRESHOLD_SAR``
    the override now needs a second admin to countersign within the
    configured window (default 24h), else the row auto-expires and
    the invoice stays BLOCKED.

    Policy helpers live in
    ``apps.invoices.services.multi_approver`` — this is the persistence
    surface only.
    """
    class Status(models.TextChoices):
        PENDING       = "pending",       "Pending countersign"
        COUNTERSIGNED = "countersigned", "Countersigned"
        EXPIRED       = "expired",       "Expired"
        WITHDRAWN     = "withdrawn",     "Withdrawn"

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="approval_override_requests",
    )
    invoice      = models.ForeignKey(
        "invoices.Invoice", on_delete=models.CASCADE,
        related_name="override_requests",
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name="override_requests_made",
    )
    countersigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="override_requests_countersigned",
    )
    reason       = models.TextField()
    amount       = models.DecimalField(max_digits=18, decimal_places=2)
    threshold    = models.DecimalField(max_digits=18, decimal_places=2)
    status       = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
        db_index=True,
    )
    expires_at   = models.DateTimeField()
    created_at   = models.DateTimeField(auto_now_add=True)
    countersigned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["invoice", "status"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"Override {self.invoice_id} {self.amount} ({self.status})"

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone
        return self.status == self.Status.PENDING and self.expires_at < timezone.now()


class InvoiceAuditEvent(HashChainMixin):
    """Every action on an invoice is recorded here (Rule Group 8).

    Tamper-evident via the per-org SHA-256 chain inherited from
    HashChainMixin. After save, ``previous_hash``/``event_hash``/
    ``chain_position`` are immutable — a pre-save signal blocks any
    re-hash, and `verify_chain()` flags any row mutated outside the app.
    """

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
        DELETED     = "deleted",     "Deleted (Soft)"

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
        indexes = [
            models.Index(fields=["invoice", "chain_position"]),
        ]

    def __str__(self):
        return f"{self.event_type} on {self.invoice_id} by {self.user} at {self.timestamp}"

    # ── HashChainMixin contract ──────────────────────────────────────────────

    @classmethod
    def _chain_org_filter_key(cls) -> str:
        """Tell the chain framework how to filter rows by org — InvoiceAuditEvent
        reaches the org via invoice → organization."""
        return "invoice__organization_id"

    def _chain_organization_id(self):
        """Return the org id this event belongs to."""
        if self.invoice_id:
            return self.invoice.organization_id
        return None

    def _chain_payload(self) -> dict:
        """Canonical immutable snapshot the hash commits to. Any post-save
        edit to these fields would be detected by `verify_chain()`.

        Note: ``timestamp`` is *not* included. Django's ``auto_now_add``
        populates it inside the field-level pre_save, which fires AFTER our
        chain pre_save signal — so the value is None at the moment we hash.
        Including it would force us to choose between (a) hashing on a
        wallclock that drifts from the auto-populated field, breaking
        determinism, or (b) hand-rolling the timestamp ourselves and
        ignoring auto_now_add. We keep `timestamp` as a UI-only field and
        commit only to the immutable payload below — pk + chain_position
        already encode order.
        """
        return {
            "id":          str(self.id),
            "invoice_id":  str(self.invoice_id),
            "user_id":     str(self.user_id) if self.user_id else None,
            "event_type":  self.event_type,
            "description": self.description or "",
            "before_data": self.before_data or {},
            "after_data":  self.after_data or {},
            "ip_address":  self.ip_address or "",
        }
