"""Engagement planning records service (TADGEEG-FIN-AUDIT-9H).

Save / list / delete the ISA 300 audit plan, ISA 330 responses and ISA 240 fraud
plan computed on the assessment pages onto an engagement. Deterministic storage
only — no engine logic here; never writes to ``apps.ledger``.
"""
from __future__ import annotations

from apps.audit.planning_record_models import EngagementPlanningRecord

_R = EngagementPlanningRecord
_VALID_KINDS = {k.value for k in _R.Kind}


class PlanningRecordError(Exception):
    """Invalid input or scoping violation."""


def save_record(*, engagement, actor, kind, payload, inputs=None, title="") -> EngagementPlanningRecord:
    """Persist a computed planning artifact onto the engagement."""
    if kind not in _VALID_KINDS:
        raise PlanningRecordError("unknown planning-record kind.")
    obj = EngagementPlanningRecord(
        engagement=engagement, organization=engagement.organization,
        kind=kind, title=(title or "")[:255],
        payload=payload or {}, inputs=inputs or {},
        created_by=actor if getattr(actor, "pk", None) else None)
    obj.full_clean(exclude=["created_by"])
    obj.save()
    return obj


def list_records(*, engagement, kind=None, limit=50):
    """Saved records for an engagement, newest first (optionally one kind)."""
    qs = EngagementPlanningRecord.objects.filter(engagement=engagement)
    if kind:
        qs = qs.filter(kind=kind)
    return list(qs.select_related("created_by")[:limit])


def delete_record(*, record, actor) -> None:
    record.delete()


def counts(*, organization, engagement=None) -> dict:
    """Per-kind counts for a dashboard/workspace."""
    from django.db.models import Count, Q
    qs = EngagementPlanningRecord.objects.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    agg = qs.aggregate(**{k.value: Count("id", filter=Q(kind=k.value)) for k in _R.Kind})
    out = {k: (v or 0) for k, v in agg.items()}
    out["total"] = sum(out.values())
    return out
