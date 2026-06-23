"""Proposed audit adjustment capture for SAD items (TADGEEG-FIN-AUDIT-4B).

Creates/updates a ``ProposedAuditAdjustment`` for documentation only. It NEVER
creates or modifies ``ledger.JournalEntry`` and never posts anything — any real
posting is done by the client in their own system and only *referenced* here.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.audit.audit_difference_models import (
    AuditDifferenceItem,
    ProposedAuditAdjustment,
)

_Type = ProposedAuditAdjustment.Type


class ProposedAdjustmentError(Exception):
    """Raised for validation failures (amount, accounts, currency, tenancy)."""


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def create_or_update_adjustment(item: AuditDifferenceItem, *, actor,
                                adjustment_type: str, amount,
                                description: str = "",
                                debit_account_code: str = "", debit_account_name: str = "",
                                credit_account_code: str = "", credit_account_name: str = "",
                                currency: str = "", status: str | None = None,
                                management_accepted=None,
                                client_posted_reference: str = "",
                                adjustment_id=None) -> ProposedAuditAdjustment:
    """Create (or update an existing) proposed adjustment for a SAD item.

    Validates: tenancy, known type, amount > 0, currency present, and that
    debit/credit accounts are supplied unless ``adjustment_type`` is
    ``disclosure_only``. Never posts to the ledger.
    """
    actor_org_id = getattr(actor, "organization_id", None)
    if actor_org_id is not None and actor_org_id != item.organization_id:
        raise ProposedAdjustmentError("cross-tenant adjustment denied.")

    if adjustment_type not in _Type.values:
        raise ProposedAdjustmentError(f"invalid adjustment_type: {adjustment_type!r}")

    amt = _to_decimal(amount)
    if amt is None or amt <= 0:
        raise ProposedAdjustmentError("amount must be a positive number.")

    # Default currency from the engagement's materiality snapshot / summary.
    currency = (currency or "").strip()
    if not currency:
        currency = (item.summary.materiality_basis and "") or ""
        snap = item.summary.calculation_snapshot or {}
        currency = snap.get("currency") or ""
    currency = (currency or "").strip()[:8]

    if adjustment_type != _Type.DISCLOSURE_ONLY:
        if not (debit_account_code.strip() and credit_account_code.strip()):
            raise ProposedAdjustmentError(
                "debit_account_code and credit_account_code are required "
                "unless adjustment_type is 'disclosure_only'."
            )

    if status is not None and status not in ProposedAuditAdjustment.Status.values:
        raise ProposedAdjustmentError(f"invalid status: {status!r}")

    actor_user = actor if getattr(actor, "pk", None) else None
    if adjustment_id:
        adj = ProposedAuditAdjustment.objects.filter(
            pk=adjustment_id, item=item, organization=item.organization).first()
        if adj is None:
            raise ProposedAdjustmentError("adjustment not found for this item.")
    else:
        adj = ProposedAuditAdjustment(item=item, summary=item.summary,
                                      engagement=item.engagement,
                                      organization=item.organization,
                                      proposed_by=actor_user,
                                      proposed_at=timezone.now())

    adj.adjustment_type = adjustment_type
    adj.description = description
    adj.debit_account_code = debit_account_code.strip()[:64]
    adj.debit_account_name = debit_account_name.strip()[:255]
    adj.credit_account_code = credit_account_code.strip()[:64]
    adj.credit_account_name = credit_account_name.strip()[:255]
    adj.amount = amt
    adj.currency = currency
    if management_accepted is not None:
        adj.management_accepted = bool(management_accepted)
    if client_posted_reference:
        adj.client_posted_reference = client_posted_reference.strip()[:128]
    adj.status = status or ProposedAuditAdjustment.Status.PROPOSED
    adj.save()
    return adj
