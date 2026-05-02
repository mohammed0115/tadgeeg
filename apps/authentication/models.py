"""Authentication App - Custom User Model"""

import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


_LEGACY_ROLE_NAME_MAP = {
    "admin": "admin",
    "platform admin": "admin",
    "organization admin": "admin",
    "org admin": "admin",
    "cao": "cao",
    "chief audit officer": "cao",
    "senior auditor": "senior_auditor",
    "auditor": "senior_auditor",
    "junior auditor": "junior_auditor",
    "compliance officer": "compliance_officer",
    "finance manager": "finance_manager",
    "external auditor": "external_auditor",
    "viewer": "external_auditor",
    "guest": "external_auditor",
}
_VALID_USER_ROLE_VALUES = set(_LEGACY_ROLE_NAME_MAP.values())


def _coerce_user_role(value: Any) -> str:
    """Normalize legacy role objects or labels into the current user role string."""
    if value is None:
        return "junior_auditor"

    if hasattr(value, "name"):
        value = getattr(value, "name")

    normalized = str(value).strip()
    if not normalized:
        return "junior_auditor"

    normalized_key = normalized.lower().replace("-", " ").replace("_", " ")
    if normalized in _VALID_USER_ROLE_VALUES:
        return normalized
    return _LEGACY_ROLE_NAME_MAP.get(normalized_key, "junior_auditor")


class _LegacyRoleManager:
    """In-memory manager for compatibility with removed Role model imports in tests."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], "Role"] = {}

    def get_or_create(self, *, name: str, permission_level: int = 0, **_: Any) -> tuple["Role", bool]:
        key = (str(name).strip().lower(), int(permission_level or 0))
        if key in self._cache:
            return self._cache[key], False
        role = Role(name=str(name).strip(), permission_level=int(permission_level or 0))
        self._cache[key] = role
        return role, True

    def create(self, *, name: str, permission_level: int = 0, **kwargs: Any) -> "Role":
        """Compatibility helper matching the subset of manager API used by tests."""
        return self.get_or_create(name=name, permission_level=permission_level, **kwargs)[0]


class Role:
    """Compatibility shim for older tests that still expect a standalone Role model."""

    objects = _LegacyRoleManager()

    def __init__(self, *, name: str, permission_level: int = 0) -> None:
        self.name = name
        self.permission_level = permission_level

    @property
    def code(self) -> str:
        """Return the normalized role code persisted on the current User model."""
        return _coerce_user_role(self.name)

    def __str__(self) -> str:
        return self.code


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("Email is required"))
        email = self.normalize_email(email)
        legacy_username = extra_fields.pop("username", "").strip()
        if legacy_username and not extra_fields.get("full_name"):
            extra_fields["full_name"] = legacy_username
        if "role" in extra_fields:
            extra_fields["role"] = _coerce_user_role(extra_fields.get("role"))
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
        kwargs.pop("slug", None)
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
    # Tamper-evidence: every entry's chain_hash = SHA-256(prev_chain_hash || canonical_json(payload)).
    # Auditors can walk the chain and detect any inserted, deleted, or
    # modified record. Computed in save(); never edited after creation.
    previous_hash = models.CharField(max_length=64, blank=True, db_index=True)
    chain_hash    = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["organization", "timestamp"]),
            models.Index(fields=["action"]),
        ]

    def save(self, *args, **kwargs):
        """Append-only: refuse updates and compute the chain hash on insert."""
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            # Update path — only `retain_until` may change post-creation, and
            # only when the caller explicitly opts in via update_fields. A
            # bare ``log.save()`` call attempting to overwrite anything else
            # is rejected to preserve append-only semantics.
            allowed = set(kwargs.get("update_fields") or [])
            if not allowed:
                raise ValueError(
                    "AuditLog records are append-only — full-row save() forbidden. "
                    "Pass update_fields=['retain_until'] for the only legal update."
                )
            if not allowed.issubset({"retain_until"}):
                raise ValueError(
                    "AuditLog records are append-only — modifying %s is forbidden."
                    % (allowed - {"retain_until"})
                )
            return super().save(*args, **kwargs)

        # Insert path — compute chain hash from the previous entry's hash.
        if not self.chain_hash:
            from core.utils.audit_log import compute_chain_hash
            prev = (
                AuditLog.objects
                .order_by("-timestamp")
                .values_list("chain_hash", flat=True)
                .first()
            ) or ""
            payload = {
                "action": self.action,
                "user_id": str(self.user_id) if self.user_id else None,
                "organization_id": str(self.organization_id) if self.organization_id else None,
                "resource_type": self.resource_type,
                "resource_id": self.resource_id,
                "details": self.details,
            }
            self.previous_hash = prev
            self.chain_hash = compute_chain_hash(prev, payload)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Block deletion — audit log is append-only."""
        raise ValueError("AuditLog records cannot be deleted (append-only).")

    def __str__(self):
        return f"{self.action} by {self.user} at {self.timestamp}"
