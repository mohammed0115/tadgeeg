"""Audit procedure service (TADGEEG-G2.2 · ISA 330).

Create / list / update procedures that respond to assessed risks — the second
link of the traceability spine. Deterministic; never writes to ``apps.ledger``.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from apps.audit.assessed_risk_models import AssessedRisk
from apps.audit.procedure_models import AuditProcedure

_P = AuditProcedure
_St = _P.Status
_VALID_STATUS = {s.value for s in _St}


class AuditProcedureError(Exception):
    """Invalid input or scoping violation."""


def _next_reference(organization) -> str:
    count = AuditProcedure.objects.filter(organization=organization).count()
    return f"PROC-{count + 1:05d}"


def create_procedure(*, engagement, actor, title, assessed_risk=None, nature=None,
                     timing=None, extent=None, description="") -> AuditProcedure:
    """Create a planned procedure, optionally linked to an assessed risk."""
    if not (title or "").strip():
        raise AuditProcedureError("title is required.")
    if assessed_risk is not None and not isinstance(assessed_risk, AssessedRisk):
        raise AuditProcedureError("assessed_risk must be an AssessedRisk instance.")
    obj = AuditProcedure(
        engagement=engagement, organization=engagement.organization,
        assessed_risk=assessed_risk, title=title.strip()[:255],
        nature=nature or _P.Nature.TEST_OF_DETAILS,
        timing=timing or _P.Timing.YEAR_END,
        extent=extent or _P.Extent.STANDARD,
        description=description or "",
        created_by=actor if getattr(actor, "pk", None) else None,
        status=_St.PLANNED)
    obj.full_clean(exclude=["created_by", "reference", "performed_by"])
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


def set_status(*, procedure, actor, status, conclusion="") -> AuditProcedure:
    """Move a procedure along its lifecycle; record who performed it."""
    if status not in _VALID_STATUS:
        raise AuditProcedureError(f"invalid status: {status!r}")
    procedure.status = status
    fields = ["status", "updated_at"]
    if conclusion:
        procedure.conclusion = conclusion
        fields.append("conclusion")
    if status in (_St.IN_PROGRESS, _St.COMPLETED) and getattr(actor, "pk", None):
        procedure.performed_by = actor
        fields.append("performed_by")
    procedure.save(update_fields=fields)
    return procedure


def link_risk(*, procedure, assessed_risk, actor) -> AuditProcedure:
    """Attach (or change) the assessed risk a procedure responds to."""
    if assessed_risk is not None:
        if (assessed_risk.engagement_id != procedure.engagement_id
                or assessed_risk.organization_id != procedure.organization_id):
            raise AuditProcedureError(
                "assessed_risk must belong to the same engagement and organization.")
    procedure.assessed_risk = assessed_risk
    procedure.save(update_fields=["assessed_risk", "updated_at"])
    return procedure


def list_procedures(*, engagement, assessed_risk=None, status=None, limit=500):
    qs = (AuditProcedure.objects.filter(engagement=engagement)
          .select_related("assessed_risk", "created_by", "performed_by"))
    if assessed_risk is not None:
        qs = qs.filter(assessed_risk=assessed_risk)
    if status:
        qs = qs.filter(status=status)
    return list(qs[:limit])


def summary(*, organization, engagement=None) -> dict:
    qs = AuditProcedure.objects.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    agg = qs.aggregate(
        total=Count("id"),
        linked=Count("id", filter=Q(assessed_risk__isnull=False)),
        **{s.value: Count("id", filter=Q(status=s.value)) for s in _St})
    return {k: (v or 0) for k, v in agg.items()}
