"""
Typed Financial Document Models
================================
Extends the base Document model with type-specific structured fields.
Each document type maps to one of the 8 sample data categories.

Types:
  PurchaseOrder   → أوامر الشراء
  BankStatement   → كشوف الحساب البنكي
  PayrollSheet    → كشوف الرواتب
  ExpenseReport   → تقارير المصروفات
  VATReturn       → الإقرارات الضريبية
  FixedAssetLedger→ سجل الأصول الثابتة
  SalesReceipt    → إيصالات البيع
"""

import uuid
from decimal import Decimal
from django.db import models
from apps.authentication.models import User, Organization
from .models import Document


# ──────────────────────────────────────────────────────────────────────────────
# Shared audit mixin
# ──────────────────────────────────────────────────────────────────────────────

class AuditMixin(models.Model):
    """Common audit fields shared by all typed document records."""

    class AuditStatus(models.TextChoices):
        PENDING   = "pending",   "Pending"
        VALIDATED = "validated", "Validated"
        FLAGGED   = "flagged",   "Flagged"
        APPROVED  = "approved",  "Approved"
        REJECTED  = "rejected",  "Rejected"

    class RiskLevel(models.TextChoices):
        LOW      = "low",      "Low"
        MEDIUM   = "medium",   "Medium"
        HIGH     = "high",     "High"
        CRITICAL = "critical", "Critical"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization    = models.ForeignKey(Organization, on_delete=models.CASCADE)
    document        = models.OneToOneField(Document, on_delete=models.CASCADE, null=False, blank=False)
    uploaded_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    audit_status    = models.CharField(max_length=20, choices=AuditStatus.choices, default=AuditStatus.PENDING)
    risk_level      = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.LOW)
    validation_score= models.FloatField(default=0.0, help_text="0-100 weighted score")
    rules_passed    = models.PositiveIntegerField(default=0)
    rules_failed    = models.PositiveIntegerField(default=0)
    failed_rule_codes = models.JSONField(default=list)
    validation_details= models.JSONField(default=list)
    ai_summary      = models.TextField(blank=True)
    ai_recommendations = models.JSONField(default=list)
    anomalies_found = models.JSONField(default=list, help_text="List of detected anomalies")
    notes           = models.TextField(blank=True)
    reviewed_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ──────────────────────────────────────────────────────────────────────────────
# 1. Purchase Order  — أمر الشراء
# ──────────────────────────────────────────────────────────────────────────────

class PurchaseOrder(AuditMixin):
    """
    أوامر الشراء — Purchase Orders
    Rules: PO-001 to PO-010
    """

    class ApprovalStatus(models.TextChoices):
        DRAFT     = "draft",     "Draft"
        PENDING   = "pending",   "Pending Approval"
        APPROVED  = "approved",  "Approved"
        REJECTED  = "rejected",  "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        RECEIVED  = "received",  "Received"

    # ── Header fields ──
    po_number         = models.CharField(max_length=100, blank=True, db_index=True)
    po_date           = models.DateField(null=True, blank=True)
    delivery_date     = models.DateField(null=True, blank=True)
    vendor_name       = models.CharField(max_length=255, blank=True)
    vendor_vat_number = models.CharField(max_length=20, blank=True)
    vendor_cr_number  = models.CharField(max_length=20, blank=True)
    requester_name    = models.CharField(max_length=255, blank=True)
    department        = models.CharField(max_length=100, blank=True)
    cost_center       = models.CharField(max_length=50, blank=True)
    account_code      = models.CharField(max_length=50, blank=True)
    approval_status   = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    approved_by       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_pos")

    # ── Financials ──
    currency          = models.CharField(max_length=3, default="SAR")
    subtotal          = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    vat_amount        = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount      = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    budget_limit      = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    line_items        = models.JSONField(default=list, help_text="[{description, qty, unit_price, total}]")

    # ── Matching ──
    linked_invoice_id = models.UUIDField(null=True, blank=True, help_text="Linked Invoice UUID if matched")
    has_price_discrepancy = models.BooleanField(default=False)
    price_discrepancy_pct = models.FloatField(default=0.0)
    quantity_mismatch = models.BooleanField(default=False)

    class Meta:
        db_table = "purchase_orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "po_date"]),
            models.Index(fields=["vendor_name"]),
            models.Index(fields=["approval_status"]),
        ]

    def __str__(self):
        return f"PO {self.po_number} — {self.vendor_name}"


