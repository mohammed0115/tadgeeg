"""Authentication URL patterns"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("google/", views.GoogleLoginView.as_view(), name="google-login"),
    path("otp/verify/", views.EmailOTPVerifyView.as_view(), name="otp-verify"),
    path("otp/resend/", views.EmailOTPResendView.as_view(), name="otp-resend"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", views.MeView.as_view(), name="me"),
    path("me/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/<uuid:pk>/", views.UserDetailView.as_view(), name="user-detail"),
    path("users/<uuid:pk>/set-password/", views.SetPasswordView.as_view(), name="user-set-password"),
    path("organizations/", views.OrganizationListView.as_view(), name="organization-list"),
    path("organizations/<uuid:pk>/", views.OrganizationDetailView.as_view(), name="organization-detail"),
    path("organization/", views.CurrentOrganizationView.as_view(), name="current-organization"),
    path("organization/settings/", views.OrganizationSettingsView.as_view(), name="current-organization-settings"),
    path("audit-logs/", views.AuditLogListView.as_view(), name="audit-log-list"),
    path("mfa/setup/", views.MFASetupView.as_view(), name="mfa-setup"),
    path("mfa/verify/", views.MFAVerifyView.as_view(), name="mfa-verify"),
    path("mfa/disable/", views.MFADisableView.as_view(), name="mfa-disable"),
]
