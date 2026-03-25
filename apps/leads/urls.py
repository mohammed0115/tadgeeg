from django.urls import path

from .views import (
    AdminLeadAssignView,
    AdminLeadDetailView,
    AdminLeadListView,
    AdminLeadMarkReadView,
    AdminLeadNoteListView,
    AdminLeadSpamView,
    AdminLeadStatusView,
    LeadStatsView,
    PublicContactFormView,
)

app_name = 'leads'

urlpatterns = [
    # ── Admin ──────────────────────────────────────────────────────────────
    path('admin/leads/', AdminLeadListView.as_view(), name='admin-lead-list'),
    path('admin/leads/stats/', LeadStatsView.as_view(), name='admin-lead-stats'),
    path('admin/leads/<uuid:pk>/', AdminLeadDetailView.as_view(), name='admin-lead-detail'),
    path('admin/leads/<uuid:pk>/status/', AdminLeadStatusView.as_view(), name='admin-lead-status'),
    path('admin/leads/<uuid:pk>/assign/', AdminLeadAssignView.as_view(), name='admin-lead-assign'),
    path('admin/leads/<uuid:pk>/read/', AdminLeadMarkReadView.as_view(), name='admin-lead-read'),
    path('admin/leads/<uuid:pk>/notes/', AdminLeadNoteListView.as_view(), name='admin-lead-notes'),
    path('admin/leads/<uuid:pk>/spam/', AdminLeadSpamView.as_view(), name='admin-lead-spam'),

    # ── Public ─────────────────────────────────────────────────────────────
    path('public/contact/', PublicContactFormView.as_view(), name='public-contact-form'),
]
