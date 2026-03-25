from django.urls import path

from .views import (
    AdminApplicationDeleteView,
    AdminApplicationDetailView,
    AdminApplicationListView,
    AdminJobCloseView,
    AdminJobDetailView,
    AdminJobListView,
    AdminJobPublishView,
    JobStatsView,
    PublicJobApplyView,
    PublicJobDetailView,
    PublicJobListView,
)

app_name = 'jobs'

urlpatterns = [
    # ── Admin ──────────────────────────────────────────────────────────────
    path('admin/jobs/', AdminJobListView.as_view(), name='admin-job-list'),
    path('admin/jobs/<uuid:pk>/', AdminJobDetailView.as_view(), name='admin-job-detail'),
    path('admin/jobs/<uuid:pk>/publish/', AdminJobPublishView.as_view(), name='admin-job-publish'),
    path('admin/jobs/<uuid:pk>/close/', AdminJobCloseView.as_view(), name='admin-job-close'),
    path('admin/applications/', AdminApplicationListView.as_view(), name='admin-application-list'),
    path('admin/applications/<uuid:pk>/', AdminApplicationDetailView.as_view(), name='admin-application-detail'),
    path('admin/applications/<uuid:pk>/delete/', AdminApplicationDeleteView.as_view(), name='admin-application-delete'),
    path('admin/stats/', JobStatsView.as_view(), name='admin-job-stats'),

    # ── Public ─────────────────────────────────────────────────────────────
    path('public/jobs/', PublicJobListView.as_view(), name='public-job-list'),
    path('public/jobs/<uuid:pk>/', PublicJobDetailView.as_view(), name='public-job-detail'),
    path('public/jobs/<uuid:pk>/apply/', PublicJobApplyView.as_view(), name='public-job-apply'),
]
