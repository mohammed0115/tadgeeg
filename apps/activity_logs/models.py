import uuid
from django.db import models
from django.conf import settings
from apps.authentication.models import Organization


class ActivityLog(models.Model):
    class Action(models.TextChoices):
        # File events
        FILE_UPLOADED = "file_uploaded", "File Uploaded"
        FILE_ARCHIVED = "file_archived", "File Archived"
        FILE_RESTORED = "file_restored", "File Restored"
        FILE_DELETED = "file_deleted", "File Deleted"
        FILE_MOVED = "file_moved", "File Moved"
        FILE_DOWNLOADED = "file_downloaded", "File Downloaded"
        # Folder events
        FOLDER_CREATED = "folder_created", "Folder Created"
        FOLDER_RENAMED = "folder_renamed", "Folder Renamed"
        FOLDER_DELETED = "folder_deleted", "Folder Deleted"
        # Audit events
        AUDIT_STARTED = "audit_started", "Audit Started"
        AUDIT_COMPLETED = "audit_completed", "Audit Completed"
        AUDIT_FAILED = "audit_failed", "Audit Failed"
        AUDIT_CANCELED = "audit_canceled", "Audit Canceled"
        # Report events
        REPORT_GENERATED = "report_generated", "Report Generated"
        REPORT_DOWNLOADED = "report_downloaded", "Report Downloaded"
        # Storage events
        STORAGE_CHANGED = "storage_changed", "Storage Changed"
        POLICY_CHANGED = "policy_changed", "Policy Changed"
        # Auth events
        USER_LOGIN = "user_login", "User Login"
        USER_LOGOUT = "user_logout", "User Logout"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["action"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.user} at {self.created_at:%Y-%m-%d %H:%M}"
