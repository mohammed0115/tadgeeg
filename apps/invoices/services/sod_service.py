"""Segregation-of-Duties enforcement for invoice workflow.

Closes the most critical gap from the post-billing audit report: the
person who *uploads* an invoice must not also *review* or *approve*
it; the person who reviews must not be the same as the one who
approves. The "four-eyes" principle, codified at the service layer
so every API path that mutates approval state goes through the same
check.

Roles in this module mirror the spec:

    Maker      = Invoice.uploaded_by   (set on creation)
    Checker    = Invoice.reviewed_by   (set by InvoiceManualReviewView)
    Approver   = Invoice.approved_by   (set by InvoiceApproveView)

The SoD rule is: ``{Maker, Checker, Approver}`` must have at least
three distinct users when all are populated. Two-step partials
(Maker + Approver, no Checker yet) are still allowed but require
explicit "skip-review" intent — that's the responsibility of the
view, not this service.

The check itself is intentionally tenant-scoped: cross-organisation
contamination is prevented at the FK layer (each Invoice has an
``organization``), but we don't validate that here — that's the
viewset's filter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from django.utils.translation import gettext as _


logger = logging.getLogger("invoices.sod")


class SegregationOfDutiesError(PermissionError):
    """The action would violate the four-eyes principle.

    Used as PermissionError so DRF maps it to HTTP 403 by default,
    and so other code paths can `except PermissionError` if they
    don't want to depend on the specific class.
    """

    def __init__(self, *, action: str, conflicting_with: str, user_email: str = ""):
        self.action = action                   # "review" / "approve"
        self.conflicting_with = conflicting_with  # "maker" / "checker"
        self.user_email = user_email
        super().__init__(self.user_message)

    @property
    def user_message(self) -> str:
        if self.conflicting_with == "maker":
            return str(_(
                "Segregation of Duties: the user who uploaded an invoice "
                "cannot %(action)s it. A different user must perform this step."
            )) % {"action": self.action}
        if self.conflicting_with == "checker":
            return str(_(
                "Segregation of Duties: the reviewer of an invoice cannot "
                "also approve it. A different user must approve."
            ))
        return str(_("Segregation of Duties violated for action: %(action)s")) % {"action": self.action}


@dataclass(frozen=True)
class SoDDecision:
    """Diagnostic envelope — returned by ``inspect`` without raising
    so the view can render a friendly message."""
    allowed: bool
    reason: str = ""        # machine-readable: "sod_ok" | "self_review" | "self_approve" | "reviewer_is_approver"
    message: str = ""       # localised, user-facing


# ─── Inspection (non-raising) ────────────────────────────────────────────────
def can_review(invoice, user) -> SoDDecision:
    """Return a SoDDecision describing whether ``user`` may *review*
    ``invoice``. Does not raise."""
    if invoice.uploaded_by_id and user.pk == invoice.uploaded_by_id:
        return SoDDecision(
            allowed=False,
            reason="self_review",
            message=SegregationOfDutiesError(
                action="review", conflicting_with="maker", user_email=user.email,
            ).user_message,
        )
    return SoDDecision(allowed=True, reason="sod_ok", message="")


def can_approve(invoice, user) -> SoDDecision:
    """Return a SoDDecision describing whether ``user`` may *approve*
    ``invoice``."""
    if invoice.uploaded_by_id and user.pk == invoice.uploaded_by_id:
        return SoDDecision(
            allowed=False,
            reason="self_approve",
            message=SegregationOfDutiesError(
                action="approve", conflicting_with="maker", user_email=user.email,
            ).user_message,
        )
    reviewer_id = getattr(invoice, "reviewed_by_id", None)
    if reviewer_id and user.pk == reviewer_id:
        return SoDDecision(
            allowed=False,
            reason="reviewer_is_approver",
            message=SegregationOfDutiesError(
                action="approve", conflicting_with="checker", user_email=user.email,
            ).user_message,
        )
    return SoDDecision(allowed=True, reason="sod_ok", message="")


# ─── Enforcement (raising) ───────────────────────────────────────────────────
def assert_can_review(invoice, user) -> None:
    decision = can_review(invoice, user)
    if not decision.allowed:
        logger.warning(
            "[SoD] review blocked: user=%s invoice=%s reason=%s",
            user.email, invoice.pk, decision.reason,
        )
        raise SegregationOfDutiesError(
            action="review",
            conflicting_with="maker",
            user_email=user.email,
        )


def assert_can_approve(invoice, user) -> None:
    decision = can_approve(invoice, user)
    if not decision.allowed:
        logger.warning(
            "[SoD] approve blocked: user=%s invoice=%s reason=%s",
            user.email, invoice.pk, decision.reason,
        )
        conflicting = "checker" if decision.reason == "reviewer_is_approver" else "maker"
        raise SegregationOfDutiesError(
            action="approve",
            conflicting_with=conflicting,
            user_email=user.email,
        )


# ─── Recording (stamps the field + writes an audit event) ───────────────────
def record_review(invoice, user, *, note: str = "") -> None:
    """Stamp ``reviewed_by`` on the invoice (after a successful
    SoD check) and append a hash-chained audit event."""
    from django.utils import timezone
    invoice.reviewed_by = user
    invoice.reviewed_at = timezone.now()
    invoice.save(update_fields=["reviewed_by", "reviewed_at", "updated_at"])
    _audit_event(invoice, user, event_type="reviewed",
                 description=note or "Manual review completed")


def record_approval(invoice, user, *, note: str = "") -> None:
    """Stamp ``approved_by`` + audit event."""
    from django.utils import timezone
    invoice.approved_by = user
    invoice.approved_at = timezone.now()
    invoice.save(update_fields=["approved_by", "approved_at", "updated_at"])
    _audit_event(invoice, user, event_type="approved",
                 description=note or "Invoice approved")


def record_rejection(invoice, user, *, reason: str) -> None:
    from apps.invoices.models import Invoice
    invoice.status = Invoice.Status.REJECTED
    invoice.rejected_reason = reason
    invoice.save(update_fields=["status", "rejected_reason", "updated_at"])
    _audit_event(invoice, user, event_type="rejected",
                 description=f"Rejected: {reason}")


def _audit_event(invoice, user, *, event_type: str, description: str) -> None:
    """Best-effort append to the InvoiceAuditEvent hash chain. Failures
    here are logged but do not unwind the state transition — the chain
    is for forensics, not transactional integrity."""
    try:
        from apps.invoices.models import InvoiceAuditEvent
        InvoiceAuditEvent.objects.create(
            invoice=invoice,
            user=user,
            event_type=event_type,
            description=description,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not append %s event to invoice %s", event_type, invoice.pk)
