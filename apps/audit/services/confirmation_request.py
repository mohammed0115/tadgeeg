"""External Confirmation workflow service (TADGEEG-FIN-AUDIT-9C · ISA 505).

Create → send → record response → reconcile (matched / discrepancy), plus
no-reply and cancel. Enforces organization consistency and an explicit status
graph. Recording a response computes recorded − confirmed; reconciliation
classifies it against the tolerance. Never writes to ``apps.ledger``, uses no
AI, and never auto-resolves a discrepancy — it is flagged for the auditor.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.confirmation_models import AuditConfirmationRequest

_C = AuditConfirmationRequest
_S = _C.Status
_ZERO = Decimal("0")

# Explicit transition graph.
ALLOWED_TRANSITIONS = {
    _S.DRAFT:      {_S.SENT, _S.CANCELLED},
    _S.SENT:       {_S.RESPONDED, _S.NO_REPLY, _S.CANCELLED},
    _S.RESPONDED:  {_S.MATCHED, _S.DISCREPANCY, _S.CANCELLED},
    _S.MATCHED:    set(),
    _S.DISCREPANCY: set(),
    _S.NO_REPLY:   set(),
    _S.CANCELLED:  set(),
}


class ConfirmationError(Exception):
    """Invalid transition, scoping violation, or bad input."""


def _actor_pk(actor):
    return actor if getattr(actor, "pk", None) else None


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ConfirmationError(f"invalid amount: {value!r}")


def _next_number(organization) -> str:
    count = AuditConfirmationRequest.objects.filter(organization=organization).count()
    return f"CNF-{count + 1:05d}"


def create_confirmation(*, engagement, actor, party_name, recorded_amount,
                        confirmation_type=_C.ConfirmationType.RECEIVABLE,
                        currency="SAR", party_reference="", party_email="",
                        tolerance=_ZERO) -> AuditConfirmationRequest:
    """Create a DRAFT confirmation request for an engagement."""
    if not party_name:
        raise ConfirmationError("party_name is required.")
    organization = engagement.organization
    req = AuditConfirmationRequest(
        engagement=engagement, organization=organization,
        confirmation_type=confirmation_type, party_name=party_name,
        party_reference=party_reference, party_email=party_email,
        recorded_amount=_to_decimal(recorded_amount),
        currency=currency or "SAR", tolerance=_to_decimal(tolerance),
        requested_by=_actor_pk(actor), status=_S.DRAFT)
    req.full_clean(exclude=["requested_by", "request_number"])
    with transaction.atomic():
        for attempt in range(5):
            req.request_number = _next_number(organization)
            try:
                with transaction.atomic():
                    req.save()
                break
            except IntegrityError:
                if attempt == 4:
                    raise
    return req


def _transition(request, to_status, *, fields=None):
    if to_status not in ALLOWED_TRANSITIONS.get(request.status, set()):
        raise ConfirmationError(f"invalid transition {request.status} → {to_status}.")
    request.status = to_status
    request.save(update_fields=list(set((fields or []) + ["status", "updated_at"])))
    return request


def send(*, request, actor=None) -> AuditConfirmationRequest:
    """DRAFT → SENT (records sent_at)."""
    request.sent_at = timezone.now()
    return _transition(request, _S.SENT, fields=["sent_at"])


def record_response(*, request, confirmed_amount, note="", actor=None) -> AuditConfirmationRequest:
    """SENT → RESPONDED. Stores the confirmed amount and (optional) note.

    Callable by the auditor OR by the external party via the public token page.
    """
    if request.status != _S.SENT:
        raise ConfirmationError(
            f"a response can only be recorded while the request is 'sent' "
            f"(current: {request.status}).")
    request.confirmed_amount = _to_decimal(confirmed_amount)
    request.response_note = note or ""
    request.responded_at = timezone.now()
    return _transition(request, _S.RESPONDED,
                       fields=["confirmed_amount", "response_note", "responded_at"])


def reconcile(*, request, actor) -> AuditConfirmationRequest:
    """RESPONDED → MATCHED or DISCREPANCY based on the tolerance.

    Never posts a correction — a discrepancy is only flagged for the auditor.
    """
    if request.status != _S.RESPONDED:
        raise ConfirmationError(
            f"only a responded request can be reconciled (current: {request.status}).")
    if request.confirmed_amount is None:
        raise ConfirmationError("no confirmed amount to reconcile.")
    within = request.is_within_tolerance
    request.reviewed_by = _actor_pk(actor)
    request.reviewed_at = timezone.now()
    return _transition(request, _S.MATCHED if within else _S.DISCREPANCY,
                       fields=["reviewed_by", "reviewed_at"])


def mark_no_reply(*, request, actor) -> AuditConfirmationRequest:
    """SENT → NO_REPLY (the party did not respond)."""
    request.reviewed_by = _actor_pk(actor)
    request.reviewed_at = timezone.now()
    return _transition(request, _S.NO_REPLY, fields=["reviewed_by", "reviewed_at"])


def cancel(*, request, actor) -> AuditConfirmationRequest:
    """Cancel a non-final request."""
    if request.is_final:
        raise ConfirmationError(f"cannot cancel a {request.status} request.")
    return _transition(request, _S.CANCELLED)


def status_counts(*, organization, engagement=None) -> dict:
    """Counts per status + a matched/discrepancy summary for the dashboard."""
    from django.db.models import Count, Q
    qs = AuditConfirmationRequest.objects.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    agg = {s.value: Count("id", filter=Q(status=s.value)) for s in _S}
    counts = qs.aggregate(**agg)
    counts = {k: (v or 0) for k, v in counts.items()}
    counts["total"] = sum(counts[s.value] for s in _S)
    counts["outstanding"] = counts[_S.DRAFT] + counts[_S.SENT] + counts[_S.RESPONDED]
    return counts
