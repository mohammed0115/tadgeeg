"""Notification model — in-app alerts for users in an organization."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    """An in-app notification targeted at a single user.

    Notifications are organization-scoped (multi-tenant safe) and never deleted —
    only marked as read or dismissed. Producers send notifications via
    :func:`apps.notifications.services.notify`.
    """

    class Severity(models.TextChoices):
        INFO = "info", _("Info")
        SUCCESS = "success", _("Success")
        WARNING = "warning", _("Warning")
        DANGER = "danger", _("Danger")
        CRITICAL = "critical", _("Critical")

    class Category(models.TextChoices):
        AUDIT = "audit", _("Audit")
        FRAUD = "fraud", _("Fraud")
        COMPLIANCE = "compliance", _("Compliance")
        UPLOAD = "upload", _("Upload")
        SYSTEM = "system", _("System")
        SECURITY = "security", _("Security")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True, blank=True,
    )

    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.INFO, db_index=True)
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.SYSTEM, db_index=True)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)

    # Optional click-through link (relative URL or absolute)
    link = models.CharField(max_length=500, blank=True)

    # Source object (e.g., invoice that triggered the alert)
    source_type = models.CharField(max_length=50, blank=True, help_text="e.g., 'invoice', 'audit_document'")
    source_id = models.CharField(max_length=64, blank=True, db_index=True)

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.title} → {self.user_id}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])
