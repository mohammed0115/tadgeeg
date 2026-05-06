"""
Procurement workflow — Phase 7.3.

The procurement chain from request → purchase → receipt → invoice:

    PurchaseRequisition  →  PurchaseOrder  →  GoodsReceiptNote  →  Invoice

The first three live here; the existing apps house the last two
(``apps.documents.typed_models.PurchaseOrder`` and ``apps.invoices``).
This module adds the missing front of the chain (PR + approvals) and a
single-shot 3-way-match service that ties everything together.

State machine (``PurchaseRequisition``):

    DRAFT → SUBMITTED → APPROVED → CLOSED
                     ↘ REJECTED

Approval routing is by **threshold** — the approver gate is whichever
role's spending limit covers the requested amount. Default ladder:

    ≤ 5,000      Junior auditor / requester themselves
    ≤ 50,000     Senior auditor
    ≤ 500,000    Finance manager / CAO
    > 500,000    Admin

Each transition is recorded on ``PRApproval`` so the audit trail
shows who-approved-what-when.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


class PurchaseRequisition(models.Model):
    """A request to purchase, before the PO is issued."""

    class Status(models.TextChoices):
        DRAFT     = "draft",     "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED  = "approved",  "Approved"
        REJECTED  = "rejected",  "Rejected"
        CLOSED    = "closed",    "Closed (PO issued)"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="purchase_requisitions",
    )
    pr_number     = models.CharField(max_length=24, db_index=True,
                                     help_text="e.g. PR-2026-00123 — auto-generated.")
    title         = models.CharField(max_length=200)
    description   = models.TextField(blank=True)

    requested_by  = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="requested_prs",
    )
    department    = models.CharField(max_length=64, blank=True)
    cost_center   = models.CharField(max_length=64, blank=True)
    needed_by     = models.DateField(null=True, blank=True)

    vendor_name   = models.CharField(max_length=200, blank=True,
                                     help_text="Preferred vendor; not binding until the PO is issued.")
    currency      = models.CharField(max_length=3, default="SAR")
    total_amount  = models.DecimalField(max_digits=18, decimal_places=2,
                                        default=Decimal("0"))

    status        = models.CharField(max_length=12, choices=Status.choices,
                                     default=Status.DRAFT, db_index=True)
    purchase_order = models.ForeignKey(
        "documents.PurchaseOrder", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="requisitions",
        help_text="Filled when the PR is converted to a PO.",
    )
    submitted_at  = models.DateTimeField(null=True, blank=True)
    approved_at   = models.DateTimeField(null=True, blank=True)
    approved_by   = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="approved_prs",
    )
    rejected_at   = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "procurement_requisitions"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "pr_number"],
                name="procurement_pr_unique_number_per_org",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.pr_number} — {self.title[:50]}"


class PRLine(models.Model):
    """One line item on a PR."""

    id            = models.BigAutoField(primary_key=True)
    requisition   = models.ForeignKey(
        PurchaseRequisition, on_delete=models.CASCADE, related_name="lines",
    )
    line_number   = models.PositiveSmallIntegerField()
    description   = models.CharField(max_length=255)
    quantity      = models.DecimalField(max_digits=18, decimal_places=4,
                                        default=Decimal("1"))
    unit_price    = models.DecimalField(max_digits=18, decimal_places=4,
                                        default=Decimal("0"))
    line_total    = models.DecimalField(max_digits=18, decimal_places=2,
                                        default=Decimal("0"))
    account_code  = models.CharField(max_length=24, blank=True,
                                     help_text="GL account this line will debit when the matching invoice posts.")

    class Meta:
        db_table = "procurement_pr_lines"
        ordering = ["requisition", "line_number"]


class PRApproval(models.Model):
    """An approve/reject event on a PR — tracks who acted, when, and why.

    A PR may walk through multiple approval steps as it climbs the ladder
    (e.g. line-manager, finance, admin), so this is a list, not a single
    column on the requisition."""

    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ESCALATED = "escalated", "Escalated to next tier"

    id            = models.BigAutoField(primary_key=True)
    requisition   = models.ForeignKey(
        PurchaseRequisition, on_delete=models.CASCADE, related_name="approvals",
    )
    decided_by    = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, related_name="pr_decisions",
    )
    decision      = models.CharField(max_length=10, choices=Decision.choices)
    notes         = models.TextField(blank=True)
    threshold_role = models.CharField(max_length=32, blank=True,
                                      help_text="The approval-tier role at which this decision was made.")
    decided_at    = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "procurement_pr_approvals"
        ordering = ["-decided_at"]


class ThreeWayMatchResult(models.Model):
    """Snapshot of a 3-way match between a PO, a GRN, and an Invoice.

    R007 in the audit engine evaluates the match every time a document
    arrives; this row caches the result for the dashboard so the
    procurement screen doesn't have to re-run the rule on every page
    load.
    """

    class Status(models.TextChoices):
        MATCHED   = "matched",   "Matched"
        MISMATCH  = "mismatch",  "Mismatched"
        PARTIAL   = "partial",   "Partial match"
        PENDING   = "pending",   "Pending documents"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="threeway_matches",
    )
    purchase_order = models.ForeignKey(
        "documents.PurchaseOrder", on_delete=models.CASCADE,
        related_name="threeway_matches",
    )
    goods_receipt = models.ForeignKey(
        "documents.GoodsReceiptNote", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="threeway_matches",
    )
    invoice       = models.ForeignKey(
        "invoices.Invoice", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="threeway_matches",
    )

    status        = models.CharField(max_length=12, choices=Status.choices,
                                     default=Status.PENDING, db_index=True)
    differences   = models.JSONField(default=list, blank=True,
                                     help_text="List of {field, po, grn, invoice, message} dicts.")
    score         = models.PositiveSmallIntegerField(default=0)
    computed_at   = models.DateTimeField(default=timezone.now)
    notes         = models.TextField(blank=True)

    class Meta:
        db_table = "procurement_threeway_matches"
        ordering = ["-computed_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
        ]
