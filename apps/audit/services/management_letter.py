"""Management Letter service (TADGEEG-FIN-AUDIT-9B · ISA 265).

Create/update control deficiencies, record management's response, and build a
Management Letter grouped by significance. The letter COMMUNICATES deficiencies
to those charged with governance — it is not an audit opinion, uses no AI, and
never writes to ``apps.ledger``.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.control_deficiency_models import AuditControlDeficiency

_D = AuditControlDeficiency
_Cls = _D.Classification
_Status = _D.Status

# Wording is safe/communicative — ISA 265 is a communication, not an opinion.
LETTER_DISCLAIMER = (
    "This management letter communicates deficiencies in internal control "
    "identified during the audit (ISA 265). It is not a comprehensive statement "
    "of all deficiencies that might exist, does not modify the audit opinion, "
    "and is provided for the use of those charged with governance."
)


class ManagementLetterError(Exception):
    """Invalid input or scoping violation."""


def _actor_pk(actor):
    return actor if getattr(actor, "pk", None) else None


def _next_reference(organization) -> str:
    count = AuditControlDeficiency.objects.filter(organization=organization).count()
    return f"DEF-{count + 1:05d}"


def create_deficiency(*, engagement, actor, title, classification=_Cls.OTHER_DEFICIENCY,
                      area=_D.Area.OTHER, description="", potential_effect="",
                      recommendation="", gl_finding=None) -> AuditControlDeficiency:
    """Create an internal-control deficiency for an engagement."""
    if not title:
        raise ManagementLetterError("title is required.")
    organization = engagement.organization
    obj = AuditControlDeficiency(
        engagement=engagement, organization=organization, title=title,
        classification=classification, area=area, description=description,
        potential_effect=potential_effect, recommendation=recommendation,
        gl_finding=gl_finding, identified_by=_actor_pk(actor), status=_Status.OPEN)
    obj.full_clean(exclude=["identified_by", "reference"])
    with transaction.atomic():
        for attempt in range(5):
            obj.reference = _next_reference(organization)
            try:
                with transaction.atomic():
                    obj.save()
                break
            except IntegrityError:
                if attempt == 4:
                    raise
    return obj


def record_management_response(*, deficiency, actor, response, owner="", target_date=None):
    """Store management's response; moves status to MANAGEMENT_RESPONDED."""
    if not (response or "").strip():
        raise ManagementLetterError("management response cannot be empty.")
    deficiency.management_response = response
    deficiency.management_action_owner = owner or ""
    deficiency.target_date = target_date
    if deficiency.status == _Status.OPEN:
        deficiency.status = _Status.MANAGEMENT_RESPONDED
    deficiency.save(update_fields=["management_response", "management_action_owner",
                                   "target_date", "status", "updated_at"])
    return deficiency


def set_status(*, deficiency, actor, status):
    if status not in _Status.values:
        raise ManagementLetterError(f"invalid status: {status!r}")
    deficiency.status = status
    deficiency.save(update_fields=["status", "updated_at"])
    return deficiency


def _deficiency_dict(d) -> dict:
    return {
        "id": str(d.id), "reference": d.reference, "title": d.title,
        "area": d.area, "area_display": d.get_area_display(),
        "classification": d.classification,
        "classification_display": d.get_classification_display(),
        "status": d.status, "status_display": d.get_status_display(),
        "description": d.description, "potential_effect": d.potential_effect,
        "recommendation": d.recommendation,
        "management_response": d.management_response,
        "management_action_owner": d.management_action_owner,
        "target_date": str(d.target_date) if d.target_date else None,
    }


def build_management_letter(*, engagement) -> dict:
    """Group the engagement's deficiencies into a Management Letter payload."""
    org = engagement.organization
    deficiencies = list(AuditControlDeficiency.objects.filter(engagement=engagement))

    groups = {c.value: [] for c in _Cls}
    for d in sorted(deficiencies, key=lambda x: (x.severity_rank, x.created_at)):
        groups[d.classification].append(_deficiency_dict(d))

    counts = {c.value: len(groups[c.value]) for c in _Cls}
    counts["total"] = len(deficiencies)
    counts["open"] = sum(1 for d in deficiencies if d.status == _Status.OPEN)
    counts["remediated"] = sum(1 for d in deficiencies if d.status == _Status.REMEDIATED)

    return {
        "advisory_only": True,
        "not_an_opinion": True,
        "disclaimer": LETTER_DISCLAIMER,
        "generated_at": timezone.now().isoformat(),
        "engagement": {
            "id": str(engagement.id),
            "engagement_code": engagement.engagement_code,
            "title": engagement.title,
            "period_start": str(engagement.period_start),
            "period_end": str(engagement.period_end),
            "organization_id": org.id,
        },
        "groups": {
            "material_weakness": groups[_Cls.MATERIAL_WEAKNESS],
            "significant_deficiency": groups[_Cls.SIGNIFICANT_DEFICIENCY],
            "other_deficiency": groups[_Cls.OTHER_DEFICIENCY],
        },
        "counts": counts,
    }


def status_counts(*, organization, engagement=None) -> dict:
    from django.db.models import Count, Q
    qs = AuditControlDeficiency.objects.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    by_cls = {c.value: Count("id", filter=Q(classification=c.value)) for c in _Cls}
    by_status = {f"status_{s.value}": Count("id", filter=Q(status=s.value)) for s in _Status}
    counts = qs.aggregate(**by_cls, **by_status)
    counts = {k: (v or 0) for k, v in counts.items()}
    counts["total"] = sum(counts[c.value] for c in _Cls)
    return counts
