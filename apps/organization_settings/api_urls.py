"""Organization and account settings URLs."""

from django.urls import path

from . import api_views

urlpatterns = [
    path("organization/", api_views.VendorOrganizationView.as_view(), name="organization"),
    path("account/change-password/", api_views.VendorChangePasswordView.as_view(), name="change-password"),
    path("account/sessions/", api_views.VendorSessionListView.as_view(), name="sessions"),
    path("account/sessions/<str:pk>/", api_views.VendorSessionDetailView.as_view(), name="session-detail"),
    path("account/notification-preferences/", api_views.VendorNotificationPreferencesView.as_view(), name="notification-preferences"),
]
