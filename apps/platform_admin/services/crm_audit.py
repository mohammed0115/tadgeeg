"""
CRM audit writer (CRM-1B).

Writes CRM administrative actions to the EXISTING ``authentication.AuditLog`` —
the formal, append-only, hash-chained security record. Per the locked CRM-1A
decisions:

  * No ``PlatformAuditLog`` model is created.
  * ``AuditLog.Action`` enum is NOT extended. We reuse the existing
    ``CONFIG_CHANGED`` choice as the umbrella action and put the detailed CRM
    verb in ``details["action_type"]``.
  * The hash-chain is computed by ``AuditLog.save()`` itself — we never write
    chain logic by hand.

Why not reuse ``core.utils.audit.log_action``? That helper derives the
organization from ``request.user.organization`` and requires a request object.
In CRM the staff actor's own organization is ``None`` and the relevant
organization is the *customer's* — so we write AuditLog directly with the
customer organization, mirroring log_action's savepoint safety.
"""

import logging

from django.db import transaction

logger = logging.getLogger("finai")

# Umbrella AuditLog action for all CRM administrative events. The precise verb
# lives in details["action_type"]. Resolved lazily to avoid import-time coupling.
_UMBRELLA_ACTION = "config_changed"


def log_crm_action(
    *,
    actor,
    organization,
    action_type: str,
    resource_type: str,
    resource_id=None,
    reason: str = None,
    old_value=None,
    new_value=None,
    metadata: dict = None,
    ip_address: str = None,
    record_activity: bool = True,
):
    """
    Record a CRM administrative action to AuditLog (+ optional timeline entry).

    Returns the created ``AuditLog`` instance, or ``None`` if the write failed
    (best-effort: a logging failure must not abort the caller's transaction).

    The detailed CRM verb is stored as ``details["action_type"]``; ``reason``,
    ``old_value``, ``new_value`` and ``metadata`` are nested under ``details``.
    When ``record_activity`` is True and an organization is supplied, a
    ``crm_audit_logged`` timeline entry is also appended.
    """
    from apps.authentication.models import AuditLog

    details = {"action_type": action_type}
    if reason is not None:
        details["reason"] = reason
    if old_value is not None:
        details["old_value"] = old_value
    if new_value is not None:
        details["new_value"] = new_value
    if metadata:
        details["metadata"] = metadata

    actor_user = actor if (actor is not None and getattr(actor, "is_authenticated", False)) else None

    audit = None
    try:
        # Savepoint: this may run inside a caller's transaction.atomic() block.
        # Isolating the insert means a DB failure here rolls back only this
        # record and keeps the outer transaction usable.
        with transaction.atomic():
            audit = AuditLog.objects.create(
                user=actor_user,
                organization=organization,
                action=AuditLog.Action(_UMBRELLA_ACTION),
                resource_type=resource_type or "",
                resource_id=str(resource_id) if resource_id is not None else "",
                ip_address=ip_address,
                details=details,
            )
    except Exception as exc:
        logger.warning("log_crm_action failed to write AuditLog (%s): %s", action_type, exc)

    if record_activity and organization is not None:
        # Imported lazily to keep this module importable without the model graph.
        from apps.platform_admin.models import CustomerActivity
        from apps.platform_admin.services.crm_activity import record_customer_activity

        record_customer_activity(
            organization=organization,
            actor=actor_user,
            activity_type=CustomerActivity.ActivityType.CRM_AUDIT_LOGGED,
            description=f"CRM action logged: {action_type}",
            metadata={"action_type": action_type, "resource_type": resource_type},
        )

    return audit
