from django.urls import path
from . import views

app_name = "rule_engine"

urlpatterns = [
    path("rules/", views.RuleLibraryView.as_view(), name="rule-library"),
    path("runs/", views.AuditRunListView.as_view(), name="audit-runs"),
    path("runs/<pk>/", views.AuditRunDetailView.as_view(), name="audit-run-detail"),
    path("risk/<uuid:document_id>/", views.RiskSummaryView.as_view(), name="risk-summary"),
    path("high-risk/", views.HighRiskDocumentsView.as_view(), name="high-risk-documents"),
    path("trigger/", views.trigger_audit, name="trigger-audit"),
    path("analytics/top-failures/", views.top_failed_rules, name="top-failed-rules"),
]
