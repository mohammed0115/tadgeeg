"""URL config for the mobile API surface."""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.api_mobile import views as v


urlpatterns = [
    # Auth
    path("auth/login/",          v.MobileLoginView.as_view(),    name="mobile-login"),
    path("auth/refresh/",        TokenRefreshView.as_view(),     name="mobile-refresh"),
    path("auth/logout/",         v.MobileLogoutView.as_view(),   name="mobile-logout"),

    # Devices + biometric
    path("devices/register/",    v.MobileDeviceRegisterView.as_view(),  name="mobile-device-register"),
    path("devices/biometric/",   v.MobileBiometricRegisterView.as_view(), name="mobile-biometric"),

    # Inbox + actions
    path("inbox/",                                     v.MobileInboxView.as_view(),         name="mobile-inbox"),
    path("invoices/<uuid:pk>/<str:action>/",           v.MobileInvoiceActionView.as_view(), name="mobile-invoice-action"),

    # Captures
    path("captures/",            v.MobileCaptureView.as_view(),  name="mobile-capture"),
]