class PurchaseOrderValidation(models.Model):
    """Rule-level pass/fail flags for a Purchase Order."""
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po             = models.OneToOneField(PurchaseOrder, on_delete=models.CASCADE, related_name="validation")
    # PO-001 to PO-010
    has_po_number      = models.BooleanField(default=True)
    has_po_date        = models.BooleanField(default=True)
    has_vendor_name    = models.BooleanField(default=True)
    has_vendor_vat     = models.BooleanField(default=True)
    vat_calculation_ok = models.BooleanField(default=True)
    within_budget      = models.BooleanField(default=True)
    has_approver       = models.BooleanField(default=True)
    no_price_discrepancy  = models.BooleanField(default=True)
    no_quantity_mismatch  = models.BooleanField(default=True)
    has_cost_center    = models.BooleanField(default=True)
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "purchase_order_validations"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Bank Statement  — كشف الحساب البنكي
# ──────────────────────────────────────────────────────────────────────────────

class BankStatement(AuditMixin):
    """
    كشوف الحساب البنكي — Bank Statements
    Rules: BNK-001 to BNK-009
    """

    # ── Header ──
    bank_name         = models.CharField(max_length=255, blank=True)
    account_number    = models.CharField(max_length=50, blank=True, db_index=True)
    account_name      = models.CharField(max_length=255, blank=True)
    iban              = models.CharField(max_length=34, blank=True)
    currency          = models.CharField(max_length=3, default="SAR")
    statement_period_from = models.DateField(null=True, blank=True)
    statement_period_to   = models.DateField(null=True, blank=True)

    # ── Balances ──
    opening_balance   = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    closing_balance   = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_credits     = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_debits      = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    calculated_closing= models.DecimalField(max_digits=18, decimal_places=2, default=0,
                                             help_text="opening + credits - debits")
    balance_matches   = models.BooleanField(default=True)
    transaction_count = models.PositiveIntegerField(default=0)

    # ── Transactions (JSON) ──
    transactions      = models.JSONField(default=list,
                                          help_text="[{date, description, debit, credit, balance, ref}]")

    # ── Anomaly flags ──
    large_tx_count    = models.PositiveIntegerField(default=0, help_text="Transactions > 3× avg")
    round_amount_count= models.PositiveIntegerField(default=0, help_text="Round-number transactions")
    benford_deviation = models.FloatField(default=0.0, help_text="MAD from Benford's Law expected")
    duplicate_tx_count= models.PositiveIntegerField(default=0)
    weekend_tx_count  = models.PositiveIntegerField(default=0)
    late_night_tx_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "bank_statements"
        ordering = ["-statement_period_to"]
        indexes = [
            models.Index(fields=["organization", "statement_period_from"]),
            models.Index(fields=["account_number"]),
        ]

    def __str__(self):
        return f"{self.bank_name} — {self.account_number} ({self.statement_period_from})"


