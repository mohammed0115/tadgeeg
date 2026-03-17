"""Audit App — Cases, workflow, and case management"""

import uuid
from django.db import models
from django.utils import timezone
from apps.authentication.models import User, Organization
from apps.transactions.models import Transaction


# ── AuditSession ──────────────────────────────────────────────────────────────

class AuditSession(models.Model):
    """
    Groups all documents uploaded in a single upload operation.

    State machine:
      RECEIVED → EXTRACTING → NORMALIZING → VALIDATING
               → REVIEW_REQUIRED | COMPLETED | FAILED
    """

    class State(models.TextChoices):
        RECEIVED        = "received",        "Received"
        EXTRACTING      = "extracting",      "Extracting"
        NORMALIZING     = "normalizing",     "Normalizing"
        VALIDATING      = "validating",      "Validating"
        REVIEW_REQUIRED = "review_required", "Review Required"
        COMPLETED       = "completed",       "Completed"
        FAILED          = "failed",          "Failed"

    # Valid forward transitions
    VALID_TRANSITIONS: dict = {
        State.RECEIVED:        {State.EXTRACTING, State.FAILED},
        State.EXTRACTING:      {State.NORMALIZING, State.REVIEW_REQUIRED, State.FAILED},
        State.NORMALIZING:     {State.VALIDATING, State.REVIEW_REQUIRED, State.FAILED},
        State.VALIDATING:      {State.REVIEW_REQUIRED, State.COMPLETED, State.FAILED},
        State.REVIEW_REQUIRED: {State.COMPLETED, State.FAILED},
        State.COMPLETED:       set(),
        State.FAILED:          {State.RECEIVED},  # allow retry
    }

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="audit_sessions")
    created_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="audit_sessions")
    session_name = models.CharField(max_length=255, blank=True)
    state        = models.CharField(max_length=20, choices=State.choices, default=State.RECEIVED, db_index=True)

    # Progress counters
    total_count          = models.PositiveIntegerField(default=0)
    processed_count      = models.PositiveIntegerField(default=0)
    success_count        = models.PositiveIntegerField(default=0)
    failed_count         = models.PositiveIntegerField(default=0)
    review_required_count = models.PositiveIntegerField(default=0)

    # Risk summary (computed when session completes)
    overall_risk_score   = models.FloatField(default=0.0)
    overall_risk_level   = models.CharField(max_length=10, default="low")
    duplicate_count      = models.PositiveIntegerField(default=0)
    compliance_issues    = models.PositiveIntegerField(default=0)
    high_risk_count      = models.PositiveIntegerField(default=0)

    # AI executive summary (generated on session completion)
    executive_summary    = models.JSONField(default=dict, blank=True)

    # Timing
    started_at   = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    # Error capture
    error_log    = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "audit_sessions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "state"]),
            models.Index(fields=["created_by"]),
        ]

    def __str__(self):
        return f"Session {self.id} [{self.state}] — {self.organization.name}"

    @property
    def progress_pct(self) -> int:
        if not self.total_count:
            return 0
        return min(int(self.processed_count / self.total_count * 100), 100)

    @property
    def is_terminal(self) -> bool:
        return self.state in (self.State.COMPLETED, self.State.FAILED)

    def can_transition_to(self, new_state: str) -> bool:
        return new_state in self.VALID_TRANSITIONS.get(self.state, set())


# ── AuditFinding ──────────────────────────────────────────────────────────────

class AuditFinding(models.Model):
    """A specific audit observation generated from rule evaluation or AI analysis."""

    class Severity(models.TextChoices):
        LOW      = "low",      "Low"
        MEDIUM   = "medium",   "Medium"
        HIGH     = "high",     "High"
        CRITICAL = "critical", "Critical"

    class Category(models.TextChoices):
        DUPLICATE    = "duplicate",    "Duplicate Document"
        COMPLIANCE   = "compliance",   "Compliance Violation"
        FRAUD        = "fraud",        "Fraud Indicator"
        MISSING_DATA = "missing_data", "Missing Required Data"
        AMOUNT_ANOMALY = "amount_anomaly", "Amount Anomaly"
        DATE_ANOMALY = "date_anomaly", "Date Anomaly"
        VENDOR_RISK  = "vendor_risk",  "Vendor Risk"
        OTHER        = "other",        "Other"

    class Status(models.TextChoices):
        OPEN       = "open",       "Open"
        REVIEWED   = "reviewed",   "Reviewed"
        RESOLVED   = "resolved",   "Resolved"
        DISMISSED  = "dismissed",  "Dismissed"

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="audit_findings")
    session      = models.ForeignKey(
        AuditSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="findings"
    )
    invoice      = models.ForeignKey(
        "invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="findings"
    )
    document     = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="findings"
    )
    rule_code    = models.CharField(max_length=20, blank=True)
    category     = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    severity     = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    status       = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    title        = models.CharField(max_length=255)
    description  = models.TextField()
    evidence     = models.JSONField(default=dict, blank=True)
    remediation  = models.TextField(blank=True)
    reviewed_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_findings"
    )
    reviewed_at  = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_findings"
        ordering = ["-severity", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["session"]),
            models.Index(fields=["severity"]),
        ]

    def __str__(self):
        return f"[{self.severity.upper()}] {self.title}"


class AuditCase(models.Model):
    """An audit case created from an anomaly or manual finding."""

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class CaseStatus(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        UNDER_REVIEW = "under_review", "Under Review"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        ESCALATED = "escalated", "Escalated"

    class CaseType(models.TextChoices):
        ANOMALY = "anomaly", "Transaction Anomaly"
        FRAUD = "fraud", "Suspected Fraud"
        COMPLIANCE = "compliance", "Compliance Violation"
        DUPLICATE = "duplicate", "Duplicate Transaction"
        MANUAL = "manual", "Manual Finding"
        BENFORD = "benford", "Benford's Law Violation"
        JOURNAL = "journal", "Suspicious Journal Entry"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="audit_cases")
    case_number = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    case_type = models.CharField(max_length=20, choices=CaseType.choices, default=CaseType.ANOMALY)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=CaseStatus.choices, default=CaseStatus.OPEN)
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_cases"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="created_cases"
    )
    transaction = models.ForeignKey(
        Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_cases"
    )
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_cases",
    )
    ai_risk_score = models.FloatField(default=0.0)
    ai_findings = models.JSONField(default=dict)
    due_date = models.DateField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_cases"
    )
    tags = models.JSONField(default=list)
    attachments = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_cases"
        ordering = ["-priority", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["assigned_to"]),
            models.Index(fields=["priority"]),
        ]

    def __str__(self):
        return f"{self.case_number}: {self.title}"

    def save(self, *args, **kwargs):
        if not self.case_number:
            import datetime
            count = AuditCase.objects.filter(organization=self.organization).count()
            year = datetime.datetime.now().year
            self.case_number = f"CASE-{year}-{count + 1:04d}"
        super().save(*args, **kwargs)


class CaseComment(models.Model):
    """Comment on an audit case."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(AuditCase, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    text = models.TextField()
    is_internal = models.BooleanField(default=False, help_text="Internal note not visible to external auditors")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "case_comments"
        ordering = ["created_at"]
