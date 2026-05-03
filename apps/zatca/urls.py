from django.urls import path

from . import views as v

urlpatterns = [
    path("dashboard/",                     v.ComplianceDashboardView.as_view(), name="zatca-dashboard"),
    path("devices/",                       v.DeviceListCreateView.as_view(),    name="zatca-device-list"),
    path("devices/<uuid:pk>/renew/",       v.DeviceRenewView.as_view(),         name="zatca-device-renew"),
    path("submissions/",                   v.SubmissionListView.as_view(),      name="zatca-submission-list"),
    path("submissions/submit/",            v.SubmitInvoiceView.as_view(),       name="zatca-submission-submit"),
]
