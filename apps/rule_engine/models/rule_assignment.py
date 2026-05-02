import uuid

from django.db import models

from apps.rule_engine.models.rule_definition import RuleDefinition, Severity


class SupportedDocumentType(models.TextChoices):
    """Canonical document types the rule engine can audit.

    Aliases (same business document, different naming):
      - `tax_return` ≡ `tax_vat_document` (kept for backward compatibility)
      - `payment`    ≡ `payment_voucher`
    """
    # ── Original (kept stable for existing data) ─────────────────────────
    SALES_INVOICE      = "sales_invoice",    "Sales Invoice"
    PURCHASE_ORDER     = "purchase_order",   "Purchase Order"
    BANK_STATEMENT     = "bank_statement",   "Bank Statement"
    PAYROLL            = "payroll",          "Payroll Sheet"
    EXPENSE            = "expense",          "Expense Report"
    EXPENSE_REPORT     = "expense_report",   "Expense Report"   # canonical alias
    TAX_RETURN         = "tax_return",       "VAT / Tax Return"
    FIXED_ASSET        = "fixed_asset",      "Fixed Asset Register"
    SALES_RECEIPT      = "sales_receipt",    "Sales Receipt"
    GRN                = "grn",              "Goods Receipt Note"
    PAYMENT            = "payment",          "Payment Voucher"
    PAYMENT_VOUCHER    = "payment_voucher",  "Payment Voucher"  # canonical alias

    # ── Phase-1 additions (10 new types) ────────────────────────────────
    PURCHASE_INVOICE   = "purchase_invoice", "Purchase Invoice"
    SALES_ORDER        = "sales_order",      "Sales Order"
    QUOTATION          = "quotation",        "Quotation"
    PROFORMA_INVOICE   = "proforma_invoice", "Proforma Invoice"
    RECEIPT_VOUCHER    = "receipt_voucher",  "Receipt Voucher"
    CASH_VOUCHER       = "cash_voucher",     "Cash Voucher"
    JOURNAL_ENTRY      = "journal_entry",    "Journal Entry"
    GENERAL_LEDGER     = "general_ledger",   "General Ledger"
    LEDGER             = "ledger",           "Ledger"
    CONTRACT           = "contract",         "Contract"
    SUPPLIER_STATEMENT = "supplier_statement","Supplier Statement"
    CUSTOMER_STATEMENT = "customer_statement","Customer Statement"
    TAX_VAT_DOCUMENT   = "tax_vat_document", "Tax / VAT Document"  # canonical alias

    OTHER              = "other",            "Other"


class ApplicabilityMode(models.TextChoices):
    FULL = "full", "Full"
    PARTIAL = "partial", "Partial"
    CONDITIONAL = "conditional", "Conditional"


class AssignmentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"
    DEPRECATED = "deprecated", "Deprecated"


class RuleAssignment(models.Model):
    """
    Binds a :model:`rule_engine.RuleDefinition` to a document type, optionally
    scoped to a single organisation.

    A NULL ``organization`` means the assignment is a system-level default that
    applies to **all** tenants unless overridden by a more specific assignment.

    Per-organisation overrides:
    - ``severity_override`` replaces the rule's default severity.
    - ``config_override`` is deep-merged on top of ``default_config``.
    - ``blocks_approval_override`` replaces the rule's flag.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    rule = models.ForeignKey(
        RuleDefinition,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    document_type = models.CharField(
        max_length=32,
        choices=SupportedDocumentType.choices,
        db_index=True,
    )
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rule_assignments",
        db_index=True,
        help_text=(
            "NULL = system default that applies to all organisations unless "
            "a more specific assignment exists for a given org."
        ),
    )

    # Applicability
    applicability = models.CharField(
        max_length=16,
        choices=ApplicabilityMode.choices,
        default=ApplicabilityMode.FULL,
    )
    condition_expression = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "JSONLogic expression evaluated at runtime against the normalised "
            "document payload. Rule is skipped when the expression evaluates "
            "to False."
        ),
    )

    # Lifecycle
    status = models.CharField(
        max_length=16,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ACTIVE,
    )
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)

    # Per-organisation overrides (all nullable — None means "use rule default")
    severity_override = models.CharField(
        max_length=16,
        choices=Severity.choices,
        null=True,
        blank=True,
    )
    config_override = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON object deep-merged on top of RuleDefinition.default_config.",
    )
    blocks_approval_override = models.BooleanField(
        null=True,
        blank=True,
        help_text=(
            "When set, overrides RuleDefinition.blocks_approval for this assignment."
        ),
    )

    # Audit trail
    created_by = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "re_rule_assignment"
        unique_together = (("rule", "document_type", "organization"),)
        indexes = [
            models.Index(
                fields=["document_type", "status"],
                name="re_assign_doctype_status_idx",
            ),
            models.Index(
                fields=["organization", "document_type"],
                name="re_assignment_org_doctype_idx",
            ),
        ]
        verbose_name = "Rule Assignment"
        verbose_name_plural = "Rule Assignments"

    def __str__(self) -> str:
        org_label = self.organization_id or "global"
        return f"{self.rule.rule_code} → {self.document_type} ({org_label})"

    # ------------------------------------------------------------------
    # Computed properties — resolve effective values considering overrides
    # ------------------------------------------------------------------

    @property
    def effective_severity(self) -> str:
        """Return the severity that will be recorded on AuditResult rows."""
        return self.severity_override or self.rule.default_severity

    @property
    def effective_blocks_approval(self) -> bool:
        """Return whether a failure on this assignment blocks document approval."""
        if self.blocks_approval_override is not None:
            return self.blocks_approval_override
        return self.rule.blocks_approval

    @property
    def effective_config(self) -> dict:
        """
        Return the merged configuration dictionary for this assignment.

        ``config_override`` keys are deep-merged on top of
        ``rule.default_config``.  Nested dicts are merged recursively;
        all other types are replaced.
        """
        base = dict(self.rule.default_config)
        override = dict(self.config_override)
        return _deep_merge(base, override)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
