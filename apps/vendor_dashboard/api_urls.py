"""Vendor dashboard API URL configuration."""

from django.urls import path

from apps.audit_engine.views import AuditJobViewSet
from apps.documents import views as document_views
from apps.reports import views as report_views

from . import api_views

app_name = "vendor_dashboard_api"

audit_job_run = AuditJobViewSet.as_view({"post": "run"})

urlpatterns = [
    path("stats/", api_views.VendorDashboardStatsView.as_view(), name="stats"),
    path("activity/", api_views.VendorActivityFeedView.as_view(), name="activity"),
    path("organization/", api_views.VendorOrganizationView.as_view(), name="organization"),
    path("storage/stats/", api_views.VendorStorageStatsView.as_view(), name="storage-stats"),
    path("files/", document_views.DocumentListView.as_view(), name="files"),
    path("files/upload/", document_views.DocumentUploadView.as_view(), name="file-upload"),
    path("files/<uuid:pk>/", document_views.DocumentDetailView.as_view(), name="file-detail"),
    path("folders/", api_views.VendorFolderRootView.as_view(), name="folders"),
    path("folders/<uuid:pk>/", api_views.VendorFolderDetailView.as_view(), name="folder-detail"),
    path("folders/<uuid:pk>/contents/", api_views.VendorFolderContentsView.as_view(), name="folder-contents"),
    path("audits/jobs/", api_views.VendorAuditJobListView.as_view(), name="audit-jobs"),
    path("audits/jobs/stats/", api_views.VendorAuditJobStatsView.as_view(), name="audit-job-stats"),
    path("audits/jobs/run/", audit_job_run, name="audit-job-run"),
    path("audits/results/", api_views.VendorAuditResultListView.as_view(), name="audit-results"),
    path("account/change-password/", api_views.VendorChangePasswordView.as_view(), name="change-password"),
    path("account/sessions/", api_views.VendorSessionListView.as_view(), name="sessions"),
    path("account/sessions/<str:pk>/", api_views.VendorSessionDetailView.as_view(), name="session-detail"),
    path("account/notification-preferences/", api_views.VendorNotificationPreferencesView.as_view(), name="notification-preferences"),
    path("team/members/", api_views.VendorTeamMemberListView.as_view(), name="team-members"),
    path("team/members/<uuid:pk>/", api_views.VendorTeamMemberDetailView.as_view(), name="team-member-detail"),
    path("team/invitations/", api_views.VendorInvitationListView.as_view(), name="team-invitations"),
    path("team/invitations/<str:pk>/", api_views.VendorInvitationActionView.as_view(), name="team-invitation-detail"),
    path("team/invitations/<str:pk>/resend/", api_views.VendorInvitationActionView.as_view(), name="team-invitation-resend"),
    path("team/invite/", api_views.VendorInviteView.as_view(), name="team-invite"),
    path("notifications/", api_views.VendorNotificationsView.as_view(), name="notifications"),
    path("notifications/unread-count/", api_views.VendorNotificationsUnreadCountView.as_view(), name="notifications-unread-count"),
    path("notifications/<str:pk>/mark-read/", api_views.VendorNotificationMarkReadView.as_view(), name="notification-mark-read"),
    path("notifications/mark-all-read/", api_views.VendorNotificationMarkAllReadView.as_view(), name="notifications-mark-all-read"),
    path("notifications/<str:pk>/", api_views.VendorNotificationDeleteView.as_view(), name="notification-delete"),
    path("billing/subscription/", api_views.VendorBillingSubscriptionView.as_view(), name="billing-subscription"),
    path("billing/subscription/cancel/", api_views.VendorBillingCancelView.as_view(), name="billing-subscription-cancel"),
    path("billing/usage/", api_views.VendorBillingUsageView.as_view(), name="billing-usage"),
    path("billing/invoices/", api_views.VendorBillingInvoiceListView.as_view(), name="billing-invoices"),
    path("reports/", report_views.ReportListView.as_view(), name="reports"),
    path("reports/<uuid:pk>/", report_views.ReportDetailView.as_view(), name="report-detail"),
    path("reports/<uuid:pk>/download/", report_views.ReportPDFView.as_view(), name="report-download"),
]
