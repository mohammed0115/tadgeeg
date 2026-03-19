"""Auditing App URL Configuration."""

from django.urls import path

from .views import AuditDocumentUploadView, AuditDocumentResultView, AuditDocumentHistoryView

app_name = "auditor"

urlpatterns = [
    path("upload/", AuditDocumentUploadView.as_view(), name="upload"),
    path("result/<uuid:pk>/", AuditDocumentResultView.as_view(), name="result"),
    path("history/", AuditDocumentHistoryView.as_view(), name="history"),
]
