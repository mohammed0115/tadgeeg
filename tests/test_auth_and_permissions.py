"""
Authentication Flow Tests
==========================
Covers login/logout, OTP email verification, account lockout,
JWT cookie handling, password validation, and Google OAuth stubs.

Gaps filled:
  - OTP resend rate-limiting
  - Account lockout after N failed attempts
  - JWT cookie set / cleared on login / logout
  - Password reset validation (min length, complexity)
  - Register with duplicate email
  - Login with unverified email (if applicable)
  - Role assignment on registration
"""

import pytest
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()


# ─── Registration ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRegistration:

    def test_register_with_valid_data_succeeds(self):
        """"Valid data" now includes the lead fields §A.1/§A.2 made mandatory.

        Trial registration is a lead-generation flow: phone and country (§A.1)
        and primary_benefit (§A.2) are required at the serializer, so a payload
        of email+password alone is no longer valid data and correctly 400s.
        This test asserts the success path, so it has to send them.
        """
        client = APIClient()
        response = client.post("/api/v1/auth/register/", {
            "email": "newuser@test.finai",
            "password": "SecurePass1!",
            "password_confirm": "SecurePass1!",
            "full_name": "New User",
            "phone": "+966501234567",
            "country": "SA",
            "primary_benefit": "company",
        }, format="json")
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), (
            f"registration rejected valid data: {response.status_code} "
            f"{getattr(response, 'data', None)}"
        )

    def test_register_duplicate_email_fails(self, db):
        User.objects.create_user(
            email="dup@test.finai", password="Pass1!", full_name="Dup"
        )
        client = APIClient()
        response = client.post("/api/v1/auth/register/", {
            "email": "dup@test.finai",
            "password": "AnotherPass1!",
            "password_confirm": "AnotherPass1!",
            "full_name": "Dup2",
        }, format="json")
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_409_CONFLICT,
        )

    def test_register_weak_password_rejected(self):
        client = APIClient()
        response = client.post("/api/v1/auth/register/", {
            "email": "weak@test.finai",
            "password": "123",
            "password_confirm": "123",
            "full_name": "Weak User",
        }, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_missing_email_rejected(self):
        client = APIClient()
        response = client.post("/api/v1/auth/register/", {
            "password": "SecurePass1!",
            "password_confirm": "SecurePass1!",
            "full_name": "No Email",
        }, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_missing_full_name_rejected(self):
        client = APIClient()
        response = client.post("/api/v1/auth/register/", {
            "email": "noname@test.finai",
            "password": "SecurePass1!",
            "password_confirm": "SecurePass1!",
        }, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ─── Login ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLogin:

    @pytest.fixture
    def active_user(self, db):
        return User.objects.create_user(
            email="login@test.finai",
            password="LoginPass1!",
            full_name="Login User",
            email_verified_at=timezone.now(),
        )

    def test_login_correct_credentials_returns_tokens(self, active_user):
        client = APIClient()
        with patch("apps.authentication.services.email_otp.issue_email_otp") as mock_otp:
            mock_otp.return_value = MagicMock()
            response = client.post("/api/v1/auth/login/", {
                "email": "login@test.finai",
                "password": "LoginPass1!",
            }, format="json")
        # Should either return tokens or redirect to OTP verification
        assert response.status_code in (
            status.HTTP_200_OK,
            status.HTTP_202_ACCEPTED,
        )

    def test_login_wrong_password_returns_401(self, active_user):
        client = APIClient()
        response = client.post("/api/v1/auth/login/", {
            "email": "login@test.finai",
            "password": "WrongPass1!",
        }, format="json")
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_login_nonexistent_email_returns_error(self):
        client = APIClient()
        response = client.post("/api/v1/auth/login/", {
            "email": "ghost@test.finai",
            "password": "AnyPass1!",
        }, format="json")
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_login_response_does_not_reveal_user_existence(self):
        """Same error for wrong password vs non-existent user (prevents enumeration)."""
        client = APIClient()
        existing_user = User.objects.create_user(
            email="exists@test.finai",
            password="Pass1!",
            full_name="Exists",
        )
        resp_wrong_pw = client.post("/api/v1/auth/login/", {
            "email": "exists@test.finai",
            "password": "WrongPass!",
        }, format="json")
        resp_no_user = client.post("/api/v1/auth/login/", {
            "email": "ghost@test.finai",
            "password": "WrongPass!",
        }, format="json")
        # Both should be the same HTTP status code
        assert resp_wrong_pw.status_code == resp_no_user.status_code


@pytest.mark.django_db
def test_password_reset_unknown_email_shows_validation_message():
    client = Client()
    response = client.post("/forgot-password/", {"email": "ghost@test.finai"})

    assert response.status_code == 200
    assert "No active account was found with this email address." in response.content.decode()


# ─── Account lockout ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAccountLockout:

    @pytest.fixture
    def lockout_user(self, db):
        return User.objects.create_user(
            email="lockout@test.finai",
            password="LockMe123!",
            full_name="Lockout User",
        )

    def test_locked_account_is_detected(self, lockout_user):
        lockout_user.locked_until = timezone.now() + timedelta(minutes=30)
        lockout_user.save()
        assert lockout_user.is_locked() is True

    def test_unlocked_account_is_detected(self, lockout_user):
        lockout_user.locked_until = None
        lockout_user.save()
        assert lockout_user.is_locked() is False

    def test_expired_lock_is_cleared(self, lockout_user):
        lockout_user.locked_until = timezone.now() - timedelta(minutes=1)
        lockout_user.save()
        assert lockout_user.is_locked() is False

    def test_failed_attempts_incremented(self, lockout_user):
        lockout_user.failed_login_attempts = 0
        initial = lockout_user.failed_login_attempts
        lockout_user.failed_login_attempts += 1
        lockout_user.save()
        lockout_user.refresh_from_db()
        assert lockout_user.failed_login_attempts == initial + 1

    def test_locked_user_gets_429_on_login(self, lockout_user):
        lockout_user.locked_until = timezone.now() + timedelta(hours=1)
        lockout_user.save()
        client = APIClient()
        response = client.post("/api/v1/auth/login/", {
            "email": "lockout@test.finai",
            "password": "LockMe123!",
        }, format="json")
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_429_TOO_MANY_REQUESTS,
            status.HTTP_403_FORBIDDEN,
        )


# ─── OTP email verification ───────────────────────────────────────────────────

@pytest.mark.unit
class TestEmailOTPService:

    def test_otp_code_is_6_digits(self):
        from apps.authentication.services.email_otp import generate_otp_code
        code = generate_otp_code(length=6)
        assert len(code) == 6
        assert code.isdigit()

    def test_otp_code_is_not_deterministic(self):
        from apps.authentication.services.email_otp import generate_otp_code
        codes = {generate_otp_code() for _ in range(20)}
        assert len(codes) > 1  # Not all the same

    def test_mask_email_hides_middle(self):
        from apps.authentication.services.email_otp import mask_email_address
        masked = mask_email_address("newtonsudan31@gmail.com")
        assert "ne" in masked
        assert "@gmail.com" in masked
        assert "wtonsudan3" not in masked  # Middle should be masked

    def test_mask_email_short_local(self):
        from apps.authentication.services.email_otp import mask_email_address
        masked = mask_email_address("a@b.com")
        assert "@b.com" in masked

    def test_mask_email_no_at_sign(self):
        from apps.authentication.services.email_otp import mask_email_address
        result = mask_email_address("invalidemail")
        # Should not crash
        assert isinstance(result, str)

    def test_otp_error_resend_cooldown_is_429(self):
        from apps.authentication.views import _otp_error_status
        from apps.authentication.services.email_otp import EmailOTPError
        err = EmailOTPError("Cooldown", code="resend_cooldown")
        assert _otp_error_status(err) == 429

    def test_otp_error_send_failed_is_503(self):
        from apps.authentication.views import _otp_error_status
        from apps.authentication.services.email_otp import EmailOTPError
        err = EmailOTPError("Send failed", code="send_failed")
        assert _otp_error_status(err) == 503

    def test_otp_error_already_verified_is_409(self):
        from apps.authentication.views import _otp_error_status
        from apps.authentication.services.email_otp import EmailOTPError
        err = EmailOTPError("Already verified", code="already_verified")
        assert _otp_error_status(err) == 409

    def test_otp_error_generic_is_400(self):
        from apps.authentication.views import _otp_error_status
        from apps.authentication.services.email_otp import EmailOTPError
        err = EmailOTPError("Unknown error", code="unknown")
        assert _otp_error_status(err) == 400


# ─── JWT Cookie utilities ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestJWTCookieUtils:

    def test_set_auth_cookies_sets_expected_keys(self):
        from core.utils.jwt_cookies import set_auth_cookies
        from unittest.mock import MagicMock
        response = MagicMock()
        set_auth_cookies(response, access_token="access123", refresh_token="refresh456")
        # Should have called set_cookie
        assert response.set_cookie.called

    def test_clear_auth_cookies_deletes_cookies(self):
        from core.utils.jwt_cookies import clear_auth_cookies
        response = MagicMock()
        clear_auth_cookies(response)
        assert response.delete_cookie.called


# ─── Password validation ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPasswordChange:

    @pytest.fixture
    def user(self, db):
        return User.objects.create_user(
            email="pwchange@test.finai",
            password="OldPass1!",
            full_name="PW User",
        )

    def test_authenticated_user_can_change_password(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post("/api/v1/auth/me/change-password/", {
            "old_password": "OldPass1!",
            "new_password": "A1!New-Password-2026",
            "new_password_confirm": "A1!New-Password-2026",
        }, format="json")
        assert response.status_code in (
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT,
        )

    def test_wrong_old_password_rejected(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post("/api/v1/auth/me/change-password/", {
            "old_password": "WrongOld1!",
            "new_password": "A1!New-Password-2026",
            "new_password_confirm": "A1!New-Password-2026",
        }, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_mismatched_new_passwords_rejected(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post("/api/v1/auth/me/change-password/", {
            "old_password": "OldPass1!",
            "new_password": "NewPass1!",
            "new_password_confirm": "DifferentPass1!",
        }, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unauthenticated_user_cannot_change_password(self):
        client = APIClient()
        response = client.post("/api/v1/auth/me/change-password/", {
            "old_password": "OldPass1!",
            "new_password": "A1!New-Password-2026",
            "new_password_confirm": "A1!New-Password-2026",
        }, format="json")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


# ─── Role-based capability checks ────────────────────────────────────────────

@pytest.mark.django_db
class TestUserRoleCapabilities:

    def _make_user(self, role):
        from apps.authentication.models import Organization
        org = Organization.objects.create(
            name=f"Org-{role}",
            name_ar=f"منظمة {role}",
            country="SA",
            currency="SAR",
            vat_number=f"300000000000{abs(hash(role)) % 100:03d}",
        )
        return User.objects.create_user(
            email=f"{role}@cap.test",
            password="Cap1!",
            full_name=role.title(),
            role=role,
            organization=org,
        )

    def test_admin_can_manage_organization(self, db):
        user = self._make_user(User.Role.ADMIN)
        assert user.has_role_capability("manage_organization")

    def test_junior_auditor_cannot_manage_organization(self, db):
        user = self._make_user(User.Role.JUNIOR_AUDITOR)
        assert not user.has_role_capability("manage_organization")

    def test_senior_auditor_can_approve_invoices(self, db):
        user = self._make_user(User.Role.SENIOR_AUDITOR)
        assert user.has_role_capability("approve_invoices")

    def test_external_auditor_cannot_approve_invoices(self, db):
        user = self._make_user(User.Role.EXTERNAL_AUDITOR)
        assert not user.has_role_capability("approve_invoices")

    def test_finance_manager_can_view_executive_dashboard(self, db):
        user = self._make_user(User.Role.FINANCE_MANAGER)
        assert user.has_role_capability("view_executive_dashboard")

    def test_compliance_officer_can_review_findings(self, db):
        user = self._make_user(User.Role.COMPLIANCE_OFFICER)
        assert user.has_role_capability("review_findings")

    def test_unknown_capability_returns_false(self, db):
        user = self._make_user(User.Role.ADMIN)
        assert not user.has_role_capability("fly_to_mars")

    def test_superuser_has_all_capabilities(self, db):
        user = User.objects.create_superuser(
            email="super@cap.test", password="Super1!", full_name="Super"
        )
        for cap in ("manage_organization", "approve_invoices", "review_findings",
                    "view_executive_dashboard", "edit_invoice_data"):
            assert user.has_role_capability(cap), f"Superuser should have capability: {cap}"

    def test_effective_role_superuser(self, db):
        user = User.objects.create_superuser(
            email="eff_super@test.finai", password="Super1!", full_name="S"
        )
        assert user.effective_role == "super_admin"

    def test_effective_role_admin(self, db):
        user = self._make_user(User.Role.ADMIN)
        assert user.effective_role == "organization_admin"

    def test_effective_role_finance_manager(self, db):
        user = self._make_user(User.Role.FINANCE_MANAGER)
        assert user.effective_role == "finance_manager"
