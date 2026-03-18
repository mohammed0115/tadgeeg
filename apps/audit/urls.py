from django.urls import path
from . import views
urlpatterns = [
    path("dashboard/overview/", views.AuditDashboardOverviewView.as_view(), name="dashboard-overview"),
    path("sessions/<uuid:pk>/", views.AuditSessionDetailView.as_view(), name="session-detail"),
    path("sessions/<uuid:pk>/progress/", views.AuditSessionProgressView.as_view(), name="session-progress"),
    path("sessions/<uuid:pk>/findings/", views.AuditSessionFindingsView.as_view(), name="session-findings"),
    path("cases/", views.AuditCaseListCreateView.as_view(), name="case-list"),
    path("cases/<uuid:pk>/", views.AuditCaseDetailView.as_view(), name="case-detail"),
    path("cases/<uuid:pk>/comments/", views.CaseCommentView.as_view(), name="case-comments"),
    path("cases/<uuid:pk>/status/", views.UpdateCaseStatusView.as_view(), name="case-status"),
    path("cases/<uuid:pk>/assign/", views.AssignCaseView.as_view(), name="case-assign"),
    path("<uuid:pk>/", views.AuditCaseDetailView.as_view(), name="case-detail-compat"),
    path("<uuid:pk>/update-status/", views.UpdateCaseStatusView.as_view(), name="case-status-compat"),
    path("<uuid:pk>/assign/", views.AssignCaseView.as_view(), name="case-assign-compat"),
]
