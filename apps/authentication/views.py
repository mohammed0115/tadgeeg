"""Authentication Views"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from core.utils.audit import log_action
from core.utils.jwt_cookies import set_auth_cookies, clear_auth_cookies

from .models import AuditLog, Organization, OrganizationSettings, User
from .permissions import IsAdminUser, IsSameUserOrAdmin
from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    OrganizationSerializer,
    OrganizationSettingsSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .services.email_otp import (
    EmailOTPError,
    clear_pending_verification,
    complete_verified_login,
    get_challenge_state,
    get_pending_verification_user,
    issue_email_otp,
    mask_email_address,
    resend_email_otp,
    verify_email_otp,
)
from .services.organization_setup import ensure_organization_settings, ensure_user_organization


def _is_global_admin(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))


def _is_org_admin(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "can_manage_users", False))


def _same_organization(user, obj) -> bool:
    return bool(
        getattr(user, "organization_id", None)
        and getattr(obj, "organization_id", None)
        and user.organization_id == obj.organization_id
    )


def _otp_error_status(error: EmailOTPError) -> int:
    if error.code in {"resend_cooldown", "resend_limit", "attempts_exceeded"}:
        return status.HTTP_429_TOO_MANY_REQUESTS
    if error.code == "send_failed":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error.code == "already_verified":
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _otp_pending_payload(user: User, challenge, *, sent: bool) -> dict:
    state = get_challenge_state(challenge)
    return {
        "user": UserSerializer(user).data,
        "verification_required": True,
        "redirect": reverse("frontend:otp_verify"),
        "masked_email": mask_email_address(user.email),
        "message": (
            _("A 6-digit verification code has been sent to your email address.")
            if sent
            else _("A recent verification code has already been sent. Check your email and enter the code.")
        ),
        "otp_expires_at": state["expires_at"].isoformat() if state["expires_at"] else None,
        "otp_expires_in_seconds": state["expires_in"],
        "resend_cooldown_seconds": state["resend_available_in"],
        "attempts_remaining": state["attempts_remaining"],
        "needs_org": user.organization is None,
    }


def _verified_login_payload(request, user: User) -> dict:
    tokens = complete_verified_login(request, user)
    return {
        **tokens,
        "user": UserSerializer(user).data,
        "redirect": reverse("frontend:dashboard"),
        "needs_org": user.organization is None,
    }


def _mfa_pending_payload(user: User, temp_token) -> dict:
    """Return MFA verification payload with temporary token"""
    return {
        "temp_token": str(temp_token),
        "mfa_required": True,
        "mfa_method": getattr(user, "mfa_method", "totp"),
        "user_id": user.id,
        "user_email": user.email,
        "redirect": reverse("frontend:mfa_verify"),
        "message": _("Please enter your 6-digit authenticator code to complete login"),
        "expires_in_seconds": 300,  # 5 minutes
    }



class RegisterView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        summary="Register a new user",
        request=RegisterSerializer,
        responses={201: UserSerializer},
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log_action(request, AuditLog.Action.USER_CREATED, "user", str(user.id))

        try:
            challenge, sent = issue_email_otp(user, request)
        except EmailOTPError as exc:
            payload = UserSerializer(user).data
            payload.update(
                {
                    "verification_required": True,
                    "redirect": reverse("frontend:otp_verify"),
                    "error": exc.message,
                }
            )
            return Response(payload, status=_otp_error_status(exc))

        payload = UserSerializer(user).data
        payload.update(_otp_pending_payload(user, challenge, sent=sent))
        return Response(payload, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    IP_MAX = 20
    IP_LOCK = 900

    def _get_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "unknown")

    @extend_schema(
        tags=["Auth"],
        summary="Login and obtain JWT tokens",
        request=LoginSerializer,
        responses={200: {"type": "object", "properties": {
            "access": {"type": "string"},
            "refresh": {"type": "string"},
            "user": {"type": "object"},
        }}},
    )
    def post(self, request):
        ip = self._get_ip(request)
        ip_key = f"login_ip:{ip}"
        ip_attempts = cache.get(ip_key, 0)
        if ip_attempts >= self.IP_MAX:
            return Response(
                {"error": _("Too many login attempts. Try again in 15 minutes.")},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            cache.set(ip_key, ip_attempts + 1, self.IP_LOCK)
            raise ValidationError(serializer.errors)
        data = serializer.validated_data

        user = data["user"]

        if not user.is_email_verified:
            try:
                challenge, sent = issue_email_otp(user, request)
            except EmailOTPError as exc:
                cache.set(ip_key, ip_attempts + 1, self.IP_LOCK)
                return Response(
                    {
                        "verification_required": True,
                        "redirect": reverse("frontend:otp_verify"),
                        "error": exc.message,
                    },
                    status=_otp_error_status(exc),
                )
            return Response(_otp_pending_payload(user, challenge, sent=sent), status=status.HTTP_202_ACCEPTED)

        cache.delete(ip_key)
        
        # ✅ PHASE 1 FIX: Check if user has MFA enabled
        if user.mfa_enabled and user.mfa_secret:
            # Return temporary token for MFA verification (202 Accepted)
            temp_token = RefreshToken.for_user(user)
            temp_token.set_exp(lifetime=timedelta(minutes=5))  # 5-min expiry
            return Response(
                _mfa_pending_payload(user, temp_token),
                status=status.HTTP_202_ACCEPTED
            )
        
        # If no MFA, proceed with full login
        log_action(request, AuditLog.Action.LOGIN, "user", str(user.id))
        payload = _verified_login_payload(request, user)
        response = Response(payload)
        set_auth_cookies(response, payload["access"], payload["refresh"])
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Logout and blacklist refresh token")
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass
        log_action(request, AuditLog.Action.LOGOUT, "user", str(request.user.id))
        response = Response({"message": _("Logged out successfully.")})
        clear_auth_cookies(response)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Get current authenticated user", responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(tags=["Auth"], summary="Update current user profile", request=UserSerializer)
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_action(request, AuditLog.Action.USER_UPDATED, "user", str(request.user.id))
        return Response(serializer.data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Change current user password")
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        return Response({"message": _("Password changed successfully.")})


class UserListView(generics.ListCreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="List all users (Admin only)")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_permissions(self):
        return [IsAuthenticated(), IsAdminUser()]

    def get_queryset(self):
        queryset = User.objects.select_related("organization").order_by("-created_at")
        if _is_global_admin(self.request.user):
            if org_id := self.request.query_params.get("organization"):
                queryset = queryset.filter(organization_id=org_id)
        elif getattr(self.request.user, "organization_id", None):
            queryset = queryset.filter(organization_id=self.request.user.organization_id)
            if org_id := self.request.query_params.get("organization"):
                queryset = queryset.filter(organization_id=org_id)
        else:
            return queryset.none()

        if role := self.request.query_params.get("role"):
            roles = [item.strip() for item in role.split(",") if item.strip()]
            queryset = queryset.filter(role__in=roles)

        return queryset

    def perform_create(self, serializer):
        organization = serializer.validated_data.get("organization")
        if _is_global_admin(self.request.user):
            if organization:
                ensure_organization_settings(organization)
        else:
            if not getattr(self.request.user, "organization_id", None):
                raise ValidationError({
                    "organization": _(
                        "Your account is not linked to an organization. "
                        "Contact your platform administrator to fix this."
                    )
                })
            if organization and organization.id != self.request.user.organization_id:
                raise PermissionDenied(_("You can only create users inside your own organization."))
        user = serializer.save()
        log_action(self.request, AuditLog.Action.USER_CREATED, "user", str(user.id))


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsSameUserOrAdmin]

    @extend_schema(tags=["Auth"], summary="Get, update, or delete a user")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = User.objects.select_related("organization")
        if _is_global_admin(self.request.user):
            return queryset
        if getattr(self.request.user, "organization_id", None):
            return queryset.filter(organization_id=self.request.user.organization_id)
        return queryset.none()


class SetPasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        summary="Set a user's password",
        request={"type": "object", "properties": {
            "new_password": {"type": "string", "minLength": 8},
        }},
    )
    def post(self, request, pk):
        new_password = request.data.get("new_password", "")
        if len(new_password) < 8:
            return Response({"detail": _("Password must be at least 8 characters long.")}, status=400)

        try:
            user = User.objects.select_related("organization").get(pk=pk)
        except User.DoesNotExist:
            return Response({"detail": _("User not found.")}, status=404)

        is_admin = _is_global_admin(request.user) or (_is_org_admin(request.user) and _same_organization(request.user, user))
        is_same_user = request.user.pk == user.pk
        if not (is_admin or is_same_user):
            return Response({"detail": _("You do not have permission to perform this action.")}, status=403)

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=400)

        user.set_password(new_password)
        user.save(update_fields=["password"])
        log_action(request, AuditLog.Action.USER_UPDATED, "user", str(user.id))
        return Response({"detail": _("Password updated successfully.")})


UserSetPasswordView = SetPasswordView


class OrganizationListView(generics.ListCreateAPIView):
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Organization.objects.all().order_by("name")

    @extend_schema(tags=["Auth"], summary="List all organizations")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if _is_global_admin(self.request.user):
            return queryset
        if getattr(self.request.user, "organization_id", None):
            return queryset.filter(id=self.request.user.organization_id)
        return queryset.none()

    def perform_create(self, serializer):
        if not _is_global_admin(self.request.user):
            raise PermissionDenied("Only super administrators can create organizations from this endpoint.")
        organization = serializer.save()
        ensure_organization_settings(organization)


class OrganizationDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    queryset = Organization.objects.all()

    @extend_schema(tags=["Auth"], summary="Get or update an organization")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if _is_global_admin(self.request.user):
            return queryset
        if getattr(self.request.user, "organization_id", None):
            return queryset.filter(id=self.request.user.organization_id)
        return queryset.none()


class CurrentOrganizationView(APIView):
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        permissions = [IsAuthenticated()]
        if self.request.method == "PATCH" and getattr(self.request.user, "organization_id", None):
            permissions.append(IsAdminUser())
        return permissions

    def _default_payload(self):
        return {
            "id": None,
            "name": "",
            "name_ar": "",
            "country": Organization.Country.SAUDI_ARABIA,
            "currency": Organization.Currency.SAR,
            "vat_number": "",
            "cr_number": "",
            "vat_rate": 15,
            "industry": "",
            "fiscal_year_start": 1,
            "address": "",
            "website": "",
            "created_at": None,
            "updated_at": None,
        }

    def _attach_organization(self, user, organization):
        ensure_organization_settings(organization)
        update_fields = ["organization"]
        user.organization = organization
        if user.role != User.Role.ADMIN:
            user.role = User.Role.ADMIN
            update_fields.append("role")
        user.save(update_fields=update_fields)

    @extend_schema(tags=["Auth"], summary="Get the current user's organization")
    def get(self, request):
        organization = getattr(request.user, "organization", None)
        if not organization:
            return Response(self._default_payload())
        return Response(OrganizationSerializer(organization).data)

    @extend_schema(tags=["Auth"], summary="Update the current user's organization", request=OrganizationSerializer)
    def patch(self, request):
        organization = getattr(request.user, "organization", None)
        if not organization:
            serializer = OrganizationSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            organization = serializer.save()
            self._attach_organization(request.user, organization)
            log_action(request, AuditLog.Action.CONFIG_CHANGED, "organization", str(organization.id))
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        serializer = OrganizationSerializer(organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_action(request, AuditLog.Action.CONFIG_CHANGED, "organization", str(organization.id))
        return Response(serializer.data)


class OrganizationSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def _defaults(self, organization):
        return {
            "financial": {
                "monthly_budget_limit": 0,
                "large_invoice_threshold": 10000,
                "vat_rate": float(organization.vat_rate),
                "anomaly_threshold_pct": 25,
                "max_daily_invoices": 100,
                "expense_policy_limit": 5000,
                "zatca_api_url": "",
                "zatca_env": "sandbox",
                "zatca_qr_required": "true",
                "ai_review_mode": "balanced",
                "ai_confidence_threshold": 85,
                "ai_require_explanations": True,
                "ai_auto_create_case": True,
                "ai_block_high_risk_invoices": False,
                "invoice_due_days": 30,
                "invoice_require_po": True,
                "invoice_require_vendor_vat": True,
                "invoice_rounding_policy": "standard",
                "invoice_default_notes": "",
                "compliance_hold_missing_tax_id": True,
            },
            "notifications": {
                "email_invoice_flagged": True,
                "email_audit_case_created": True,
                "email_weekly_summary": True,
                "email_vat_late_filing": True,
                "ws_realtime_alerts": True,
                "payroll_anomaly_alert": True,
            },
        }

    def _get_settings(self, request):
        organization = getattr(request.user, "organization", None)
        if not organization:
            return None
        settings_obj, _ = OrganizationSettings.objects.get_or_create(
            organization=organization,
            defaults=self._defaults(organization),
        )
        return settings_obj

    def _default_payload(self):
        defaults = self._defaults(Organization())
        return {
            "financial": defaults.get("financial", {}),
            "notifications": defaults.get("notifications", {}),
        }

    def _payload(self, settings_obj):
        return {
            "financial": settings_obj.financial or {},
            "notifications": settings_obj.notifications or {},
        }

    @extend_schema(tags=["Auth"], summary="Get current organization settings", responses={200: OrganizationSettingsSerializer})
    def get(self, request):
        settings_obj = self._get_settings(request)
        if not settings_obj:
            return Response(self._default_payload())
        return Response(self._payload(settings_obj))

    @extend_schema(tags=["Auth"], summary="Update current organization settings", request=OrganizationSettingsSerializer)
    def post(self, request):
        settings_obj = self._get_settings(request)
        if not settings_obj:
            return Response({"error": "User has no organization."}, status=400)

        financial = dict(settings_obj.financial or {})
        notifications = dict(settings_obj.notifications or {})

        if isinstance(request.data.get("financial"), dict):
            financial.update(request.data.get("financial") or {})
        if isinstance(request.data.get("notifications"), dict):
            incoming_notifications = dict(request.data.get("notifications") or {})
            if "email_case_created" in incoming_notifications and "email_audit_case_created" not in incoming_notifications:
                incoming_notifications["email_audit_case_created"] = incoming_notifications["email_case_created"]
            if "email_vat_late" in incoming_notifications and "email_vat_late_filing" not in incoming_notifications:
                incoming_notifications["email_vat_late_filing"] = incoming_notifications["email_vat_late"]
            notifications.update(incoming_notifications)

        settings_obj.financial = financial
        settings_obj.notifications = notifications
        settings_obj.save(update_fields=["financial", "notifications", "updated_at"])

        if "vat_rate" in financial and getattr(request.user, "organization", None):
            request.user.organization.vat_rate = financial["vat_rate"]
            request.user.organization.save(update_fields=["vat_rate"])

        log_action(request, AuditLog.Action.CONFIG_CHANGED, "organization_settings", str(settings_obj.id))
        return Response(self._payload(settings_obj))

    def patch(self, request):
        return self.post(request)


CurrentOrganizationSettingsView = OrganizationSettingsView


class GoogleLoginView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        summary="Login with Google Identity Services",
        request={"type": "object", "properties": {"id_token": {"type": "string"}}},
    )
    def post(self, request):
        token = request.data.get("id_token", "")
        if not token or not settings.GOOGLE_CLIENT_ID:
            return Response({"error": _("Invalid Google token.")}, status=400)

        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token

            idinfo = google_id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except Exception:
            return Response({"error": _("Invalid Google token.")}, status=400)

        if not idinfo.get("email_verified", False):
            return Response(
                {"error": _("Google account email has not been verified.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = (idinfo.get("email") or "").strip().lower()
        full_name = (idinfo.get("name") or "").strip()
        if not email:
            return Response({"error": _("Invalid Google token.")}, status=400)

        user = User.objects.filter(email__iexact=email).select_related("organization").first()
        is_new = user is None

        if is_new:
            user = User(
                email=email,
                full_name=full_name or email.split("@")[0],
                role=User.Role.ADMIN,
                organization=None,
                is_active=True,
                email_verified_at=None,
            )
            user.set_unusable_password()
            user.save()
            ensure_user_organization(user, promote_owner=True)
        elif not user.full_name and full_name:
            user.full_name = full_name
            user.save(update_fields=["full_name"])
        elif not user.organization_id:
            ensure_user_organization(user, promote_owner=True)

        if not user.is_active:
            return Response({"error": _("This account is inactive.")}, status=403)

        if is_new:
            log_action(request, AuditLog.Action.USER_CREATED, "user", str(user.id), {"provider": "google"})

        if not user.is_email_verified:
            try:
                challenge, sent = issue_email_otp(user, request)
            except EmailOTPError as exc:
                return Response(
                    {
                        "error": exc.message,
                        "verification_required": True,
                        "redirect": reverse("frontend:otp_verify"),
                        "is_new": is_new,
                        "needs_org": user.organization is None,
                    },
                    status=_otp_error_status(exc),
                )

            payload = _otp_pending_payload(user, challenge, sent=sent)
            payload["is_new"] = is_new
            return Response(payload, status=status.HTTP_202_ACCEPTED)

        log_action(request, AuditLog.Action.LOGIN, "user", str(user.id), {"provider": "google"})
        payload = _verified_login_payload(request, user)
        payload["is_new"] = is_new
        response = Response(payload)
        set_auth_cookies(response, payload["access"], payload["refresh"])
        return response


class EmailOTPVerifyView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        summary="Verify email OTP and complete login",
        request={"type": "object", "properties": {"otp_code": {"type": "string"}}},
    )
    def post(self, request):
        user = get_pending_verification_user(request)
        if user is None:
            return Response(
                {"error": _("There is no pending verification flow. Sign in or create an account first.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            verify_email_otp(user, request.data.get("otp_code", ""))
        except EmailOTPError as exc:
            return Response(
                {
                    "error": exc.message,
                    "verification_required": True,
                    "redirect": reverse("frontend:otp_verify"),
                },
                status=_otp_error_status(exc),
            )

        log_action(request, AuditLog.Action.USER_UPDATED, "user", str(user.id), {"email_verified": True})
        log_action(request, AuditLog.Action.LOGIN, "user", str(user.id), {"provider": "email_otp"})
        payload = _verified_login_payload(request, user)
        payload["message"] = _("Email verified successfully.")
        response = Response(payload)
        set_auth_cookies(response, payload["access"], payload["refresh"])
        return response


class EmailOTPResendView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(tags=["Auth"], summary="Resend email OTP")
    def post(self, request):
        user = get_pending_verification_user(request)
        if user is None:
            clear_pending_verification(request)
            return Response(
                {"error": _("There is no pending verification flow to resend the code.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            challenge = resend_email_otp(user, request)
        except EmailOTPError as exc:
            return Response(
                {
                    "error": exc.message,
                    "verification_required": True,
                    "retry_after": exc.wait_seconds,
                },
                status=_otp_error_status(exc),
            )

        state = get_challenge_state(challenge)
        return Response(
            {
                "message": _("A new verification code has been sent to your email address."),
                "masked_email": mask_email_address(user.email),
                "otp_expires_at": state["expires_at"].isoformat() if state["expires_at"] else None,
                "otp_expires_in_seconds": state["expires_in"],
                "resend_cooldown_seconds": state["resend_available_in"],
                "attempts_remaining": state["attempts_remaining"],
            }
        )


class AuditLogListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    @extend_schema(
        tags=["Auth"],
        summary="View audit trail logs (Admin only)",
        parameters=[
            OpenApiParameter("user_id", description="Filter by user ID"),
            OpenApiParameter("action", description="Filter by action type"),
            OpenApiParameter("from_date", description="Filter from date (ISO 8601)"),
            OpenApiParameter("to_date", description="Filter to date (ISO 8601)"),
        ],
    )
    def get(self, request):
        from .serializers import AuditLogSerializer

        queryset = AuditLog.objects.select_related("user", "organization").order_by("-timestamp")
        if not _is_global_admin(request.user):
            if getattr(request.user, "organization_id", None):
                queryset = queryset.filter(organization_id=request.user.organization_id)
            else:
                queryset = queryset.none()

        if user_id := request.query_params.get("user_id"):
            queryset = queryset.filter(user_id=user_id)
        if action := request.query_params.get("action"):
            queryset = queryset.filter(action=action)
        if from_date := request.query_params.get("from_date"):
            queryset = queryset.filter(timestamp__gte=from_date)
        if to_date := request.query_params.get("to_date"):
            queryset = queryset.filter(timestamp__lte=to_date)

        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(AuditLogSerializer(page, many=True).data)
        return Response(AuditLogSerializer(queryset, many=True).data)


# ── MFA / TOTP Views (NFR-3 gap fix) ─────────────────────────────────────────

class MFASetupView(APIView):
    """
    GET  → Generate a new TOTP secret and return provisioning URI + QR code data URL.
    POST → Verify a TOTP code and activate MFA on the account.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Get MFA setup QR code and secret")
    def get(self, request):
        try:
            import pyotp, qrcode, io, base64
        except ImportError:
            return Response({"error": "pyotp / qrcode غير متاح على السيرفر."}, status=500)

        # Generate a new secret (not saved until POST confirms it)
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        label = request.user.email
        issuer = "Tadgeeg AI"
        uri = totp.provisioning_uri(label, issuer_name=issuer)

        # Build QR code as base64 data URL
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()

        # Temporarily store in session so POST can verify against same secret
        request.session["mfa_pending_secret"] = secret

        return Response({
            "secret": secret,
            "uri": uri,
            "qr_code": f"data:image/png;base64,{qr_b64}",
            "mfa_enabled": request.user.mfa_enabled,
        })

    @extend_schema(tags=["Auth"], summary="Activate MFA with a verified TOTP code")
    def post(self, request):
        try:
            import pyotp
        except ImportError:
            return Response({"error": "pyotp غير متاح على السيرفر."}, status=500)

        code = str(request.data.get("code", "")).strip()
        secret = request.session.get("mfa_pending_secret") or request.data.get("secret", "")

        if not code or not secret:
            return Response({"error": "code و secret مطلوبان."}, status=400)

        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            return Response({"error": "الرمز غير صحيح أو منتهي الصلاحية."}, status=400)

        user = request.user
        user.mfa_secret = secret
        user.mfa_enabled = True
        user.save(update_fields=["mfa_secret", "mfa_enabled"])
        request.session.pop("mfa_pending_secret", None)

        log_action(request, AuditLog.Action.USER_UPDATED, "user", str(user.id),
                   details={"change": "mfa_enabled"})

        return Response({"success": True, "message": "تم تفعيل المصادقة الثنائية بنجاح."})


