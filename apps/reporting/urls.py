from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.reporting.views import ReportViewSet
from apps.reporting.dashboard_views import DashboardMetricsView, RecentActivityView

router = DefaultRouter()
router.register("reports", ReportViewSet, basename="report")

urlpatterns = [
    path("", include(router.urls)),
    path("dashboard/metrics/", DashboardMetricsView.as_view(), name="dashboard-metrics"),
    path("dashboard/activity/", RecentActivityView.as_view(), name="dashboard-activity"),
]
