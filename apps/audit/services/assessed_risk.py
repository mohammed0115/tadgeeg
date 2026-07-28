"""Assessed Risk service (TADGEEG-G2 · ISA 315).

Create / list / transition assessed risks of material misstatement — the anchor
of the audit traceability chain. Deterministic; never writes to ``apps.ledger``.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from apps.audit.assessed_risk_models import AssessedRisk

_R = AssessedRisk
_St = _R.Status
_VALID_STATUS = {s.value for s in _St}


class AssessedRiskError(Exception):
    """Invalid input or scoping violation."""


def _next_reference(organization) -> str:
    count = AssessedRisk.objects.filter(organization=organization).count()
    return f"RISK-{count + 1:05d}"


def create_risk(*, engagement, actor, title, assertion=None, fs_area="",
                inherent_risk=None, control_risk=None, is_significant=False,
                is_fraud_risk=False, description="", notes="") -> AssessedRisk:
    """Record an assessed risk (status ``identified``)."""
    if not (title or "").strip():
        raise AssessedRiskError("title is required.")
    obj = AssessedRisk(
        engagement=engagement, organization=engagement.organization,
        title=title.strip()[:255], fs_area=(fs_area or "")[:120],
        assertion=assertion or _R.Assertion.EXISTENCE,
        inherent_risk=inherent_risk or _R.InherentRisk.MEDIUM,
        control_risk=control_risk or _R.ControlRisk.MEDIUM,
        is_significant=bool(is_significant), is_fraud_risk=bool(is_fraud_risk),
        description=description or "", notes=notes or "",
        created_by=actor if getattr(actor, "pk", None) else None,
        status=_St.IDENTIFIED)
    obj.full_clean(exclude=["created_by", "reference"])
    with transaction.atomic():
        for attempt in range(5):
            obj.reference = _next_reference(engagement.organization)
            try:
                with transaction.atomic():
                    obj.save()
                break
            except IntegrityError:
                if attempt == 4:
                    raise
    return obj


def set_status(*, risk, actor, status) -> AssessedRisk:
    """Move a risk along its lifecycle (identified→responded→tested→concluded→closed)."""
    if status not in _VALID_STATUS:
        raise AssessedRiskError(f"invalid status: {status!r}")
    risk.status = status
    risk.save(update_fields=["status", "updated_at"])
    return risk


def list_risks(*, engagement, status=None, assertion=None, limit=500):
    qs = AssessedRisk.objects.filter(engagement=engagement).select_related("created_by")
    if status:
        qs = qs.filter(status=status)
    if assertion:
        qs = qs.filter(assertion=assertion)
    return list(qs[:limit])


def summary(*, organization, engagement=None) -> dict:
    """Counts by status + significant/fraud tallies for a dashboard/workspace."""
    qs = AssessedRisk.objects.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    agg = qs.aggregate(
        total=Count("id"),
        significant=Count("id", filter=Q(is_significant=True)),
        fraud=Count("id", filter=Q(is_fraud_risk=True)),
        **{s.value: Count("id", filter=Q(status=s.value)) for s in _St})
    return {k: (v or 0) for k, v in agg.items()}
