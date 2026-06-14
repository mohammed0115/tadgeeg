"""
CRM customer timeline writer (CRM-1B).

``CustomerActivity`` is a display-only timeline for the CRM. It complements,
and never replaces, the formal ``AuditLog`` security record.
"""

import logging

logger = logging.getLogger("finai")


def _normalize_actor(actor):
    """Return a persistable actor or None (drops AnonymousUser / unauth)."""
    if actor is not None and getattr(actor, "is_authenticated", False):
        return actor
    return None


def record_customer_activity(
    *,
    organization,
    activity_type,
    actor=None,
    description: str = "",
    metadata: dict = None,
):
    """
    Append a row to the customer's CRM timeline.

    Best-effort by design: a timeline failure must never break the caller's
    primary action, so the write is wrapped and logged rather than raised.
    Returns the created ``CustomerActivity`` or ``None`` on failure.
    """
    from apps.platform_admin.models import CustomerActivity

    if organization is None:
        return None
    try:
        return CustomerActivity.objects.create(
            organization=organization,
            actor=_normalize_actor(actor),
            activity_type=activity_type,
            description=description or "",
            metadata=metadata or {},
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Failed to record CustomerActivity (%s) for org %s: %s",
            activity_type,
            getattr(organization, "id", "?"),
            exc,
        )
        return None
