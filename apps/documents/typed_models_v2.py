"""
Typed Financial Document Models — Phase 2 additions (10 new types)
====================================================================
Adds first-class models for the document types not yet in the system:

  SalesOrder         → أمر البيع
  Quotation          → عرض السعر
  ProformaInvoice    → فاتورة مبدئية
  ReceiptVoucher     → سند قبض
  CashVoucher        → سند نقدي
  GeneralLedger      → دفتر الأستاذ العام
  Ledger             → دفتر الأستاذ
  Contract           → عقد
  SupplierStatement  → كشف المورد
  CustomerStatement  → كشف العميل

Every model inherits `AuditMixin` so the rule engine, multi-doc adapter,
findings register and AI insights pipeline pick them up automatically with
zero code changes elsewhere.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.authentication.models import User
from .typed_models import AuditMixin


# ──────────────────────────────────────────────────────────────────────────────
# 1. Sales Order — أمر البيع
# ──────────────────────────────────────────────────────────────────────────────
class SalesOrder(AuditMixin):
    """
    أوامر البيع — Sales Orders
    Rules: SO-001 to SO-010
    """
    class Status(models.TextChoices):
        DRAFT     = "draft",     "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        FULFILLED = "fulfilled", "Fulfilled"
        CANCELLED = "cancelled", "Cancelled"

    # Header
    so_number          = models.CharField(max_length=100, blank=True, db_index=True)
    so_date            = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    customer_name      = models.CharField(max_length=255, blank=True)
    customer_vat_number = models.CharField(max_length=20, blank=True)
    customer_id_number = models.CharField(max_length=50, blank=True)
    department         = models.CharField(max_length=100, blank=True)
    status             = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # Financials
    currency           = models.CharField(max_length=3, default="SAR")
    subtotal           = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount    = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    vat_amount         = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    line_items         = models.JSONField(default=list)

    # Credit + linkage
    customer_credit_limit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    customer_outstanding  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    linked_invoice_id     = models.UUIDField(null=True, blank=True)
    linked_quotation_id   = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "sales_orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "so_date"]),
            models.Index(fields=["customer_name"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"SO {self.so_number} — {self.customer_name}"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Quotation — عرض السعر
# ──────────────────────────────────────────────────────────────────────────────
class Quotation(AuditMixin):
    """
    عروض الأسعار — Quotations
    Rules: QT-001 to QT-010
    """
    class PartyType(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        SUPPLIER = "supplier", "Supplier"

    class Status(models.TextChoices):
        DRAFT     = "draft",     "Draft"
        SENT      = "sent",      "Sent"
        ACCEPTED  = "accepted",  "Accepted"
        REJECTED  = "rejected",  "Rejected"
        EXPIRED   = "expired",   "Expired"
        CONVERTED = "converted", "Converted to Order"

    # Header
    quotation_number   = models.CharField(max_length=100, blank=True, db_index=True)
    quotation_date     = models.DateField(null=True, blank=True)
    expiry_date        = models.DateField(null=True, blank=True)
    party_type         = models.CharField(max_length=10, choices=PartyType.choices, default=PartyType.CUSTOMER)
    party_name         = models.CharField(max_length=255, blank=True)
    party_vat_number   = models.CharField(max_length=20, blank=True)
    status             = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # Financials
    currency           = models.CharField(max_length=3, default="SAR")
    subtotal           = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_pct       = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount    = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    vat_amount         = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    line_items         = models.JSONField(default=list)

    # Conversion tracking
    converted_to_order_id = models.UUIDField(null=True, blank=True)
    converted_to_invoice_id = models.UUIDField(null=True, blank=True)
    is_expired         = models.BooleanField(default=False)

    class Meta:
        db_table = "quotations"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "quotation_date"]),
            models.Index(fields=["party_name"]),
            models.Index(fields=["status"]),
            models.Index(fields=["expiry_date"]),
        ]

    def __str__(self):
        return f"Quote {self.quotation_number} — {self.party_name}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Proforma Invoice — فاتورة مبدئية
# ──────────────────────────────────────────────────────────────────────────────
class ProformaInvoice(AuditMixin):
    """
    الفواتير المبدئية — Proforma Invoices
    Rules: PF-001 to PF-010
    """
    class Status(models.TextChoices):
        DRAFT     = "draft",     "Draft"
        SENT      = "sent",      "Sent"
        ACCEPTED  = "accepted",  "Accepted"
        EXPIRED   = "expired",   "Expired"
        CONVERTED = "converted", "Converted to Tax Invoice"

    # Header
    proforma_number    = models.CharField(max_length=100, blank=True, db_index=True)
    proforma_date      = models.DateField(null=True, blank=True)
    validity_date      = models.DateField(null=True, blank=True)
    customer_name      = models.CharField(max_length=255, blank=True)
    customer_vat_number = models.CharField(max_length=20, blank=True)
    status             = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # Financials
    currency           = models.CharField(max_length=3, default="SAR")
    subtotal           = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    vat_amount         = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    line_items         = models.JSONField(default=list)

    # Conversion to real (tax) invoice
    is_marked_proforma = models.BooleanField(default=True, help_text="Document explicitly labelled as Proforma")
    converted_invoice_id = models.UUIDField(null=True, blank=True)
    converted_at       = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "proforma_invoices"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "proforma_date"]),
            models.Index(fields=["customer_name"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Proforma {self.proforma_number} — {self.customer_name}"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Receipt Voucher — سند قبض
# ──────────────────────────────────────────────────────────────────────────────
class ReceiptVoucher(AuditMixin):
    """
    سندات القبض — Receipt Vouchers
    Rules: RV-001 to RV-010
    """
    class Method(models.TextChoices):
        CASH    = "cash",    "Cash"
        BANK    = "bank",    "Bank Transfer"
        CHEQUE  = "cheque",  "Cheque"
        ONLINE  = "online",  "Online"
        OTHER   = "other",   "Other"

    # Header
    receipt_number      = models.CharField(max_length=100, blank=True, db_index=True)
    receipt_date        = models.DateField(null=True, blank=True)
    payer_name          = models.CharField(max_length=255, blank=True)
    payer_vat_number    = models.CharField(max_length=20, blank=True)
    receipt_method      = models.CharField(max_length=20, choices=Method.choices, default=Method.BANK)
    currency            = models.CharField(max_length=3, default="SAR")

    # Amount
    amount              = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # References
    linked_invoice_number = models.CharField(max_length=100, blank=True)
    linked_invoice_id     = models.UUIDField(null=True, blank=True)
    bank_reference        = models.CharField(max_length=100, blank=True)
    cheque_number         = models.CharField(max_length=50, blank=True)

    # Reconciliation flags
    is_reconciled       = models.BooleanField(default=False)
    bank_match_id       = models.UUIDField(null=True, blank=True)
    is_duplicate        = models.BooleanField(default=False)
    variance_vs_invoice = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = "receipt_vouchers"
        ordering = ["-receipt_date"]
        indexes = [
            models.Index(fields=["organization", "receipt_date"]),
            models.Index(fields=["payer_name"]),
            models.Index(fields=["receipt_method"]),
            models.Index(fields=["is_duplicate"]),
        ]

    def __str__(self):
        return f"Receipt {self.receipt_number} — {self.payer_name}"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Cash Voucher — سند نقدي
# ──────────────────────────────────────────────────────────────────────────────
class CashVoucher(AuditMixin):
    """
    السندات النقدية — Cash Vouchers
    Rules: CV-001 to CV-010
    """
    class MovementType(models.TextChoices):
        IN   = "in",  "Cash In (Receipt)"
        OUT  = "out", "Cash Out (Payment)"

    # Header
    voucher_number     = models.CharField(max_length=100, blank=True, db_index=True)
    voucher_date       = models.DateField(null=True, blank=True)
    movement_type      = models.CharField(max_length=10, choices=MovementType.choices, default=MovementType.OUT)
    counterparty_name  = models.CharField(max_length=255, blank=True)
    reason             = models.TextField(blank=True)
    currency           = models.CharField(max_length=3, default="SAR")

    # Amount
    amount             = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # Approval + control
    has_attachment     = models.BooleanField(default=False)
    requires_approval  = models.BooleanField(default=False)
    approval_status    = models.CharField(max_length=20, default="pending")
    approved_by        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_cash_vouchers")
    cashbox_balance_after = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    is_duplicate       = models.BooleanField(default=False)

    class Meta:
        db_table = "cash_vouchers"
        ordering = ["-voucher_date"]
        indexes = [
            models.Index(fields=["organization", "voucher_date"]),
            models.Index(fields=["movement_type"]),
            models.Index(fields=["is_duplicate"]),
        ]

    def __str__(self):
        return f"Cash {self.movement_type} {self.voucher_number} — {self.amount}"


# ──────────────────────────────────────────────────────────────────────────────
# 6. General Ledger — دفتر الأستاذ العام
# ──────────────────────────────────────────────────────────────────────────────
class GeneralLedger(AuditMixin):
    """
    دفتر الأستاذ العام — General Ledger snapshot for a period.
    Rules: GL-001 to GL-012
    """
    period_from        = models.DateField(null=True, blank=True)
    period_to          = models.DateField(null=True, blank=True)
    fiscal_year        = models.CharField(max_length=20, blank=True)

    # Aggregate totals across the entire ledger
    total_debit        = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_credit       = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    accounts_count     = models.PositiveIntegerField(default=0)
    movements_count    = models.PositiveIntegerField(default=0)

    # JSON breakdowns
    accounts           = models.JSONField(default=list, help_text="[{account_code, account_name, opening, debit, credit, closing}]")
    abnormal_balances  = models.JSONField(default=list)
    rollforward_variances = models.JSONField(default=list)

    is_balanced        = models.BooleanField(default=False, help_text="Total debit equals total credit")

    class Meta:
        db_table = "general_ledgers"
        ordering = ["-period_to"]
        indexes = [
            models.Index(fields=["organization", "period_to"]),
            models.Index(fields=["fiscal_year"]),
        ]

    def __str__(self):
        return f"GL {self.fiscal_year} ({self.period_from} → {self.period_to})"


# ──────────────────────────────────────────────────────────────────────────────
# 7. Ledger — دفتر الأستاذ (account-level)
# ──────────────────────────────────────────────────────────────────────────────
class Ledger(AuditMixin):
    """
    دفتر الأستاذ — single-account ledger.
    Rules: LDG-001 to LDG-010
    """
    account_number     = models.CharField(max_length=50, blank=True, db_index=True)
    account_name       = models.CharField(max_length=255, blank=True)
    account_type       = models.CharField(max_length=50, blank=True, help_text="Asset / Liability / Equity / Revenue / Expense")
    period_from        = models.DateField(null=True, blank=True)
    period_to          = models.DateField(null=True, blank=True)
    currency           = models.CharField(max_length=3, default="SAR")

    # Balances
    opening_balance    = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    closing_balance    = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_debit        = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_credit       = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    # Movements
    movements          = models.JSONField(default=list, help_text="[{date, ref, description, debit, credit, balance}]")
    movements_count    = models.PositiveIntegerField(default=0)

    # Health flags
    has_negative_balance = models.BooleanField(default=False)
    closing_balance_correct = models.BooleanField(default=True)

    class Meta:
        db_table = "ledgers"
        ordering = ["-period_to"]
        indexes = [
            models.Index(fields=["organization", "account_number"]),
            models.Index(fields=["period_to"]),
        ]

    def __str__(self):
        return f"Ledger {self.account_number} — {self.account_name}"


# ──────────────────────────────────────────────────────────────────────────────
# 8. Contract — عقد
# ──────────────────────────────────────────────────────────────────────────────
class Contract(AuditMixin):
    """
    العقود — Contracts.
    Rules: CTR-001 to CTR-013
    """
    class Status(models.TextChoices):
        DRAFT      = "draft",      "Draft"
        ACTIVE     = "active",     "Active"
        EXPIRED    = "expired",    "Expired"
        TERMINATED = "terminated", "Terminated"
        SUSPENDED  = "suspended",  "Suspended"

    contract_number    = models.CharField(max_length=100, blank=True, db_index=True)
    title              = models.CharField(max_length=255, blank=True)
    party_a            = models.CharField(max_length=255, blank=True, help_text="Our organisation, usually")
    party_b            = models.CharField(max_length=255, blank=True, help_text="Counter-party (vendor/customer)")
    party_b_type       = models.CharField(max_length=20, blank=True, help_text="vendor / customer")
    party_b_vat_number = models.CharField(max_length=20, blank=True)
    start_date         = models.DateField(null=True, blank=True)
    end_date           = models.DateField(null=True, blank=True)
    signing_date       = models.DateField(null=True, blank=True)
    is_signed          = models.BooleanField(default=False)
    status             = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # Financials
    currency           = models.CharField(max_length=3, default="SAR")
    contract_value     = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    invoiced_to_date   = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    payment_terms      = models.TextField(blank=True)

    # Linkage / control
    has_attachment     = models.BooleanField(default=False)
    value_modifications = models.JSONField(default=list, help_text="[{date, old_value, new_value, approver}]")
    related_invoices    = models.JSONField(default=list, help_text="List of invoice IDs invoiced under this contract")

    class Meta:
        db_table = "contracts"
        ordering = ["-start_date"]
        indexes = [
            models.Index(fields=["organization", "start_date"]),
            models.Index(fields=["party_b"]),
            models.Index(fields=["status"]),
            models.Index(fields=["contract_number"]),
        ]

    def __str__(self):
        return f"Contract {self.contract_number} — {self.party_b}"


# ──────────────────────────────────────────────────────────────────────────────
# 9. Supplier Statement — كشف المورد
# ──────────────────────────────────────────────────────────────────────────────
class SupplierStatement(AuditMixin):
    """
    كشوف الموردين — Supplier Statements (vendor's view of our account).
    Rules: SS-001 to SS-012
    """
    supplier_name      = models.CharField(max_length=255, blank=True)
    supplier_id        = models.CharField(max_length=50, blank=True)
    supplier_vat_number = models.CharField(max_length=20, blank=True)
    period_from        = models.DateField(null=True, blank=True)
    period_to          = models.DateField(null=True, blank=True)
    currency           = models.CharField(max_length=3, default="SAR")

    # Balances
    opening_balance    = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    closing_balance    = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_invoiced     = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_paid         = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    # Movements
    movements          = models.JSONField(default=list)

    # Reconciliation results
    invoices_matched   = models.PositiveIntegerField(default=0)
    invoices_missing_in_system = models.JSONField(default=list)
    payments_missing_on_statement = models.JSONField(default=list)
    balance_variance   = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    duplicate_count    = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "supplier_statements"
        ordering = ["-period_to"]
        indexes = [
            models.Index(fields=["organization", "period_to"]),
            models.Index(fields=["supplier_name"]),
        ]

    def __str__(self):
        return f"Supplier Statement {self.supplier_name} ({self.period_from}–{self.period_to})"


# ──────────────────────────────────────────────────────────────────────────────
# 10. Customer Statement — كشف العميل
# ──────────────────────────────────────────────────────────────────────────────
class CustomerStatement(AuditMixin):
    """
    كشوف العملاء — Customer Statements (our AR view per customer).
    Rules: CS-001 to CS-012
    """
    customer_name      = models.CharField(max_length=255, blank=True)
    customer_id        = models.CharField(max_length=50, blank=True)
    customer_vat_number = models.CharField(max_length=20, blank=True)
    period_from        = models.DateField(null=True, blank=True)
    period_to          = models.DateField(null=True, blank=True)
    currency           = models.CharField(max_length=3, default="SAR")

    # Balances
    opening_balance    = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    closing_balance    = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_invoiced     = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_received     = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    # Movements
    movements          = models.JSONField(default=list)

    # Reconciliation
    invoices_matched   = models.PositiveIntegerField(default=0)
    invoices_missing_in_system = models.JSONField(default=list)
    receipts_missing_on_statement = models.JSONField(default=list)
    balance_variance   = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    duplicate_count    = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "customer_statements"
        ordering = ["-period_to"]
        indexes = [
            models.Index(fields=["organization", "period_to"]),
            models.Index(fields=["customer_name"]),
        ]

    def __str__(self):
        return f"Customer Statement {self.customer_name} ({self.period_from}–{self.period_to})"


# ──────────────────────────────────────────────────────────────────────────────
# Registration in DOCUMENT_TYPE_MAP — extend the existing map.
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# 11. Journal Entry — قيد يومية
# ──────────────────────────────────────────────────────────────────────────────
class JournalEntry(AuditMixin):
    """
    قيود اليومية — Journal Entries
    Rules: JE-001 to JE-014
    """
    class ApprovalStatus(models.TextChoices):
        PENDING  = "pending",  "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    # Header
    entry_number       = models.CharField(max_length=100, blank=True, db_index=True)
    entry_date         = models.DateField(null=True, blank=True)
    description        = models.TextField(blank=True)
    fiscal_period      = models.CharField(max_length=20, blank=True)
    currency           = models.CharField(max_length=3, default="SAR")

    # Totals (debits must equal credits)
    total_debit        = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_credit       = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    lines_count        = models.PositiveIntegerField(default=0)
    is_balanced        = models.BooleanField(default=False)

    # Lines: [{account_code, account_name, debit, credit, description}]
    lines              = models.JSONField(default=list)

    # Control flags
    is_manual          = models.BooleanField(default=True, help_text="True if entered manually vs imported")
    has_attachment     = models.BooleanField(default=False)
    is_period_close    = models.BooleanField(default=False, help_text="Posted at period-end")
    approval_status    = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING,
    )
    approved_by        = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_journal_entries",
    )

    class Meta:
        # Distinct from apps.transactions.JournalEntry which models the
        # in-system double-entry posting; this Phase-2 model represents an
        # *uploaded* journal-entry document that's been extracted, audited,
        # and stored alongside other typed source documents.
        db_table = "journal_entry_documents"
        ordering = ["-entry_date"]
        indexes = [
            models.Index(fields=["organization", "entry_date"]),
            models.Index(fields=["entry_number"]),
            models.Index(fields=["is_balanced"]),
        ]

    def __str__(self):
        return f"JE {self.entry_number} ({self.entry_date})"


PHASE2_DOCUMENT_TYPE_MAP = {
    "sales_order":        SalesOrder,
    "quotation":          Quotation,
    "proforma_invoice":   ProformaInvoice,
    "receipt_voucher":    ReceiptVoucher,
    "cash_voucher":       CashVoucher,
    "general_ledger":     GeneralLedger,
    "ledger":             Ledger,
    "contract":           Contract,
    "supplier_statement": SupplierStatement,
    "customer_statement": CustomerStatement,
    "journal_entry":      JournalEntry,
}

PHASE2_DOCUMENT_TYPE_LABELS = {
    "sales_order":        _("Sales Order"),
    "quotation":          _("Quotation"),
    "proforma_invoice":   _("Proforma Invoice"),
    "receipt_voucher":    _("Receipt Voucher"),
    "cash_voucher":       _("Cash Voucher"),
    "general_ledger":     _("General Ledger"),
    "ledger":             _("Ledger"),
    "contract":           _("Contract"),
    "supplier_statement": _("Supplier Statement"),
    "customer_statement": _("Customer Statement"),
    "journal_entry":      _("Journal Entry"),
}