class MFAVerifyView(APIView):
    """
    POST → Verify a TOTP code for a user who has MFA enabled.
    Used as a second-factor check after password login.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Verify TOTP code (second factor)")
    def post(self, request):
        try:
            import pyotp
        except ImportError:
            return Response({"error": "pyotp غير متاح."}, status=500)

        user = request.user
        if not user.mfa_enabled or not user.mfa_secret:
            return Response({"error": "المصادقة الثنائية غير مفعلة لهذا الحساب."}, status=400)

        code = str(request.data.get("code", "")).strip()
        if not code:
            return Response({"error": "الرمز مطلوب."}, status=400)

        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(code, valid_window=1):
            return Response({"error": "الرمز غير صحيح أو منتهي الصلاحية."}, status=400)

        return Response({"success": True, "message": "تم التحقق من الهوية."})


class MFALoginVerifyView(APIView):
    """
    ✅ PHASE 1 FIX: NEW ENDPOINT
    POST with temp_token + totp_code → Issue full JWT tokens
    Handles MFA verification during login flow
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        summary="Verify TOTP code during login (issue full tokens)",
        request={
            "type": "object",
            "properties": {
                "temp_token": {"type": "string", "description": "Temporary JWT token from 202 response"},
                "code": {"type": "string", "description": "6-digit TOTP code"}
            }
        }
    )
    def post(self, request):
        try:
            import pyotp
        except ImportError:
            return Response({"error": _("TOTP service unavailable")}, status=500)

        temp_token_str = request.data.get("temp_token", "")
        totp_code = str(request.data.get("code", "")).strip()

        if not temp_token_str or not totp_code:
            return Response(
                {"error": _("Temporary token and TOTP code are required")},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify temporary token and get user
        try:
            temp_token = RefreshToken(temp_token_str)
            user_id = temp_token.get("user_id")
            user = User.objects.get(id=user_id)
        except Exception:
            return Response(
                {"error": _("Invalid or expired temporary token")},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Verify TOTP code
        if not user.mfa_enabled or not user.mfa_secret:
            return Response(
                {"error": _("MFA not enabled for this user")},
                status=status.HTTP_400_BAD_REQUEST
            )

        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(totp_code, valid_window=1):
            # Track failed MFA attempts
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= 5:
                user.locked_until = timezone.now() + timedelta(minutes=30)
            user.save()
            
            return Response(
                {"error": _("Invalid or expired TOTP code")},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # MFA successful - issue full tokens
        user.failed_login_attempts = 0
        user.last_login = timezone.now()
        user.save()
        
        log_action(request, AuditLog.Action.LOGIN, "user", str(user.id),
                   details={"mfa": "verified"})
        
        payload = _verified_login_payload(request, user)
        response = Response(payload)
        set_auth_cookies(response, payload["access"], payload["refresh"])
        return response



class MFADisableView(APIView):
    """POST → Verify current TOTP code then disable MFA."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Disable MFA (requires valid TOTP code)")
    def post(self, request):
        try:
            import pyotp
        except ImportError:
            return Response({"error": "pyotp غير متاح."}, status=500)

        user = request.user
        if not user.mfa_enabled:
            return Response({"error": "المصادقة الثنائية غير مفعلة."}, status=400)

        code = str(request.data.get("code", "")).strip()
        if not code:
            return Response({"error": "الرمز مطلوب للتحقق قبل إلغاء التفعيل."}, status=400)

        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(code, valid_window=1):
            return Response({"error": "الرمز غير صحيح."}, status=400)

        user.mfa_enabled = False
        user.mfa_secret = ""
        user.save(update_fields=["mfa_enabled", "mfa_secret"])

        log_action(request, AuditLog.Action.USER_UPDATED, "user", str(user.id),
                   details={"change": "mfa_disabled"})

        return Response({"success": True, "message": "تم إلغاء تفعيل المصادقة الثنائية."})
