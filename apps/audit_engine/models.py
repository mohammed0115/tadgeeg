import uuid

from django.conf import settings
from django.db import models

from apps.authentication.models import Organization
from apps.storage_management.models import AuditFile


class AuditJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    class AuditType(models.TextChoices):
        GENERIC_AUDIT = "generic_audit", "Generic Audit"
        FINANCIAL_AUDIT = "financial_audit", "Financial Audit"
        COMPLIANCE_CHECK = "compliance_check", "Compliance Check"
        DOCUMENT_VALIDATION = "document_validation", "Document Validation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="audit_jobs",
    )
    audit_file = models.ForeignKey(
        AuditFile,
        on_delete=models.CASCADE,
        related_name="audit_jobs",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_audit_jobs",
    )
    audit_type = models.CharField(
        max_length=30,
        choices=AuditType.choices,
        default=AuditType.GENERIC_AUDIT,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    processing_time_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["audit_file"]),
        ]

    def __str__(self):
        return f"Job[{self.audit_type}] {self.audit_file.original_name} ({self.status})"


class AuditResult(models.Model):
    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit_job = models.OneToOneField(
        AuditJob,
        on_delete=models.CASCADE,
        related_name="result",
    )
    overall_score = models.FloatField(default=100.0)
    risk_level = models.CharField(
        max_length=10,
        choices=RiskLevel.choices,
        default=RiskLevel.LOW,
    )
    summary = models.TextField(blank=True)
    extracted_text = models.TextField(blank=True)
    extracted_entities = models.JSONField(default=dict)
    model_used = models.CharField(max_length=100, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Result for {self.audit_job} — score={self.overall_score}"


class AuditIssue(models.Model):
    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class IssueType(models.TextChoices):
        MISSING_FIELD = "missing_field", "Missing Field"
        INVALID_STRUCTURE = "invalid_structure", "Invalid Structure"
        SUSPICIOUS_VALUE = "suspicious_value", "Suspicious Value"
        DUPLICATE = "duplicate", "Duplicate"
        EMPTY_SECTION = "empty_section", "Empty Section"
        METADATA_INCONSISTENCY = "metadata_inconsistency", "Metadata Inconsistency"
        WEAK_COMPLETENESS = "weak_completeness", "Weak Completeness"
        UNSUPPORTED_FORMAT = "unsupported_format", "Unsupported Format"
        RULE_VIOLATION = "rule_violation", "Rule Violation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit_result = models.ForeignKey(
        AuditResult,
        on_delete=models.CASCADE,
        related_name="issues",
    )
    issue_code = models.CharField(max_length=50, blank=True)
    issue_type = models.CharField(max_length=30, choices=IssueType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    page_number = models.PositiveIntegerField(null=True, blank=True)
    row_reference = models.CharField(max_length=100, blank=True)
    suggested_fix = models.TextField(blank=True)
    confidence_score = models.FloatField(default=1.0)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["severity"]

    def __str__(self):
        return f"[{self.severity}] {self.title}"


class AIAnalysisLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    audit_file = models.ForeignKey(
        AuditFile,
        on_delete=models.CASCADE,
        related_name="ai_logs",
    )
    audit_job = models.ForeignKey(
        AuditJob,
        on_delete=models.CASCADE,
        related_name="ai_logs",
        null=True,
        blank=True,
    )
    model_name = models.CharField(max_length=100, blank=True)
    provider_name = models.CharField(max_length=50, blank=True, default="openai")
    prompt_version = models.CharField(max_length=20, blank=True, default="1.0")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUCCESS,
    )
    response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AI Analysis Log"
        verbose_name_plural = "AI Analysis Logs"

    def __str__(self):
        return f"AILog[{self.model_name}] file={self.audit_file.original_name} status={self.status}"
