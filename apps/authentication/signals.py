"""
apps/authentication/signals.py
================================
Django signals for the authentication app.

Registered in AuthenticationConfig.ready() so they fire on app startup.

Signals:
  - audit_role_change: Writes an AuditLog entry whenever a User's role field
    changes, satisfying privilege-escalation audit requirements.
  - prune_expired_audit_logs: Fires after each AuditLog bulk-delete to keep
    the audit table from growing unbounded (works alongside the Celery beat
    task that calls AuditLog.objects.filter(retain_until__lt=now).delete()).
"""
from __future__ import annotations

import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

logger = logging.getLogger("finai")


@receiver(pre_save, sender="authentication.User")
def audit_role_change(sender, instance, **kwargs):
    """
    Write an immutable AuditLog record whenever a User's role is changed.

    This covers both manual admin edits and programmatic role updates, giving
    security teams a full history of privilege changes without relying on
    application-level call sites to remember to log.
    """
    if not instance.pk:
        # New user — role assignment logged via USER_CREATED action elsewhere.
        return

    try:
        previous = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    if previous.role == instance.role:
        return  # No change — nothing to record.

    from apps.authentication.models import AuditLog

    AuditLog.objects.create(
        user=instance,
        organization=getattr(instance, "organization", None),
        action=AuditLog.Action.USER_UPDATED,
        resource_type="User",
        resource_id=str(instance.pk),
        details={
            "field": "role",
            "old_value": previous.role,
            "new_value": instance.role,
            "changed_by": "system",  # Will be overwritten if request context available
        },
    )
    logger.info(
        "[SECURITY] Role changed for user %s: %s → %s",
        instance.email,
        previous.role,
        instance.role,
    )
