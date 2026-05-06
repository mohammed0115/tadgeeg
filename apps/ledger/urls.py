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

    # Phase 7.2 — accounting periods
    path("periods/",                           v.PeriodListCreateView.as_view(),    name="ledger-periods"),
    path("periods/<uuid:pk>/close/",           v.PeriodCloseView.as_view(),         name="ledger-period-close"),
    path("periods/<uuid:pk>/reopen/",          v.PeriodReopenView.as_view(),        name="ledger-period-reopen"),
    path("periods/<uuid:pk>/lock/",            v.PeriodLockView.as_view(),          name="ledger-period-lock"),

    # Phase 7.4 — multi-jurisdiction tax engine
    path("tax/jurisdictions/",                 v.TaxJurisdictionsView.as_view(),    name="ledger-tax-jurisdictions"),
    path("tax/validate/",                      v.TaxValidateView.as_view(),         name="ledger-tax-validate"),
    path("tax/compute/",                       v.TaxComputeView.as_view(),          name="ledger-tax-compute"),
]
