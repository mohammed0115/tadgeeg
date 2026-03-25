from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.reporting.dashboard_selectors import (
    get_admin_dashboard_metrics,
    get_org_dashboard_metrics,
    get_recent_activity,
)


class DashboardMetricsView(APIView):
    """Return KPI metrics for the requesting user's organisation.

    Staff / superuser users receive global (cross-org) metrics.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        org = getattr(user, "organization", None)

        if user.is_staff or user.is_superuser or org is None:
            metrics = get_admin_dashboard_metrics()
        else:
            metrics = get_org_dashboard_metrics(org)

        return Response(metrics)


class RecentActivityView(APIView):
    """Return the most recent activity log entries for the user's organisation.

    Query params
    ------------
    limit : int (default 10, max 100)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)

        try:
            limit = min(int(request.query_params.get("limit", 10)), 100)
        except (TypeError, ValueError):
            limit = 10

        activity = get_recent_activity(org, limit=limit) if org else []
        return Response({"results": activity})
