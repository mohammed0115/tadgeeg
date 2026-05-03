from django.urls import path

from . import views as v


urlpatterns = [
    path("accounts/",                          v.AccountListView.as_view(),         name="ledger-accounts"),
    path("entries/",                           v.JournalEntryListCreateView.as_view(), name="ledger-entries"),
    path("entries/<uuid:pk>/",                 v.JournalEntryDetailView.as_view(),  name="ledger-entry-detail"),
    path("entries/<uuid:pk>/void/",            v.JournalEntryVoidView.as_view(),    name="ledger-entry-void"),
    path("post-invoice/",                      v.PostInvoiceToGLView.as_view(),     name="ledger-post-invoice"),
    path("trial-balance/",                     v.TrialBalanceView.as_view(),        name="ledger-trial-balance"),
    path("general-ledger/<str:code>/",         v.GeneralLedgerView.as_view(),       name="ledger-general"),
    path("exchange-rates/",                    v.ExchangeRateView.as_view(),        name="ledger-fx-rates"),
]
