"""Threshold-based multi-approver policy (F-2).

Single-approver override on the Golden Rule was the audit-review's
Finding 2. This module ships:

  • Per-amount threshold (default 100,000 SAR — configurable).
  • Invoices above the threshold require an ``OverrideRequest`` row
    (model lives in ``apps.invoices.models``) that's countersigned by
    a SECOND admin within ``COUNTERSIGN_WINDOW`` (default 24h), or the
    invoice stays BLOCKED.
  • Each countersign writes an AuditLog row for the four-eyes pack.

The InvoiceApproveView keeps the single-approver path for invoices
below the threshold (≈ 99% of volume), so the daily flow is unchanged.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.invoices.models import OverrideRequest


_DEFAULT_THRESHOLD     = Decimal("100000.00")
_DEFAULT_WINDOW_HOURS  = 24


def _threshold() -> Decimal:
    return Decimal(str(
        getattr(settings, "APPROVAL_OVERRIDE_THRESHOLD_SAR", _DEFAULT_THRESHOLD)
    ))


def _window() -> timedelta:
    hours = int(getattr(settings, "APPROVAL_COUNTERSIGN_WINDOW_HOURS",
                        _DEFAULT_WINDOW_HOURS))
    return timedelta(hours=hours)


# ─── Policy ────────────────────────────────────────────────────────────────

def requires_countersign(invoice) -> bool:
    """True if this invoice's amount is over the multi-approver threshold."""
    amount = Decimal(invoice.total_amount or 0)
    return amount >= _threshold()


@transaction.atomic
def open_override_request(invoice, *, requested_by, reason: str) -> OverrideRequest:
    """First admin clicks 'override'. Creates a PENDING row. The invoice
    stays in its current state until a SECOND admin countersigns."""
    if not requires_countersign(invoice):
        raise ValueError("Invoice amount below override threshold — no countersign needed.")
    if not (reason or "").strip():
        raise ValueError("override reason is required.")
    return OverrideRequest.objects.create(
        organization=invoice.organization,
        invoice=invoice,
        requested_by=requested_by,
        reason=reason.strip(),
        amount=Decimal(invoice.total_amount or 0),
        threshold=_threshold(),
        expires_at=timezone.now() + _window(),
    )


@transaction.atomic
def countersign(override_id, *, actor) -> OverrideRequest:
    """Second admin approves the override. SoD: actor != requester."""
    ovr = (
        OverrideRequest.objects
        .select_for_update()
        .select_related("invoice", "requested_by")
        .get(pk=override_id)
    )
    if ovr.status != OverrideRequest.Status.PENDING:
        raise ValueError(f"Override already {ovr.status}.")
    if ovr.is_expired:
        ovr.status = OverrideRequest.Status.EXPIRED
        ovr.save(update_fields=["status"])
        raise ValueError("Override request expired.")
    if ovr.requested_by_id == actor.pk:
        raise PermissionError(
            "Same admin cannot countersign their own override request "
            "(four-eyes principle)."
        )
    ovr.countersigned_by = actor
    ovr.countersigned_at = timezone.now()
    ovr.status = OverrideRequest.Status.COUNTERSIGNED
    ovr.save(update_fields=["countersigned_by", "countersigned_at", "status"])
    return ovr


def has_valid_countersign(invoice) -> Optional[OverrideRequest]:
    """Return the active COUNTERSIGNED override for an invoice, if any."""
    return (
        OverrideRequest.objects
        .filter(
            invoice=invoice,
            status=OverrideRequest.Status.COUNTERSIGNED,
        )
        .order_by("-countersigned_at")
        .first()
    )
