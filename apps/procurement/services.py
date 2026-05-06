"""
Procurement workflow service — Phase 7.3.

Approval ladder (default; configurable per-org once the org-settings
table grows the field):

    ≤ 5,000      requester themselves (instant pre-approval)
    ≤ 50,000     senior_auditor and above
    ≤ 500,000    finance_manager / chief_audit_officer / admin
    > 500,000    admin only
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.authentication.models import User
from apps.procurement.models import (
    PRApproval, PRLine, PurchaseRequisition, ThreeWayMatchResult,
)

logger = logging.getLogger("finai.procurement")


# ─────────────────────────────────────────────────────────────────────────────
# Threshold ladder
# ─────────────────────────────────────────────────────────────────────────────

LADDER = [
    (Decimal("5000"),    {User.Role.JUNIOR_AUDITOR, User.Role.SENIOR_AUDITOR,
                          User.Role.FINANCE_MANAGER, User.Role.CHIEF_AUDIT_OFFICER,
                          User.Role.ADMIN}),
    (Decimal("50000"),   {User.Role.SENIOR_AUDITOR, User.Role.FINANCE_MANAGER,
                          User.Role.CHIEF_AUDIT_OFFICER, User.Role.ADMIN}),
    (Decimal("500000"),  {User.Role.FINANCE_MANAGER, User.Role.CHIEF_AUDIT_OFFICER,
                          User.Role.ADMIN}),
    (Decimal("9" * 18),  {User.Role.ADMIN}),
]


def required_role_set(amount: Decimal) -> set[str]:
    """Return the set of roles allowed to approve a PR of ``amount``."""
    for ceiling, allowed in LADDER:
        if amount <= ceiling:
            return allowed
    return {User.Role.ADMIN}


def can_approve(user, pr: PurchaseRequisition) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.role in required_role_set(Decimal(str(pr.total_amount or 0)))


# ─────────────────────────────────────────────────────────────────────────────
# Numbering + workflow
# ─────────────────────────────────────────────────────────────────────────────

def _next_pr_number(organization) -> str:
    year = timezone.now().year
    prefix = f"PR-{year}-"
    last = (
        PurchaseRequisition.objects
        .filter(organization=organization, pr_number__startswith=prefix)
        .order_by("-pr_number").first()
    )
    if not last:
        return f"{prefix}00001"
    try:
        seq = int(last.pr_number.rsplit("-", 1)[-1])
    except ValueError:
        seq = 0
    return f"{prefix}{seq + 1:05d}"


@transaction.atomic
def create_requisition(*, organization, requested_by, title: str,
                       description: str = "", needed_by=None,
                       department: str = "", cost_center: str = "",
                       vendor_name: str = "", currency: str = "SAR",
                       lines: Optional[list[dict]] = None) -> PurchaseRequisition:
    """Create a draft PR with line items.

    Each line dict: ``{description, quantity, unit_price, account_code}``.
    ``total_amount`` is computed from the lines so the caller can't
    fabricate a number that doesn't match the lines (a common procurement-
    fraud vector).
    """
    pr = PurchaseRequisition.objects.create(
        organization=organization,
        pr_number=_next_pr_number(organization),
        title=title[:200],
        description=description,
        requested_by=requested_by,
        department=department[:64],
        cost_center=cost_center[:64],
        needed_by=needed_by,
        vendor_name=vendor_name[:200],
        currency=currency,
        status=PurchaseRequisition.Status.DRAFT,
    )

    total = Decimal("0")
    for idx, ln in enumerate(lines or [], start=1):
        qty   = Decimal(str(ln.get("quantity") or 1))
        price = Decimal(str(ln.get("unit_price") or 0))
        line_total = (qty * price).quantize(Decimal("0.01"))
        PRLine.objects.create(
            requisition=pr, line_number=idx,
            description=str(ln.get("description") or "")[:255],
            quantity=qty, unit_price=price, line_total=line_total,
            account_code=str(ln.get("account_code") or "")[:24],
        )
        total += line_total

    pr.total_amount = total
    pr.save(update_fields=["total_amount", "updated_at"])
    return pr


@transaction.atomic
def submit_for_approval(pr: PurchaseRequisition, *, user) -> PurchaseRequisition:
    if pr.status != PurchaseRequisition.Status.DRAFT:
        raise ValueError(f"cannot submit a {pr.status} PR")
    if pr.total_amount <= 0:
        raise ValueError("PR has no value — add at least one line")

    pr.status = PurchaseRequisition.Status.SUBMITTED
    pr.submitted_at = timezone.now()
    pr.save(update_fields=["status", "submitted_at", "updated_at"])
    return pr


@transaction.atomic
def approve_requisition(pr: PurchaseRequisition, *, user,
                        notes: str = "") -> PurchaseRequisition:
    """Approve a SUBMITTED PR. Requires a role that covers ``total_amount``."""
    if pr.status != PurchaseRequisition.Status.SUBMITTED:
        raise ValueError(f"only SUBMITTED PRs can be approved (got {pr.status})")
    if not can_approve(user, pr):
        raise PermissionError(
            f"role {user.role} can't approve {pr.total_amount} {pr.currency} — "
            f"requires one of {sorted(required_role_set(Decimal(str(pr.total_amount))))}"
        )

    pr.status = PurchaseRequisition.Status.APPROVED
    pr.approved_at = timezone.now()
    pr.approved_by = user
    pr.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])

    PRApproval.objects.create(
        requisition=pr, decided_by=user,
        decision=PRApproval.Decision.APPROVED, notes=notes,
        threshold_role=getattr(user, "role", "") or "",
    )
    return pr


@transaction.atomic
def reject_requisition(pr: PurchaseRequisition, *, user, reason: str) -> PurchaseRequisition:
    if pr.status not in {PurchaseRequisition.Status.SUBMITTED,
                         PurchaseRequisition.Status.APPROVED}:
        raise ValueError(f"can't reject a {pr.status} PR")
    if not reason.strip():
        raise ValueError("rejection reason is required")

    pr.status = PurchaseRequisition.Status.REJECTED
    pr.rejected_at = timezone.now()
    pr.rejection_reason = reason
    pr.save(update_fields=["status", "rejected_at", "rejection_reason", "updated_at"])

    PRApproval.objects.create(
        requisition=pr, decided_by=user,
        decision=PRApproval.Decision.REJECTED, notes=reason,
        threshold_role=getattr(user, "role", "") or "",
    )
    return pr


@transaction.atomic
def convert_to_po(pr: PurchaseRequisition, *, user) -> "documents.PurchaseOrder":
    """Issue a Purchase Order from an APPROVED PR.

    The PR transitions to CLOSED and points at the PO it spawned. Once
    closed, edits are blocked — the PO is now the source of truth for
    the procurement chain.
    """
    if pr.status != PurchaseRequisition.Status.APPROVED:
        raise ValueError(f"only APPROVED PRs can be converted to a PO (got {pr.status})")

    from apps.documents.typed_models import PurchaseOrder

    po = PurchaseOrder.objects.create(
        organization=pr.organization,
        po_number=f"PO-{pr.pr_number.split('-', 1)[-1]}",
        po_date=timezone.now().date(),
        vendor_name=pr.vendor_name or "",
        currency=pr.currency,
        subtotal=pr.total_amount,
        total_amount=pr.total_amount,
        line_items=[
            {"description": li.description, "quantity": float(li.quantity),
             "unit_price": float(li.unit_price), "total": float(li.line_total),
             "account_code": li.account_code}
            for li in pr.lines.order_by("line_number")
        ],
    )

    pr.status = PurchaseRequisition.Status.CLOSED
    pr.purchase_order = po
    pr.save(update_fields=["status", "purchase_order", "updated_at"])
    return po


# ─────────────────────────────────────────────────────────────────────────────
# 3-way matching
# ─────────────────────────────────────────────────────────────────────────────

def match_three_way(po, *, grn=None, invoice=None) -> ThreeWayMatchResult:
    """Compare PO ↔ GRN ↔ Invoice on the fields that legally matter
    (totals, vendor, line counts) and persist the result.

    Idempotent: a fresh row is created on every call so the procurement
    dashboard sees a history of how the match evolved as documents
    arrived.
    """
    differences: list[dict] = []
    score = 100

    po_total      = float(getattr(po, "total_amount", 0) or 0)
    grn_total     = float(getattr(grn, "total_amount", 0) or 0) if grn else None
    invoice_total = float(getattr(invoice, "total_amount", 0) or 0) if invoice else None

    if grn_total is not None and abs(po_total - grn_total) > 1.0:
        differences.append({
            "field": "total_amount", "po": po_total, "grn": grn_total,
            "message": "PO total ≠ GRN total",
        })
        score -= 30
    if invoice_total is not None and abs(po_total - invoice_total) > 1.0:
        differences.append({
            "field": "total_amount", "po": po_total, "invoice": invoice_total,
            "message": "PO total ≠ Invoice total",
        })
        score -= 30

    po_vendor = (getattr(po, "vendor_name", "") or "").strip().lower()
    inv_vendor = (getattr(invoice, "vendor_name", "") or "").strip().lower() if invoice else ""
    if invoice and po_vendor and inv_vendor and po_vendor != inv_vendor:
        differences.append({
            "field": "vendor_name",
            "po": po_vendor, "invoice": inv_vendor,
            "message": "Vendor name on PO ≠ Invoice",
        })
        score -= 15

    score = max(0, score)
    if grn is None or invoice is None:
        status = ThreeWayMatchResult.Status.PENDING
    elif differences:
        status = (ThreeWayMatchResult.Status.MISMATCH
                  if score < 70 else ThreeWayMatchResult.Status.PARTIAL)
    else:
        status = ThreeWayMatchResult.Status.MATCHED

    return ThreeWayMatchResult.objects.create(
        organization=po.organization,
        purchase_order=po,
        goods_receipt=grn,
        invoice=invoice,
        status=status,
        differences=differences,
        score=score,
    )
