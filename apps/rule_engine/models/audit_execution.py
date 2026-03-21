import uuid

from django.db import models

from apps.rule_engine.models.rule_assignment import RuleAssignment


class AuditRun(models.Model):
    """
    Top-level record for a single execution of the audit engine against one
    document.  Aggregates all per-rule results and holds the overall risk score.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial"

    class TriggeredBy(models.TextChoices):
        UPLOAD = "upload", "Upload"
        MANUAL = "manual", "Manual"
        SCHEDULED = "scheduled", "Scheduled"
        REPROCESS = "reprocess", "Reprocess"

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        "authentication.Organization",
        on_delete=models.CASCADE,
        related_name="audit_runs",
        db_index=True,
    )

    document_type = models.CharField(max_length=32)
    document_id = models.UUIDField(db_index=True)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    engine_version = models.CharField(max_length=16, default="2.0")
    triggered_by = models.CharField(
        max_length=16,
        choices=TriggeredBy.choices,
        default=TriggeredBy.UPLOAD,
    )

    # Rule counters
    total_rules = models.PositiveSmallIntegerField(default=0)
    passed_rules = models.PositiveSmallIntegerField(default=0)
    failed_rules = models.PositiveSmallIntegerField(default=0)
    warning_rules = models.PositiveSmallIntegerField(default=0)
    skipped_rules = models.PositiveSmallIntegerField(default=0)
    error_rules = models.PositiveSmallIntegerField(default=0)

    # Risk assessment
    risk_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    risk_level = models.CharField(
        max_length=16,
        choices=RiskLevel.choices,
        null=True,
        blank=True,
    )
    requires_manual_review = models.BooleanField(default=False)
    blocks_approval = models.BooleanField(default=False)

    # Timing
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    processing_time_ms = models.PositiveIntegerField(null=True, blank=True)

    # Diagnostics
    error_log = models.JSONField(
        default=list,
        blank=True,
        help_text="List of error dicts recorded during execution.",
    )

    class Meta:
        db_table = "re_audit_run"
        indexes = [
            models.Index(
                fields=["organization", "document_type", "document_id"],
                name="re_run_org_doc_idx",
            ),
            models.Index(
                fields=["status", "started_at"],
                name="re_run_status_started_idx",
            ),
        ]
        ordering = ["-started_at"]
        verbose_name = "Audit Run"
        verbose_name_plural = "Audit Runs"

    def __str__(self) -> str:
        return f"AuditRun {self.id} [{self.document_type}] {self.status}"


class AuditResult(models.Model):
    """
    Result of evaluating a single :model:`rule_engine.RuleAssignment` within
    an :model:`rule_engine.AuditRun`.
    """

    class Status(models.TextChoices):
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"
        WARNING = "warning", "Warning"
        NOT_APPLICABLE = "not_applicable", "Not Applicable"
        SKIPPED = "skipped", "Skipped"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    audit_run = models.ForeignKey(
        AuditRun,
        on_delete=models.CASCADE,
        related_name="results",
    )
    rule_assignment = models.ForeignKey(
        RuleAssignment,
        on_delete=models.PROTECT,
        related_name="results",
    )

    # Snapshot of rule metadata at execution time (prevents foreign-key drift
    # when rule definitions are updated after the fact).
    rule_code = models.CharField(max_length=32, db_index=True)
    rule_version = models.PositiveSmallIntegerField()
    applied_severity = models.CharField(max_length=16)

    # Outcome
    status = models.CharField(max_length=16, choices=Status.choices)
    explanation = models.TextField()
    explanation_ar = models.TextField(blank=True)
    risk_contribution = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
    )
    blocks_approval = models.BooleanField(default=False)

    # Raw data from the rule implementation
    raw_output = models.JSONField(
        default=dict,
        blank=True,
        help_text="Unstructured output dict returned by the rule class.",
    )

    # Error capture
    error_message = models.TextField(blank=True)
    error_traceback = models.TextField(blank=True)

    # Timing
    execution_time_ms = models.PositiveIntegerField(null=True, blank=True)
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "re_audit_result"
        unique_together = (("audit_run", "rule_code"),)
        indexes = [
            models.Index(
                fields=["rule_code", "status"],
                name="re_result_rulecode_status_idx",
            ),
            models.Index(
                fields=["audit_run", "applied_severity"],
                name="re_result_run_severity_idx",
            ),
        ]
        verbose_name = "Audit Result"
        verbose_name_plural = "Audit Results"

    def __str__(self) -> str:
        return f"{self.rule_code} → {self.status} (run={self.audit_run_id})"


class AuditEvidence(models.Model):
    """
    Structured evidence item attached to an :model:`rule_engine.AuditResult`.

    Each piece of evidence captures one data point that led to the result,
    e.g. a field that was missing, a calculation that failed, or a value
    from a cross-document comparison.
    """

    class EvidenceType(models.TextChoices):
        FIELD_VALUE = "field_value", "Field Value"
        CALCULATION = "calculation", "Calculation"
        COMPARISON = "comparison", "Comparison"
        REFERENCE = "reference", "Reference"
        CROSS_DOCUMENT = "cross_document", "Cross Document"
        STATISTICAL = "statistical", "Statistical"
        SCREENSHOT = "screenshot", "Screenshot"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    audit_result = models.ForeignKey(
        AuditResult,
        on_delete=models.CASCADE,
        related_name="evidence_items",
    )

    evidence_type = models.CharField(
        max_length=32,
        choices=EvidenceType.choices,
    )

    # Field identification (bilingual)
    field_name = models.CharField(max_length=128, blank=True)
    field_name_ar = models.CharField(max_length=128, blank=True)

    # Values (stored as JSON to handle any scalar or nested type)
    expected_value = models.JSONField(null=True, blank=True)
    actual_value = models.JSONField(null=True, blank=True)

    # Human-readable description (bilingual)
    description = models.TextField()
    description_ar = models.TextField(blank=True)

    # Cross-document reference (optional)
    linked_document_type = models.CharField(max_length=32, blank=True)
    linked_document_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "re_audit_evidence"
        ordering = ["evidence_type"]
        verbose_name = "Audit Evidence"
        verbose_name_plural = "Audit Evidence Items"

    def __str__(self) -> str:
        return (
            f"{self.evidence_type}: {self.field_name or '—'} "
            f"(result={self.audit_result_id})"
        )
