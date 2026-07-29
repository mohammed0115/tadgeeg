"""Engagement member service (TADGEEG-G3.3)."""
from __future__ import annotations

from apps.audit.member_models import EngagementMember

_M = EngagementMember
_VALID_ROLES = {r.value for r in _M.Role}


class EngagementMemberError(Exception):
    """Invalid input or scoping violation."""


def assign(*, engagement, actor, user, role=None, responsibilities="", due_date=None):
    """Assign (or reactivate) a user to an engagement in a role."""
    role = role or _M.Role.MEMBER
    if role not in _VALID_ROLES:
        raise EngagementMemberError(f"invalid role: {role!r}")
    if getattr(user, "organization_id", None) != engagement.organization_id:
        raise EngagementMemberError("member must belong to the engagement's organization.")
    obj, created = EngagementMember.objects.get_or_create(
        engagement=engagement, user=user, role=role,
        defaults={"organization": engagement.organization,
                  "responsibilities": responsibilities or "", "due_date": due_date,
                  "assigned_by": actor if getattr(actor, "pk", None) else None})
    if not created:
        obj.is_active = True
        if responsibilities:
            obj.responsibilities = responsibilities[:255]
        if due_date:
            obj.due_date = due_date
        obj.save(update_fields=["is_active", "responsibilities", "due_date", "updated_at"])
    return obj


def remove(*, member, actor) -> EngagementMember:
    """Deactivate a membership (kept for the audit trail, not hard-deleted)."""
    member.is_active = False
    member.save(update_fields=["is_active", "updated_at"])
    return member


def list_members(*, engagement, active_only=True):
    qs = EngagementMember.objects.filter(engagement=engagement).select_related(
        "user", "assigned_by")
    if active_only:
        qs = qs.filter(is_active=True)
    return list(qs)


def summary(*, organization, engagement=None) -> dict:
    from django.db.models import Count, Q
    qs = EngagementMember.objects.filter(organization=organization, is_active=True)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    agg = qs.aggregate(
        total=Count("id"),
        **{f"role_{r.value}": Count("id", filter=Q(role=r.value)) for r in _M.Role})
    return {k: (v or 0) for k, v in agg.items()}
