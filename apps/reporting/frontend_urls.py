"""Frontend (template) URL patterns for Phase 2 reporting dashboard."""
from django.urls import path
from apps.reporting import frontend_views as views

app_name = "phase2"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("reports/", views.reports, name="reports"),
]
