"""Audit trail logging helper"""

import logging

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
            ip_address=_get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            details=details or {},
        )
    except Exception as e:
        logger.warning(f"Failed to log audit action {action}: {e}")


def _get_client_ip(request) -> str:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