class BankStatementValidation(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    statement     = models.OneToOneField(BankStatement, on_delete=models.CASCADE, related_name="validation")
    balance_reconciled   = models.BooleanField(default=True)  # BNK-001
    no_large_transactions= models.BooleanField(default=True)  # BNK-002
    no_duplicate_transactions = models.BooleanField(default=True) # BNK-003
    benford_law_ok       = models.BooleanField(default=True)  # BNK-004
    no_round_amounts     = models.BooleanField(default=True)  # BNK-005
    no_weekend_transactions = models.BooleanField(default=True) # BNK-006
    account_number_present  = models.BooleanField(default=True) # BNK-007
    period_complete      = models.BooleanField(default=True)  # BNK-008
    iban_valid           = models.BooleanField(default=True)  # BNK-009
    created_at           = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bank_statement_validations"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Payroll Sheet  — كشف الرواتب
# ──────────────────────────────────────────────────────────────────────────────

class PayrollSheet(AuditMixin):
    """
    كشوف الرواتب — Payroll
    Rules: PAY-001 to PAY-009
    """

    # ── Header ──
    payroll_period_from = models.DateField(null=True, blank=True)
    payroll_period_to   = models.DateField(null=True, blank=True)
    department          = models.CharField(max_length=100, blank=True)
    company_name        = models.CharField(max_length=255, blank=True)
    payment_date        = models.DateField(null=True, blank=True)
    currency            = models.CharField(max_length=3, default="SAR")

    # ── Totals ──
    employee_count      = models.PositiveIntegerField(default=0)
    total_gross_salary  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_allowances    = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_deductions    = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_gosi          = models.DecimalField(max_digits=18, decimal_places=2, default=0,
                                               help_text="GOSI / Social insurance")
    total_net_salary    = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Employee records (JSON) ──
    employees = models.JSONField(default=list,
                                  help_text="[{id, name, gross, allowances, deductions, gosi, net, bank_account}]")

    # ── Anomaly flags ──
    duplicate_employee_ids = models.JSONField(default=list, help_text="Duplicate national IDs found")
    ghost_employee_flags   = models.JSONField(default=list, help_text="Suspected ghost employees")
    salary_spike_flags     = models.JSONField(default=list, help_text="Employees with >30% salary increase")
    calculation_errors     = models.JSONField(default=list, help_text="gross - deductions ≠ net")
    missing_gosi_count     = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "payroll_sheets"
        ordering = ["-payroll_period_to"]
        indexes = [
            models.Index(fields=["organization", "payroll_period_from"]),
            models.Index(fields=["department"]),
        ]

    def __str__(self):
        return f"Payroll {self.payroll_period_from} — {self.payroll_period_to} ({self.employee_count} employees)"


class PayrollValidation(models.Model):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payroll        = models.OneToOneField(PayrollSheet, on_delete=models.CASCADE, related_name="validation")
    no_duplicate_ids        = models.BooleanField(default=True)  # PAY-001
    no_ghost_employees      = models.BooleanField(default=True)  # PAY-002
    net_calculation_correct = models.BooleanField(default=True)  # PAY-003
    gosi_present            = models.BooleanField(default=True)  # PAY-004
    no_salary_spikes        = models.BooleanField(default=True)  # PAY-005
    has_bank_accounts       = models.BooleanField(default=True)  # PAY-006
    period_valid            = models.BooleanField(default=True)  # PAY-007
    totals_match            = models.BooleanField(default=True)  # PAY-008
    employee_count_consistent = models.BooleanField(default=True) # PAY-009
    created_at              = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payroll_validations"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Expense Report  — تقرير المصروفات
# ──────────────────────────────────────────────────────────────────────────────

class ExpenseReport(AuditMixin):
    """
    تقارير المصروفات — Expense Reports
    Rules: EXP-001 to EXP-008
    """

    class ExpenseCategory(models.TextChoices):
        TRAVEL      = "travel",      "Travel"
        ACCOMMODATION= "accommodation", "Accommodation"
        MEALS       = "meals",       "Meals & Entertainment"
        OFFICE      = "office",      "Office Supplies"
        COMMUNICATION="communication","Communication"
        TRAINING    = "training",    "Training"
        MAINTENANCE = "maintenance", "Maintenance"
        OTHER       = "other",       "Other"

    # ── Header ──
    report_number       = models.CharField(max_length=100, blank=True, db_index=True)
    employee_name       = models.CharField(max_length=255, blank=True)
    employee_id         = models.CharField(max_length=50, blank=True)
    department          = models.CharField(max_length=100, blank=True)
    report_period_from  = models.DateField(null=True, blank=True)
    report_period_to    = models.DateField(null=True, blank=True)
    submitted_date      = models.DateField(null=True, blank=True)
    approved_by         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_expenses")
    currency            = models.CharField(max_length=3, default="SAR")
    purpose             = models.TextField(blank=True)

    # ── Totals ──
    total_claimed       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_approved      = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_rejected      = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    vat_included        = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Line items (JSON) ──
    expense_lines = models.JSONField(default=list,
                                     help_text="[{date, category, description, amount, receipt_attached, receipt_number}]")

    # ── Anomaly flags ──
    missing_receipts_count  = models.PositiveIntegerField(default=0)
    duplicate_claims        = models.JSONField(default=list)
    over_policy_limit_count = models.PositiveIntegerField(default=0)
    weekend_expense_count   = models.PositiveIntegerField(default=0)
    split_transaction_flags = models.JSONField(default=list, help_text="Possible split to avoid limits")

    class Meta:
        db_table = "expense_reports"
        ordering = ["-report_period_to"]
        indexes = [
            models.Index(fields=["organization", "submitted_date"]),
            models.Index(fields=["employee_name"]),
        ]

    def __str__(self):
        return f"Expense {self.report_number} — {self.employee_name}"


class ExpenseReportValidation(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report        = models.OneToOneField(ExpenseReport, on_delete=models.CASCADE, related_name="validation")
    all_receipts_attached   = models.BooleanField(default=True)  # EXP-001
    no_duplicate_claims     = models.BooleanField(default=True)  # EXP-002
    within_policy_limits    = models.BooleanField(default=True)  # EXP-003
    has_approver            = models.BooleanField(default=True)  # EXP-004
    no_split_transactions   = models.BooleanField(default=True)  # EXP-005
    valid_dates             = models.BooleanField(default=True)  # EXP-006
    vat_calculation_ok      = models.BooleanField(default=True)  # EXP-007
    totals_match            = models.BooleanField(default=True)  # EXP-008
    created_at              = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "expense_report_validations"


# ──────────────────────────────────────────────────────────────────────────────
# 5. VAT Return  — الإقرار الضريبي
# ──────────────────────────────────────────────────────────────────────────────

class VATReturn(AuditMixin):
    """
    الإقرارات الضريبية — VAT Returns (ZATCA)
    Rules: VATR-001 to VATR-008
    """

    class FilingStatus(models.TextChoices):
        DRAFT     = "draft",     "Draft"
        SUBMITTED = "submitted", "Submitted"
        ACCEPTED  = "accepted",  "Accepted by ZATCA"
        REJECTED  = "rejected",  "Rejected by ZATCA"
        AMENDED   = "amended",   "Amended"

    # ── Header ──
    taxpayer_name     = models.CharField(max_length=255, blank=True)
    vat_number        = models.CharField(max_length=20, blank=True, db_index=True)
    cr_number         = models.CharField(max_length=20, blank=True)
    period_from       = models.DateField(null=True, blank=True)
    period_to         = models.DateField(null=True, blank=True)
    filing_date       = models.DateField(null=True, blank=True)
    due_date          = models.DateField(null=True, blank=True)
    filing_status     = models.CharField(max_length=20, choices=FilingStatus.choices, default=FilingStatus.DRAFT)
    zatca_reference   = models.CharField(max_length=100, blank=True)

    # ── Box values ──
    standard_rated_sales        = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    zero_rated_sales            = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    exempt_sales                = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_sales                 = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    output_vat                  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    standard_rated_purchases    = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    input_vat                   = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_vat_payable             = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    vat_paid                    = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Calculated vs declared ──
    calculated_output_vat       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    calculated_input_vat        = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    calculated_net              = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    output_discrepancy          = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    input_discrepancy           = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    is_late_filing              = models.BooleanField(default=False)
    late_days                   = models.IntegerField(default=0)

    class Meta:
        db_table = "vat_returns"
        ordering = ["-period_to"]
        indexes = [
            models.Index(fields=["organization", "period_from"]),
            models.Index(fields=["vat_number"]),
            models.Index(fields=["filing_status"]),
        ]

    def __str__(self):
        return f"VAT Return {self.vat_number} ({self.period_from} – {self.period_to})"


class VATReturnValidation(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vat_return   = models.OneToOneField(VATReturn, on_delete=models.CASCADE, related_name="validation")
    vat_number_valid        = models.BooleanField(default=True)  # VATR-001
    output_vat_correct      = models.BooleanField(default=True)  # VATR-002
    input_vat_correct       = models.BooleanField(default=True)  # VATR-003
    net_vat_correct         = models.BooleanField(default=True)  # VATR-004
    no_output_discrepancy   = models.BooleanField(default=True)  # VATR-005
    no_input_discrepancy    = models.BooleanField(default=True)  # VATR-006
    filed_on_time           = models.BooleanField(default=True)  # VATR-007
    period_complete         = models.BooleanField(default=True)  # VATR-008
    created_at              = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vat_return_validations"


# ──────────────────────────────────────────────────────────────────────────────
# 6. Fixed Asset Ledger  — سجل الأصول الثابتة
# ──────────────────────────────────────────────────────────────────────────────

class FixedAsset(AuditMixin):
    """
    سجل الأصول الثابتة — Fixed Assets
    Rules: AST-001 to AST-009
    """

    class AssetCategory(models.TextChoices):
        LAND          = "land",          "Land"
        BUILDINGS     = "buildings",     "Buildings"
        VEHICLES      = "vehicles",      "Vehicles"
        EQUIPMENT     = "equipment",     "Equipment & Machinery"
        COMPUTERS     = "computers",     "Computers & IT"
        FURNITURE     = "furniture",     "Furniture & Fixtures"
        OTHER         = "other",         "Other"

    class DepreciationMethod(models.TextChoices):
        STRAIGHT_LINE = "straight_line", "Straight Line"
        DECLINING     = "declining",     "Declining Balance"
        UNITS         = "units",         "Units of Production"
        NONE          = "none",          "Not Depreciated"

    # ── Header (represents a register/ledger, multiple assets as JSON) ──
    register_date     = models.DateField(null=True, blank=True)
    company_name      = models.CharField(max_length=255, blank=True)
    department        = models.CharField(max_length=100, blank=True)
    fiscal_year       = models.CharField(max_length=9, blank=True, help_text="e.g. 2024")

    # ── Totals ──
    total_cost        = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_accumulated_depreciation = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_book_value  = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    asset_count       = models.PositiveIntegerField(default=0)

    # ── Asset records (JSON) ──
    assets = models.JSONField(default=list,
                               help_text="[{asset_id, name, category, purchase_date, cost, "
                                         "useful_life_years, method, annual_depreciation, "
                                         "accumulated_depreciation, book_value, is_fully_depreciated}]")

    # ── Anomaly flags ──
    negative_book_value_count  = models.PositiveIntegerField(default=0)
    over_depreciated_count     = models.PositiveIntegerField(default=0,
                                                               help_text="Accumulated > Cost")
    wrong_depreciation_rate    = models.JSONField(default=list)
    missing_asset_id_count     = models.PositiveIntegerField(default=0)
    duplicate_asset_id_count   = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "fixed_assets"
        ordering = ["-register_date"]
        indexes = [
            models.Index(fields=["organization", "fiscal_year"]),
            models.Index(fields=["department"]),
        ]

    def __str__(self):
        return f"Fixed Assets Register {self.fiscal_year} — {self.asset_count} assets"


class FixedAssetValidation(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset       = models.OneToOneField(FixedAsset, on_delete=models.CASCADE, related_name="validation")
    no_negative_book_values      = models.BooleanField(default=True)  # AST-001
    no_over_depreciation         = models.BooleanField(default=True)  # AST-002
    depreciation_rates_correct   = models.BooleanField(default=True)  # AST-003
    no_duplicate_asset_ids       = models.BooleanField(default=True)  # AST-004
    all_assets_have_ids          = models.BooleanField(default=True)  # AST-005
    book_value_calculation_ok    = models.BooleanField(default=True)  # AST-006
    useful_life_reasonable       = models.BooleanField(default=True)  # AST-007
    totals_consistent            = models.BooleanField(default=True)  # AST-008
    purchase_dates_valid         = models.BooleanField(default=True)  # AST-009
    created_at                   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fixed_asset_validations"


# ──────────────────────────────────────────────────────────────────────────────
# 7. Sales Receipt  — إيصال البيع
# ──────────────────────────────────────────────────────────────────────────────

class SalesReceipt(AuditMixin):
    """
    إيصالات البيع — Sales Receipts (ZATCA Phase 2 compliant)
    Rules: REC-001 to REC-008
    """

    class ReceiptType(models.TextChoices):
        STANDARD  = "standard",  "Standard Tax Invoice"
        SIMPLIFIED= "simplified","Simplified Tax Invoice"
        CREDIT    = "credit",    "Credit Note"
        DEBIT     = "debit",     "Debit Note"

    # ── Header ──
    receipt_number    = models.CharField(max_length=100, blank=True, db_index=True)
    receipt_date      = models.DateField(null=True, blank=True)
    receipt_type      = models.CharField(max_length=20, choices=ReceiptType.choices, default=ReceiptType.SIMPLIFIED)
    seller_name       = models.CharField(max_length=255, blank=True)
    seller_vat_number = models.CharField(max_length=20, blank=True)
    customer_name     = models.CharField(max_length=255, blank=True)
    customer_vat_number= models.CharField(max_length=20, blank=True)
    currency          = models.CharField(max_length=3, default="SAR")

    # ── Amounts ──
    subtotal          = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    vat_rate          = models.DecimalField(max_digits=5, decimal_places=2, default=15)
    vat_amount        = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount      = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    line_items        = models.JSONField(default=list)

    # ── ZATCA compliance ──
    has_qr_code       = models.BooleanField(default=False)
    qr_code_valid     = models.BooleanField(default=False)
    qr_code_data      = models.JSONField(default=dict, help_text="Decoded QR TLV fields")
    zatca_uuid        = models.CharField(max_length=50, blank=True)

    # ── Duplicate detection ──
    is_duplicate      = models.BooleanField(default=False)
    duplicate_of      = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)
    file_hash         = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        db_table = "sales_receipts"
        ordering = ["-receipt_date"]
        indexes = [
            models.Index(fields=["organization", "receipt_date"]),
            models.Index(fields=["seller_vat_number"]),
            models.Index(fields=["is_duplicate"]),
            models.Index(fields=["file_hash"]),
        ]

    def __str__(self):
        return f"Receipt {self.receipt_number} — {self.seller_name}"


class SalesReceiptValidation(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt     = models.OneToOneField(SalesReceipt, on_delete=models.CASCADE, related_name="validation")
    has_receipt_number      = models.BooleanField(default=True)  # REC-001
    has_receipt_date        = models.BooleanField(default=True)  # REC-002
    vat_rate_correct        = models.BooleanField(default=True)  # REC-003
    vat_calculation_correct = models.BooleanField(default=True)  # REC-004
    has_qr_code             = models.BooleanField(default=True)  # REC-005
    qr_code_valid           = models.BooleanField(default=True)  # REC-006
    no_duplicate            = models.BooleanField(default=True)  # REC-007
    seller_vat_present      = models.BooleanField(default=True)  # REC-008
    created_at              = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sales_receipt_validations"


# ──────────────────────────────────────────────────────────────────────────────
# Document type registry — used by upload router
# ──────────────────────────────────────────────────────────────────────────────

DOCUMENT_TYPE_MAP = {
    "purchase_order":  PurchaseOrder,
    "bank_statement":  BankStatement,
    "payroll":         PayrollSheet,
    "expense_report":  ExpenseReport,
    "vat_return":      VATReturn,
    "fixed_asset":     FixedAsset,
    "sales_receipt":   SalesReceipt,
    "invoice":         None,  # handled by apps/invoices
}

DOCUMENT_TYPE_LABELS_AR = {
    "purchase_order": "أمر الشراء",
    "bank_statement": "كشف الحساب البنكي",
    "payroll":        "كشف الرواتب",
    "expense_report": "تقرير المصروفات",
    "vat_return":     "الإقرار الضريبي",
    "fixed_asset":    "سجل الأصول الثابتة",
    "sales_receipt":  "إيصال البيع",
    "invoice":        "فاتورة",
}
