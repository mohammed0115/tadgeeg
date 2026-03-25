"""Platform monitoring URLs."""

from django.urls import path

from . import api_views

urlpatterns = [
    path("health/", api_views.PlatformMonitoringHealthView.as_view(), name="health"),
    path("metrics/", api_views.PlatformMonitoringMetricsView.as_view(), name="metrics"),
    path("errors/", api_views.PlatformMonitoringErrorsView.as_view(), name="errors"),
]
