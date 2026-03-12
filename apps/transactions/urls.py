"""Transactions URLs"""
from django.urls import path
from . import views

urlpatterns = [
    path("", views.TransactionListCreateView.as_view(), name="transaction-list"),
    path("<uuid:pk>/", views.TransactionDetailView.as_view(), name="transaction-detail"),
    path("bulk-import/", views.BulkImportView.as_view(), name="bulk-import"),
    path("journal-entries/", views.JournalEntryListView.as_view(), name="journal-list"),
    path("stats/", views.TransactionStatsView.as_view(), name="transaction-stats"),
]
