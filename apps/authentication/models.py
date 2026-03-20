"""Authentication App - Custom User Model"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("Email is required"))
        email = self.normalize_email(email)
        legacy_username = extra_fields.pop("username", "").strip()
        if legacy_username and not extra_fields.get("full_name"):
            extra_fields["full_name"] = legacy_username
        extra_fields.setdefault("email_verified_at", timezone.now())
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model with role-based access control."""

    class Role(models.TextChoices):
        ADMIN = "admin", _("System Administrator")
        CHIEF_AUDIT_OFFICER = "cao", _("Chief Audit Officer")
        SENIOR_AUDITOR = "senior_auditor", _("Senior Auditor")
        JUNIOR_AUDITOR = "junior_auditor", _("Junior Auditor")
        COMPLIANCE_OFFICER = "compliance_officer", _("Compliance Officer")
        FINANCE_MANAGER = "finance_manager", _("Finance Manager")
        EXTERNAL_AUDITOR = "external_auditor", _("External Auditor")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.JUNIOR_AUDITOR)
    organization = models.ForeignKey(
        "Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="users"
    )
    department = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=64, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    class Meta:
        db_table = "auth_users"
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["role"]),
            models.Index(fields=["organization"]),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.role})"

    def is_locked(self):
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False

    @property
    def effective_role(self):
        if self.is_superuser:
            return "super_admin"
        if self.role == self.Role.ADMIN:
            return "organization_admin"
        if self.role in [self.Role.CHIEF_AUDIT_OFFICER, self.Role.SENIOR_AUDITOR, self.Role.JUNIOR_AUDITOR]:
            return "auditor"
        if self.role == self.Role.FINANCE_MANAGER:
            return "finance_manager"
        if self.role == self.Role.COMPLIANCE_OFFICER:
            return "compliance_officer"
        if self.role == self.Role.EXTERNAL_AUDITOR:
            return "read_only_executive"
        return self.role

    def has_role_capability(self, capability: str) -> bool:
        capability_map = {
            "manage_organization": {self.Role.ADMIN},
            "approve_invoices": {self.Role.ADMIN, self.Role.CHIEF_AUDIT_OFFICER, self.Role.SENIOR_AUDITOR},
            "review_findings": {self.Role.ADMIN, self.Role.CHIEF_AUDIT_OFFICER, self.Role.SENIOR_AUDITOR, self.Role.COMPLIANCE_OFFICER},
            "view_executive_dashboard": {
                self.Role.ADMIN,
                self.Role.CHIEF_AUDIT_OFFICER,
                self.Role.SENIOR_AUDITOR,
                self.Role.FINANCE_MANAGER,
                self.Role.EXTERNAL_AUDITOR,
            },
            "edit_invoice_data": {self.Role.ADMIN, self.Role.CHIEF_AUDIT_OFFICER, self.Role.SENIOR_AUDITOR, self.Role.JUNIOR_AUDITOR},
        }
        allowed_roles = capability_map.get(capability, set())
        return self.is_superuser or self.role in allowed_roles

    @property
    def is_email_verified(self):
        return self.email_verified_at is not None

    @property
    def can_manage_users(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def can_generate_reports(self):
        return self.has_role_capability("review_findings")

    @property
    def can_view_all_data(self):
        return self.is_superuser or self.role in [
            self.Role.ADMIN,
            self.Role.CHIEF_AUDIT_OFFICER,
            self.Role.SENIOR_AUDITOR,
        ]


class EmailOTPVerification(models.Model):
    """Single-use email OTP challenges for onboarding verification."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_otp_verifications",
    )
    otp_code_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    attempts_count = models.PositiveSmallIntegerField(default=0)
    resend_count = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_email_otp_verifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "is_used"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"Email OTP for {self.user.email}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def resend_available_at(self):
        cooldown_seconds = int(getattr(settings, "EMAIL_OTP_RESEND_COOLDOWN_SECONDS", 60))
        return self.last_sent_at + timedelta(seconds=cooldown_seconds)


class Organization(models.Model):
    """Multi-tenant organization entity."""

    class Country(models.TextChoices):
        SAUDI_ARABIA = "SA", _("Saudi Arabia")
        UAE = "AE", _("United Arab Emirates")
        BAHRAIN = "BH", _("Bahrain")
        KUWAIT = "KW", _("Kuwait")
        OMAN = "OM", _("Oman")
        QATAR = "QA", _("Qatar")

    class Currency(models.TextChoices):
        SAR = "SAR", _("Saudi Riyal")
        AED = "AED", _("UAE Dirham")
        BHD = "BHD", _("Bahraini Dinar")
        KWD = "KWD", _("Kuwaiti Dinar")
        OMR = "OMR", _("Omani Rial")
        QAR = "QAR", _("Qatari Riyal")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    name_ar = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=2, choices=Country.choices, default=Country.SAUDI_ARABIA)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.SAR)
    vat_number = models.CharField(max_length=50, blank=True)
    cr_number = models.CharField(max_length=50, blank=True, help_text=_("Commercial Registration Number"))
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=15.00)
    fiscal_year_start = models.PositiveSmallIntegerField(default=1, help_text=_("Month (1-12)"))
    address = models.TextField(blank=True)
    website = models.URLField(blank=True)
    industry = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organizations"

    def __init__(self, *args, **kwargs):
        legacy_registration = kwargs.pop("registration_number", None)
        if legacy_registration is not None and "cr_number" not in kwargs:
            kwargs["cr_number"] = legacy_registration
        super().__init__(*args, **kwargs)

    def __str__(self):
        return self.name


class OrganizationSettings(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    financial = models.JSONField(default=dict)
    notifications = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_settings"

    def __str__(self):
        return f"Settings for {self.organization.name}"


class AuditLog(models.Model):
    """Immutable audit trail for all system actions."""

    class Action(models.TextChoices):
        LOGIN = "login", _("User Login")
        LOGOUT = "logout", _("User Logout")
        LOGIN_FAILED = "login_failed", _("Failed Login")
        DOCUMENT_UPLOAD = "document_upload", _("Document Upload")
        DOCUMENT_PROCESS = "document_process", _("Document Processed")
        TRANSACTION_CREATE = "transaction_create", _("Transaction Created")
        TRANSACTION_UPDATE = "transaction_update", _("Transaction Updated")
        ANOMALY_DETECTED = "anomaly_detected", _("Anomaly Detected")
        CASE_CREATED = "case_created", _("Audit Case Created")
        REPORT_GENERATED = "report_generated", _("Report Generated")
        USER_CREATED = "user_created", _("User Created")
        USER_UPDATED = "user_updated", "User Updated"
        CONFIG_CHANGED = "config_changed", "Configuration Changed"
        DATA_EXPORT = "data_export", "Data Exported"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="audit_logs")
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, related_name="audit_logs"
    )
    action = models.CharField(max_length=50, choices=Action.choices)
    resource_type = models.CharField(max_length=50, blank=True)
    resource_id = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    details = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)
    retain_until = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text="Records are retained until this date (7-year minimum per regulatory requirements)."
    )

    class Meta:
        db_table = "audit_logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["organization", "timestamp"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.user} at {self.timestamp}"
