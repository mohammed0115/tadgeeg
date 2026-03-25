import uuid
from django.db import models
from django.conf import settings
from apps.authentication.models import Organization


class Report(models.Model):
    class ReportType(models.TextChoices):
        AUDIT_SUMMARY = "audit_summary", "Audit Summary"
        FILE_AUDIT_REPORT = "file_audit_report", "File Audit Report"
        ORG_AUDIT_OVERVIEW = "org_audit_overview", "Organization Audit Overview"
        ISSUES_EXPORT = "issues_export", "Issues Export"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    report_type = models.CharField(max_length=30, choices=ReportType.choices)
    title = models.CharField(max_length=255)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="generated_reports",
    )
    # Lazy ref — avoids circular import with audit_engine
    related_audit_job = models.ForeignKey(
        "audit_engine.AuditJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    file_path = models.TextField(blank=True)
    report_data = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.status})"


class ReportItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="items",
    )
    # Stored as a plain UUID to avoid circular imports with audit_engine
    audit_result_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"ReportItem({self.id}) → Report({self.report_id})"
