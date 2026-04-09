"""
core/utils/audit.py
===================
Audit trail logging helpers.

Provides:
  log_action              — writes to AuditLog (platform-level action log)
  record_invoice_event    — writes to InvoiceAuditEvent (per-invoice trail)

Previously, record_invoice_event was duplicated as:
  - _save_audit_event() in apps/invoices/views.py
  - InvoiceValidationService._save_audit_event() in apps/invoices/services/validation_service.py

Both callers now import from here.
"""

import logging

from core.utils.coerce import get_client_ip

logger = logging.getLogger("finai")


def log_action(request, action: str, resource_type: str = "", resource_id: str = "", details: dict = None):
    """Log an auditable action to the AuditLog model."""
    try:
        from apps.authentication.models import AuditLog
        AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            organization=getattr(request.user, "organization", None),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            details=details or {},
        )
    except Exception as e:
        logger.warning("Failed to log audit action %s: %s", action, e)


def record_invoice_event(
    invoice,
    user,
    event_type: str,
    description: str = "",
    before: dict = None,
    after: dict = None,
    request=None,
) -> None:
    """
    Persist an :class:`~apps.invoices.models.InvoiceAuditEvent` record.

    This is the single canonical implementation.  Replaces the two
    ``_save_audit_event`` helpers that previously existed in
    ``apps/invoices/views.py`` and
    ``apps/invoices/services/validation_service.py``.

    Args:
        invoice:     Invoice model instance.
        user:        User performing the action (may be None for system events).
        event_type:  One of ``InvoiceAuditEvent.EventType`` choices.
        description: Human-readable summary of what happened.
        before:      Snapshot of relevant fields before the change.
        after:       Snapshot of relevant fields after the change.
        request:     Optional Django request — used to extract the client IP.
    """
    try:
        from apps.invoices.models import InvoiceAuditEvent

        ip = get_client_ip(request) if request else None

        InvoiceAuditEvent.objects.create(
            invoice=invoice,
            user=user,
            event_type=event_type,
            description=description,
            before_data=before or {},
            after_data=after or {},
            ip_address=ip,
        )
    except Exception as exc:
        logger.warning(
            "Failed to record invoice audit event %s for invoice %s: %s",
            event_type,
            getattr(invoice, "id", "?"),
            exc,
        )


# ── Internal helper kept for backward compatibility ───────────────────────────

def _get_client_ip(request) -> str:
    """Deprecated: use core.utils.coerce.get_client_ip instead."""
    return get_client_ip(request)
