from django.urls import path

from . import views as v

urlpatterns = [
    # Connections
    path("connections/",                        v.ConnectionListCreateView.as_view(), name="bank-conn-list"),
    path("connections/<uuid:pk>/sync/",         v.ConnectionSyncView.as_view(),       name="bank-conn-sync"),

    # Transactions + reconciliation
    path("transactions/",                       v.TransactionListView.as_view(),      name="bank-tx-list"),
    path("reconciliations/",                    v.ReconciliationListView.as_view(),   name="bank-recon-list"),
    path("reconciliations/run/",                v.ReconciliationRunView.as_view(),    name="bank-recon-run"),
    path("reconciliations/<uuid:pk>/action/",   v.ReconciliationActionView.as_view(), name="bank-recon-action"),

    # Statement upload fallback
    path("accounts/<uuid:pk>/statement/",       v.StatementUploadView.as_view(),      name="bank-statement-upload"),
]
