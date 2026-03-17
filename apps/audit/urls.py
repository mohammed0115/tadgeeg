from django.urls import path
from . import views
from . import session_views

urlpatterns = [
    # ── Audit Cases ─────────────────────────────────────────────────────────
    path("cases/", views.AuditCaseListCreateView.as_view(), name="case-list"),
    path("cases/<uuid:pk>/", views.AuditCaseDetailView.as_view(), name="case-detail"),
    path("cases/<uuid:pk>/comments/", views.CaseCommentView.as_view(), name="case-comments"),
    path("cases/<uuid:pk>/status/", views.UpdateCaseStatusView.as_view(), name="case-status"),
    path("cases/<uuid:pk>/assign/", views.AssignCaseView.as_view(), name="case-assign"),
    path("<uuid:pk>/", views.AuditCaseDetailView.as_view(), name="case-detail-compat"),
    path("<uuid:pk>/update-status/", views.UpdateCaseStatusView.as_view(), name="case-status-compat"),
    path("<uuid:pk>/assign/", views.AssignCaseView.as_view(), name="case-assign-compat"),

    # ── Audit Sessions ───────────────────────────────────────────────────────
    path("sessions/", session_views.AuditSessionListView.as_view(), name="session-list"),
    path("sessions/<uuid:pk>/", session_views.AuditSessionDetailView.as_view(), name="session-detail"),
    path("sessions/<uuid:pk>/progress/", session_views.AuditSessionProgressView.as_view(), name="session-progress"),
    path("sessions/<uuid:pk>/retry/", session_views.AuditSessionRetryView.as_view(), name="session-retry"),
    path("sessions/<uuid:pk>/summary/", session_views.AuditSessionSummaryView.as_view(), name="session-summary"),
    path("sessions/<uuid:pk>/results/", session_views.AuditSessionResultsView.as_view(), name="session-results"),
    path("sessions/<uuid:pk>/risk-summary/", session_views.AuditSessionRiskSummaryView.as_view(), name="session-risk-summary"),

    # ── Audit Findings ───────────────────────────────────────────────────────
    path("findings/", session_views.AuditFindingListView.as_view(), name="finding-list"),
    path("findings/<uuid:pk>/resolve/", session_views.AuditFindingResolveView.as_view(), name="finding-resolve"),
]
