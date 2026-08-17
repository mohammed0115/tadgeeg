"""Regression tests for MFA enforcement on every token-issuance path."""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import Organization, User


@override_settings(
    GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class MFATokenIssuanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.organization = Organization.objects.create(
            name="MFA Org", country=Organization.Country.SAUDI_ARABIA
        )

    def _user(self, *, email: str, verified: bool) -> User:
        user = User.objects.create_user(
            email=email,
            password="StrongPass123!",
            full_name="MFA User",
            role=User.Role.SENIOR_AUDITOR,
            organization=self.organization,
            mfa_enabled=True,
            mfa_secret="test-mfa-secret",
        )
        if verified:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        return user

    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_google_oauth_mfa_account_receives_only_temporary_token(self, mock_verify):
        user = self._user(email="google-mfa@example.com", verified=True)
        mock_verify.return_value = {
            "email": user.email,
            "name": user.full_name,
            "email_verified": True,
        }

        response = self.client.post("/api/v1/auth/google/", {"id_token": "test"}, format="json")

        self.assertEqual(response.status_code, 202, response.content)
        payload = response.json()
        self.assertTrue(payload["mfa_required"])
        self.assertIn("temp_token", payload)
        self.assertNotIn("access", payload)
        self.assertNotIn("refresh", payload)

    def test_email_otp_mfa_account_receives_only_temporary_token(self):
        user = self._user(email="otp-mfa@example.com", verified=False)
        def mark_verified(target, _code):
            target.email_verified_at = timezone.now()
            target.save(update_fields=["email_verified_at"])

        with patch("apps.authentication.views.get_pending_verification_user", return_value=user), patch(
            "apps.authentication.views.verify_email_otp", side_effect=mark_verified
        ):
            response = self.client.post(
                "/api/v1/auth/otp/verify/", {"otp_code": "123456"}, format="json"
            )

        self.assertEqual(response.status_code, 202, response.content)
        payload = response.json()
        self.assertTrue(payload["mfa_required"])
        self.assertIn("temp_token", payload)
        self.assertNotIn("access", payload)
        self.assertNotIn("refresh", payload)
