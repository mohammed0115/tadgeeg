import uuid

from django.db import models


class CrossDocumentLink(models.Model):
    """
    Records a detected (or manually confirmed) relationship between two
    documents of different types, e.g. a Purchase Order matched to an Invoice.

    Links are created automatically by cross-document rules during audit runs
    and can later be confirmed or rejected by a reviewer.
    """

    class LinkType(models.TextChoices):
        PO_TO_INVOICE = "po_to_invoice", "Purchase Order → Invoice"
        INVOICE_TO_PAYMENT = "invoice_to_payment", "Invoice → Payment"
        PAYROLL_TO_BANK = "payroll_to_bank", "Payroll → Bank Statement"
        TAX_TO_INVOICE = "tax_to_invoice", "Tax Return → Invoice"
        ASSET_TO_PURCHASE = "asset_to_purchase", "Fixed Asset → Purchase"
        EXPENSE_TO_RECEIPT = "expense_to_receipt", "Expense → Receipt"

    class MatchStatus(models.TextChoices):
        MATCHED = "matched", "Matched"
        PARTIAL = "partial", "Partial"
        UNMATCHED = "unmatched", "Unmatched"
        CONFLICT = "conflict", "Conflict"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="cross_document_links",
        db_index=True,
    )

    link_type = models.CharField(max_length=32, choices=LinkType.choices)

    # Source document
    source_document_type = models.CharField(max_length=32)
    source_document_id = models.UUIDField(db_index=True)

    # Target document
    target_document_type = models.CharField(max_length=32)
    target_document_id = models.UUIDField(db_index=True)

    # Match quality
    match_status = models.CharField(
        max_length=16,
        choices=MatchStatus.choices,
        default=MatchStatus.UNMATCHED,
    )
    match_score = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Normalised similarity score in the range [0, 1].",
    )
    match_details = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structured details of what was compared and how, e.g. "
            "{'amount_match': True, 'date_delta_days': 3, 'vendor_match': True}."
        ),
    )

    # Origin and confirmation
    auto_detected = models.BooleanField(
        default=True,
        help_text="True when the link was created automatically by a rule.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_by = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_document_links",
    )

    class Meta:
        db_table = "re_cross_document_link"
        indexes = [
            models.Index(
                fields=["source_document_type", "source_document_id"],
                name="re_cdlink_source_idx",
            ),
            models.Index(
                fields=["organization", "link_type", "match_status"],
                name="re_cdlink_org_type_status_idx",
            ),
        ]
        verbose_name = "Cross-Document Link"
        verbose_name_plural = "Cross-Document Links"

    def __str__(self) -> str:
        return (
            f"{self.link_type}: {self.source_document_type}/{self.source_document_id}"
            f" → {self.target_document_type}/{self.target_document_id}"
            f" [{self.match_status}]"
        )
