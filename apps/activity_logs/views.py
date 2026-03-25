from __future__ import annotations

from django.utils.dateparse import parse_datetime

from rest_framework import status
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.activity_logs.models import ActivityLog
from apps.activity_logs.serializers import ActivityLogSerializer


class ActivityLogViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    """Read-only viewset for activity logs.

    * Staff users see all logs (useful for support / admin).
    * Regular users see only logs scoped to their own organisation.

    Supported query parameters
    --------------------------
    action       : exact match on the ``action`` field
    entity_type  : exact match on the ``entity_type`` field
    date_from    : ISO-8601 datetime — lower bound on ``created_at``
    date_to      : ISO-8601 datetime — upper bound on ``created_at``
    """

    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]
    ordering = ["-created_at"]

    # ------------------------------------------------------------------ #
    # Queryset
    # ------------------------------------------------------------------ #

    def get_queryset(self):
        user = self.request.user
        qs = (
            ActivityLog.objects.select_related("user", "organization")
            .order_by("-created_at")
        )

        if not user.is_staff:
            org = getattr(user, "organization", None)
            if org is None:
                return qs.none()
            qs = qs.filter(organization=org)

        # ── Optional filters ──────────────────────────────────────────
        params = self.request.query_params

        action = params.get("action")
        if action:
            qs = qs.filter(action=action)

        entity_type = params.get("entity_type")
        if entity_type:
            qs = qs.filter(entity_type=entity_type)

        date_from = params.get("date_from")
        if date_from:
            parsed = parse_datetime(date_from)
            if parsed:
                qs = qs.filter(created_at__gte=parsed)

        date_to = params.get("date_to")
        if date_to:
            parsed = parse_datetime(date_to)
            if parsed:
                qs = qs.filter(created_at__lte=parsed)

        return qs
