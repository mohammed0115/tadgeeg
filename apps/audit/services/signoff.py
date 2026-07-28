"""Engagement sign-off service (TADGEEG-G3 · ISA 220/230).

Record preparer/reviewer/partner/EQR sign-offs on any engagement artifact and
enforce the ISA 220 segregation rule: a reviewer/partner/EQR sign-off cannot be
made by whoever prepared the same artifact. Deterministic; no ledger writes.
"""
from __future__ import annotations

from apps.audit.signoff_models import EngagementSignoff

_S = EngagementSignoff
_Role = _S.Role
_VALID_ROLES = {r.value for r in _Role}


class SignoffError(Exception):
    """Invalid input or a segregation-of-duties violation."""


def sign(*, engagement, actor, artifact_type, artifact_id, role, note=""):
    """Record a sign-off. Enforces preparer ≠ reviewer/partner/EQR."""
    if role not in _VALID_ROLES:
        raise SignoffError(f"invalid role: {role!r}")
    if not artifact_type or not artifact_id:
        raise SignoffError("artifact_type and artifact_id are required.")
    actor_id = getattr(actor, "pk", None)

    if role in _S.REVIEW_ROLES and actor_id is not None:
        prepared_by_actor = EngagementSignoff.objects.filter(
            engagement=engagement, artifact_type=artifact_type,
            artifact_id=str(artifact_id), role=_Role.PREPARER,
            signed_by_id=actor_id).exists()
        if prepared_by_actor:
            raise SignoffError(
                "segregation of duties: the preparer of this artifact cannot "
                "sign it off as reviewer/partner (ISA 220).")

    obj = EngagementSignoff(
        engagement=engagement, organization=engagement.organization,
        artifact_type=artifact_type, artifact_id=str(artifact_id),
        role=role, signed_by=actor if actor_id else None, note=note or "")
    obj.full_clean(exclude=["signed_by"])
    obj.save()
    return obj


def signoffs_for(*, engagement, artifact_type, artifact_id):
    """All sign-offs on one artifact, newest first."""
    return list(EngagementSignoff.objects.filter(
        engagement=engagement, artifact_type=artifact_type,
        artifact_id=str(artifact_id)).select_related("signed_by"))


def is_signed_off(*, engagement, artifact_type, artifact_id, role) -> bool:
    return EngagementSignoff.objects.filter(
        engagement=engagement, artifact_type=artifact_type,
        artifact_id=str(artifact_id), role=role).exists()


def status_for(*, engagement, artifact_type, artifact_id) -> dict:
    """Which roles have signed off on an artifact."""
    rows = signoffs_for(engagement=engagement, artifact_type=artifact_type,
                        artifact_id=artifact_id)
    signed = {r.role for r in rows}
    return {role.value: (role.value in signed) for role in _Role}
