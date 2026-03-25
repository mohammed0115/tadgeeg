from __future__ import annotations

from typing import Optional

from apps.activity_logs.models import ActivityLog


class ActivityLogService:
    """Service layer for creating activity log entries."""

    @classmethod
    def log(
        cls,
        action: str,
        user=None,
        organization=None,
        entity_type: str = "",
        entity_id: str = "",
        description: str = "",
        metadata: Optional[dict] = None,
        request=None,
    ) -> ActivityLog:
        """
        Create an activity log entry.

        If ``request`` is provided its IP address is extracted automatically,
        preferring the ``X-Forwarded-For`` header (first hop) over
        ``REMOTE_ADDR``.  The ``organization`` argument takes precedence; if it
        is omitted the user's own ``organization`` FK is used as a fallback.
        """
        ip: Optional[str] = None
        if request is not None:
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")

        resolved_org = organization or (
            getattr(user, "organization", None) if user is not None else None
        )

        return ActivityLog.objects.create(
            action=action,
            user=user,
            organization=resolved_org,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else "",
            description=description,
            metadata=metadata or {},
            ip_address=ip,
        )
