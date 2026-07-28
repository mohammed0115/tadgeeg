"""Engagement audit trail (TADGEEG-G0).

Thin, defensive wrappers that emit ISA-audit lifecycle events into the existing
organisation-wide, append-only, tamper-evident ``ActivityLog`` hash chain
(``apps.activity_logs``). This reuses mature infrastructure rather than adding a
parallel log: every engagement stage change / finding status change becomes a
hash-chained, edit-forbidden record (ISA 230 documentation).

Design:
  * **Never raises.** A logging failure must never break the primary action, so
    every write is wrapped — the caller's stage change / review still succeeds.
  * **No ledger writes**, no AI; purely an audit-trail side effect.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("audit.trail")


def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def record(*, organization, actor, action, entity_type="", entity_id="",
           description="", metadata=None, ip=None):
    """Append one row to the org's tamper-evident ActivityLog chain.

    Returns the created row, or ``None`` if logging failed (never raises).
    """
    try:
        from apps.activity_logs.models import ActivityLog
        return ActivityLog.objects.create(
            organization=organization,
            user=actor if getattr(actor, "pk", None) else None,
            action=action,
            entity_type=entity_type or "",
            entity_id=str(entity_id or ""),
            description=description or "",
            metadata=metadata or {},
            ip_address=ip)
    except Exception as exc:  # noqa: BLE001 - logging must never break the action
        logger.warning("audit-trail write failed (%s): %s", action, exc)
        return None


def record_stage_change(*, engagement, actor, old_stage, new_stage, request=None):
    """Log an engagement lifecycle stage transition (ISA 300)."""
    from apps.activity_logs.models import ActivityLog
    return record(
        organization=engagement.organization, actor=actor,
        action=ActivityLog.Action.ENGAGEMENT_STAGE_CHANGED,
        entity_type="audit_engagement", entity_id=engagement.pk,
        description=f"Stage {old_stage} -> {new_stage} "
                    f"({engagement.engagement_code})",
        metadata={"engagement_code": engagement.engagement_code,
                  "old_stage": str(old_stage), "new_stage": str(new_stage)},
        ip=_client_ip(request))


def record_finding_status_change(*, finding, actor, old_status, new_status,
                                 reason="", request=None):
    """Log a GL risk finding status transition (ISA 315/330 review, 3B)."""
    from apps.activity_logs.models import ActivityLog
    org = getattr(finding, "organization", None)
    return record(
        organization=org, actor=actor,
        action=ActivityLog.Action.FINDING_STATUS_CHANGED,
        entity_type="gl_risk_finding", entity_id=finding.pk,
        description=f"Finding {getattr(finding, 'reference', finding.pk)} "
                    f"{old_status} -> {new_status}",
        metadata={"old_status": str(old_status), "new_status": str(new_status),
                  "reason": reason or ""},
        ip=_client_ip(request))
