"""Frontend URL patterns for audit engine."""
from django.urls import path
from apps.audit_engine import frontend_views as views

urlpatterns = [
    path("", views.audit_jobs, name="audit_jobs"),
    path("<uuid:job_id>/result/", views.audit_result, name="audit_result"),
]
