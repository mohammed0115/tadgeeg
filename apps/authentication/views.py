"""Authentication Views"""

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from core.utils.audit import log_action

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
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

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
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = data["user"]
        user.last_login_ip = request.META.get("REMOTE_ADDR")
        user.last_login = timezone.now()
        user.save(update_fields=["last_login_ip", "last_login"])

        log_action(request, AuditLog.Action.LOGIN, "user", str(user.id))
        return Response({
            "access": data["access"],
            "refresh": data["refresh"],
            "user": UserSerializer(user).data,
        })


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
        return Response({"message": "Logged out successfully."})


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
        return Response({"message": "Password changed successfully."})


class UserListView(generics.ListCreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="List all users (Admin only)")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsAdminUser()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = User.objects.select_related("organization").order_by("-created_at")
        if org_id := self.request.query_params.get("organization"):
            queryset = queryset.filter(organization_id=org_id)
        elif getattr(self.request.user, "organization_id", None):
            queryset = queryset.filter(organization=self.request.user.organization)

        if role := self.request.query_params.get("role"):
            roles = [item.strip() for item in role.split(",") if item.strip()]
            queryset = queryset.filter(role__in=roles)

        return queryset

    def perform_create(self, serializer):
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
        if getattr(self.request.user, "organization_id", None):
            return queryset.filter(organization=self.request.user.organization)
        return queryset


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
            return Response({"detail": "يجب أن تكون كلمة المرور 8 أحرف على الأقل."}, status=400)

        try:
            user = User.objects.select_related("organization").get(pk=pk)
        except User.DoesNotExist:
            return Response({"detail": "المستخدم غير موجود."}, status=404)

        is_admin = request.user.role == User.Role.ADMIN
        is_same_user = request.user.pk == user.pk
        if not (is_admin or is_same_user):
            return Response({"detail": "ليس لديك صلاحية لتنفيذ هذا الإجراء."}, status=403)

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=400)

        user.set_password(new_password)
        user.save(update_fields=["password"])
        log_action(request, AuditLog.Action.USER_UPDATED, "user", str(user.id))
        return Response({"detail": "تم تغيير كلمة المرور بنجاح."})


UserSetPasswordView = SetPasswordView


class OrganizationListView(generics.ListCreateAPIView):
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Organization.objects.all().order_by("name")

    @extend_schema(tags=["Auth"], summary="List all organizations")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class OrganizationDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    queryset = Organization.objects.all()

    @extend_schema(tags=["Auth"], summary="Get or update an organization")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class CurrentOrganizationView(APIView):
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        permissions = [IsAuthenticated()]
        if self.request.method == "PATCH":
            permissions.append(IsAdminUser())
        return permissions

    @extend_schema(tags=["Auth"], summary="Get the current user's organization")
    def get(self, request):
        organization = getattr(request.user, "organization", None)
        if not organization:
            return Response({"error": "User has no organization."}, status=400)
        return Response(OrganizationSerializer(organization).data)

    @extend_schema(tags=["Auth"], summary="Update the current user's organization", request=OrganizationSerializer)
    def patch(self, request):
        organization = getattr(request.user, "organization", None)
        if not organization:
            return Response({"error": "User has no organization."}, status=400)

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

    def _payload(self, settings_obj):
        return {
            "financial": settings_obj.financial or {},
            "notifications": settings_obj.notifications or {},
        }

    @extend_schema(tags=["Auth"], summary="Get current organization settings", responses={200: OrganizationSettingsSerializer})
    def get(self, request):
        settings_obj = self._get_settings(request)
        if not settings_obj:
            return Response({"error": "User has no organization."}, status=400)
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
            return Response({"error": "رمز Google غير صالح"}, status=400)

        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token

            idinfo = google_id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except Exception:
            return Response({"error": "رمز Google غير صالح"}, status=400)

        # TODO: Email verification disabled for development
        # if idinfo.get("email_verified") is False:
        #     return Response({"error": "رمز Google غير صالح"}, status=400)

        email = (idinfo.get("email") or "").strip().lower()
        full_name = (idinfo.get("name") or "").strip()
        if not email:
            return Response({"error": "رمز Google غير صالح"}, status=400)

        user = User.objects.filter(email__iexact=email).select_related("organization").first()
        is_new = user is None

        if is_new:
            user = User(
                email=email,
                full_name=full_name or email.split("@")[0],
                role=User.Role.JUNIOR_AUDITOR,
                organization=None,
                is_active=True,
            )
            user.set_unusable_password()
            user.save()
        elif not user.full_name and full_name:
            user.full_name = full_name
            user.save(update_fields=["full_name"])

        if not user.is_active:
            return Response({"error": "الحساب غير مفعّل"}, status=403)

        user.last_login_ip = request.META.get("REMOTE_ADDR")
        user.last_login = timezone.now()
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(update_fields=["last_login_ip", "last_login", "failed_login_attempts", "locked_until"])

        django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.user = user

        refresh = RefreshToken.for_user(user)
        if is_new:
            log_action(request, AuditLog.Action.USER_CREATED, "user", str(user.id), {"provider": "google"})
        log_action(request, AuditLog.Action.LOGIN, "user", str(user.id), {"provider": "google"})

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(user).data,
            "is_new": is_new,
            "needs_org": user.organization is None,
        })


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
