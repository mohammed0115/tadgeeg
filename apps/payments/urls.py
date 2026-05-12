from django.urls import path

from apps.payments import views


app_name = "payments"

urlpatterns = [
    # API endpoints
    path("create/",                  views.CreatePaymentView.as_view(),  name="create"),
    path("<uuid:pk>/",               views.PaymentDetailView.as_view(),  name="detail"),
    path("<uuid:pk>/sync/",          views.PaymentSyncView.as_view(),    name="sync"),
    path("<uuid:pk>/refund/",        views.PaymentRefundView.as_view(),  name="refund"),

    # Provider webhooks (unauthenticated; verified via signature inside the adapter)
    path("webhooks/moyasar/",        views.webhook_moyasar,              name="webhook-moyasar"),
    path("webhooks/tap/",            views.webhook_tap,                  name="webhook-tap"),
    path("webhooks/telr/",           views.webhook_telr,                 name="webhook-telr"),

    # Landing page after gateway redirect (does NOT confirm payment)
    path("callback/<str:provider>/", views.PaymentCallbackView.as_view(), name="callback"),
]
