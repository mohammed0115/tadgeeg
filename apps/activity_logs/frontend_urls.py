"""Frontend URL patterns for activity logs."""
from django.urls import path
from apps.activity_logs import frontend_views as views

urlpatterns = [
    path("", views.activity, name="activity_logs"),
]
