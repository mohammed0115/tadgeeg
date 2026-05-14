"""Audit App — Cases, workflow, and case management"""

import uuid
from django.db import models
from apps.audit.integrity import HashChainMixin
from apps.authentication.models import User, Organization
from apps.transactions.models import Transaction
from core.mixins import SoftDeleteModel

# Engagement-level models (ISA 300) — re-exported so Django's app loader
# discovers them and they're importable as ``apps.audit.models.AuditEngagement``.
from apps.audit.engagement_models import AuditEngagement  # noqa: F401


class AuditSession(SoftDeleteModel):
    """Tracks the lifecycle and aggregate progress of a related audit upload."""

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        EXTRACTING = "extracting", "Extracting"
        NORMALIZING = "normalizing", "Normalizing"
        VALIDATING = "validating", "Validating"
        REVIEW_REQUIRED = "review_required", "Review Required"
        ACTION_REQUIRED = "action_required", "Action Required"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="audit_sessions",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_audit_sessions",
    )
    name = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RECEIVED,
    )
    total_count = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    review_required_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    high_risk_count = models.PositiveIntegerField(default=0)
    average_risk_score = models.FloatField(default=0.0)
    max_risk_score = models.FloatField(default=0.0)
    last_error = models.TextField(blank=True)
    context = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # ── Soft Delete (GDPR Compliance) — is_deleted / deleted_at from SoftDeleteModel
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="deleted_audit_sessions"
    )

    class Meta:
        db_table = "audit_sessions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        label = self.name or str(self.id)
        return f"AuditSession {label} ({self.status})"

    @property
    def progress_percent(self):
        if not self.total_count:
            return 0
        return round((self.processed_count / self.total_count) * 100, 2)

    def get_descendants_soft_deleted_count(self) -> int:
        """Count invoices and findings that would be affected by soft delete."""
        from apps.invoices.models import Invoice
        count = (
            Invoice.objects.filter(audit_session=self, is_deleted=False).count() +
            self.audit_findings.filter(is_deleted=False).count()
        )
        return count

    # delete() inherited from SoftDeleteModel — handles user kwarg and updated_at


class AuditFinding(models.Model):
    """Persisted user-facing findings generated from validation and review workflows."""

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        IGNORED = "ignored", "Ignored"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="audit_findings",
    )
    audit_session = models.ForeignKey(
        AuditSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="findings",
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_findings",
    )
    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_findings",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_audit_findings",
    )
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_audit_findings",
    )
    rule_code = models.CharField(max_length=20)
    rule_name = models.CharField(max_length=255)
    rule_group = models.CharField(max_length=10, blank=True)
    severity = models.CharField(
        max_length=10,
        choices=Severity.choices,
        default=Severity.MEDIUM,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=50, default="validation_engine")
    first_detected_at = models.DateTimeField(auto_now_add=True)
    last_detected_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audit_findings"
        ordering = ["-last_detected_at"]
        indexes = [
            models.Index(fields=["organization", "status", "severity"]),
            models.Index(fields=["audit_session", "status"]),
            models.Index(fields=["invoice", "rule_code"]),
        ]

    def __str__(self):
        return f"{self.rule_code} ({self.severity})"


class AuditCase(models.Model):
    """An audit case created from an anomaly or manual finding.

    ISA 230 §A21 mandates retention of engagement documentation for at
    least 5 years. AuditCase is part of that documentation, so we
    deliberately do NOT inherit ``SoftDeleteModel`` — an audit case is
    immutable to deletion. The ``deleted_by`` field below is preserved
    only for historical migration compatibility and is unused going
    forward.
    """

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
    
    # ── ISA 230 retention ──────────────────────────────────────────────
    # AuditCase no longer inherits SoftDeleteModel — these fields are
    # kept null and unused so legacy migration rows stay queryable.
    is_deleted   = models.BooleanField(default=False, editable=False)
    deleted_at   = models.DateTimeField(null=True, blank=True, editable=False)
    deleted_by   = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="deleted_audit_cases", editable=False,
    )

    # ── ISA 300 — link to parent engagement (optional for legacy cases). ──
    engagement = models.ForeignKey(
        "audit.AuditEngagement", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="cases",
    )

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
            from django.db import IntegrityError, transaction

            year = datetime.datetime.now().year
            for _ in range(5):
                try:
                    with transaction.atomic():
                        last_case = (
                            AuditCase.objects.select_for_update()
                            .filter(organization=self.organization, case_number__startswith=f"CASE-{year}-")
                            .order_by("-case_number")
                            .first()
                        )
                        next_number = 1
                        if last_case and last_case.case_number:
                            try:
                                next_number = int(last_case.case_number.rsplit("-", 1)[-1]) + 1
                            except Exception:
                                next_number = 1
                        self.case_number = f"CASE-{year}-{next_number:04d}"
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    self.case_number = ""
                    continue
            raise IntegrityError("Could not generate a unique audit case number after retries.")
        return super().save(*args, **kwargs)

    # delete() inherited from SoftDeleteModel


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


class CustomRuleDefinition(models.Model):
    """
    User-defined audit rule.

    Phase 2.2 adds two layers on top of the original 5 fixed condition types:

      • ``Status`` — DRAFT / PUBLISHED / ARCHIVED. Only PUBLISHED rules run
        inside the audit pipeline; everything else is invisible to the
        engine. Drafts can be tested freely against a sandbox sample.
      • ``expression_dsl`` — a generic JSON DSL of the form
        ``{"when": <condition tree>, "then": {"action", "severity", "message"}}``
        that supports nested ``all`` / ``any`` / ``not`` combinators and
        per-field operators (>, <, ==, contains, regex, is_empty, in, ...).
        This is what the visual rule-builder writes to.

    The legacy ``condition_type`` + ``condition_params`` fields stay so
    pre-Phase-2.2 rules keep working unchanged.
    """

    class Standard(models.TextChoices):
        ZATCA = "zatca", "ZATCA E-Invoicing"
        KPMG = "kpmg", "KPMG"
        DELOITTE = "deloitte", "Deloitte"
        PWC = "pwc", "PwC"
        EY = "ey", "EY"
        CUSTOM = "custom", "Custom"

    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class ConditionType(models.TextChoices):
        # Legacy fixed-schema types — kept for backward compatibility.
        MISSING_FIELD = "missing_field", "Field must not be empty"
        AMOUNT_THRESHOLD = "amount_threshold", "Amount above/below threshold"
        DATE_CHECK = "date_check", "Invoice date validation"
        DUPLICATE_CHECK = "duplicate_check", "Duplicate invoice number"
        PATTERN_MATCH = "pattern_match", "Field matches regex pattern"
        # Phase 2.2 — generic DSL evaluated by RuleDSLEvaluator.
        DSL = "dsl", "Custom DSL expression"

    class Status(models.TextChoices):
        DRAFT     = "draft",     "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED  = "archived",  "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="custom_rules"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    standard = models.CharField(max_length=20, choices=Standard.choices, default=Standard.CUSTOM)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    condition_type = models.CharField(max_length=30, choices=ConditionType.choices)
    condition_params = models.JSONField(
        default=dict,
        help_text=(
            "Parameters for the condition. Examples:\n"
            "  missing_field:    {\"field\": \"supplier_name\"}\n"
            "  amount_threshold: {\"max_amount\": 500000, \"min_amount\": 0}\n"
            "  date_check:       {\"no_future_dates\": true, \"max_days_old\": 365}\n"
            "  duplicate_check:  {}\n"
            "  pattern_match:    {\"field\": \"invoice_number\", \"pattern\": \"^INV-\\\\d+$\", \"must_match\": true}"
        ),
    )
    # Phase 2.2 generic DSL — used when condition_type='dsl'.
    expression_dsl = models.JSONField(
        default=dict, blank=True,
        help_text="Generic when/then JSON DSL — populated by the visual rule builder.",
    )
    remediation_suggestion = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True,
        help_text="Only PUBLISHED rules run in the audit pipeline.",
    )
    version = models.PositiveIntegerField(default=1)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="published_rules",
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="created_rules")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "custom_rule_definitions"
        ordering = ["name"]
        unique_together = [("organization", "name")]
        indexes = [
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self):
        return f"[{self.standard.upper()}] {self.name} (v{self.version})"

    def save(self, *args, **kwargs):
        if self.pk:
            # Increment version atomically and fetch back the new value in one
            # round-trip, avoiding the read-then-write race of the old pattern.
            from django.db import transaction
            with transaction.atomic():
                updated = (
                    CustomRuleDefinition.objects.select_for_update()
                    .filter(pk=self.pk)
                    .first()
                )
                if updated:
                    self.version = updated.version + 1
        super().save(*args, **kwargs)

    def evaluate(self, invoice: dict) -> dict:
        """
        Evaluate this rule against an invoice dict.

        Delegates to CustomRuleEvaluator in apps/audit/services/rule_evaluator.py
        to keep the model as a pure data container.
        """
        from apps.audit.services.rule_evaluator import CustomRuleEvaluator
        return CustomRuleEvaluator.evaluate(self, invoice)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1.3 — Working Papers + Reviewer Sign-off
# ─────────────────────────────────────────────────────────────────────────────

class WorkingPaper(HashChainMixin):
    """A reviewable, lockable audit working paper.

    Lifecycle (status field):
      DRAFT → READY_FOR_REVIEW → REVIEWED → LOCKED   (happy path)
                              ↘ DRAFT                 (reviewer rejects)

    Hash-chain hook: ``_should_chain_now()`` returns True only when the
    paper is LOCKED. Until then the preparer can edit freely; once locked,
    the chain prevents any further mutation of the payload (`title`,
    `paper_type`, `content`, etc.) — exactly the post-sign immutability
    auditors expect.
    """

    class PaperType(models.TextChoices):
        LEAD_SCHEDULE          = "lead_schedule",          "Lead Schedule"
        SUBSTANTIVE_TEST       = "substantive_test",       "Substantive Test"
        INTERNAL_CONTROL_TEST  = "internal_control_test",  "Internal Control Test"
        ANALYTICAL_REVIEW      = "analytical_review",      "Analytical Review"
        PBC_REQUEST            = "pbc_request",            "PBC (Prepared by Client) Request"
        MEMO                   = "memo",                   "Audit Memo"

    class Status(models.TextChoices):
        DRAFT             = "draft",             "Draft"
        READY_FOR_REVIEW  = "ready_for_review",  "Ready for Review"
        REVIEWED          = "reviewed",          "Reviewed (Senior)"
        LOCKED            = "locked",            "Locked (Partner Signed)"
        ARCHIVED          = "archived",          "Archived"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                      related_name="working_papers")
    reference     = models.CharField(max_length=64, db_index=True,
                                     help_text="e.g. WP-2026-AR-001")
    title         = models.CharField(max_length=255)
    paper_type    = models.CharField(max_length=32, choices=PaperType.choices)
    status        = models.CharField(max_length=24, choices=Status.choices,
                                     default=Status.DRAFT, db_index=True)

    # Free-form content captured by the preparer (lead-schedule rows,
    # test-of-detail results, analytical ratios, ...). The structure depends
    # on paper_type — kept as JSON so we don't need a separate table per type.
    content       = models.JSONField(default=dict, blank=True)

    # Cross-references — both to source documents and to other papers.
    related_invoices = models.ManyToManyField(
        "invoices.Invoice", blank=True, related_name="working_papers",
    )
    related_papers   = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="referenced_by",
        help_text="Other working papers this paper cites (e.g. WP-100 references WP-200.3).",
    )

    # Sign-off pointers — populated by the workflow service as each role acts.
    prepared_by         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                            related_name="prepared_papers")
    prepared_at         = models.DateTimeField(null=True, blank=True)
    submitted_at        = models.DateTimeField(null=True, blank=True)

    reviewed_by         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                            blank=True, related_name="reviewed_papers")
    reviewed_at         = models.DateTimeField(null=True, blank=True)
    reviewer_notes      = models.TextField(blank=True)

    partner_signed_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                            blank=True, related_name="partner_signed_papers")
    partner_signed_at   = models.DateTimeField(null=True, blank=True)
    partner_notes       = models.TextField(blank=True)
    locked_at           = models.DateTimeField(null=True, blank=True)

    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_working_papers"
        ordering = ["reference", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                name="wp_unique_reference_per_org",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "paper_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.title}"

    # ── HashChainMixin contract ──────────────────────────────────────────────

    @classmethod
    def _chain_org_filter_key(cls) -> str:
        return "organization_id"

    def _chain_organization_id(self):
        return self.organization_id

    def _chain_payload(self) -> dict:
        """Snapshot the immutable parts of the paper. Once locked, these
        fields cannot be edited without breaking the chain."""
        return {
            "id":                str(self.id),
            "organization_id":   str(self.organization_id),
            "reference":         self.reference,
            "title":             self.title,
            "paper_type":        self.paper_type,
            "content":           self.content or {},
            "prepared_by":       str(self.prepared_by_id) if self.prepared_by_id else None,
            "reviewed_by":       str(self.reviewed_by_id) if self.reviewed_by_id else None,
            "partner_signed_by": str(self.partner_signed_by_id) if self.partner_signed_by_id else None,
        }

    def _should_chain_now(self) -> bool:
        """Defer the chain assignment until the partner signs (status=LOCKED).

        While the paper is being drafted or reviewed, the preparer must be
        able to edit it — so we return False. The workflow service flips us
        to LOCKED and saves; at that point this returns True and the pre_save
        signal computes the hash, freezing the row.
        """
        return self.status == self.Status.LOCKED

    @property
    def is_locked(self) -> bool:
        return self.status == self.Status.LOCKED

    @property
    def can_edit(self) -> bool:
        return self.status in {self.Status.DRAFT, self.Status.READY_FOR_REVIEW}


class WPSignature(models.Model):
    """A sign-off event on a working paper.

    Stored as a separate row per role × user × method so the working paper
    keeps a complete audit trail of who signed when, with which method, and
    from which IP. The hash chain on `WorkingPaper` itself commits to the
    signer FKs, so no additional integrity layer is needed here.
    """

    class Role(models.TextChoices):
        PREPARER  = "preparer",  "Preparer"
        REVIEWER  = "reviewer",  "Senior Reviewer"
        PARTNER   = "partner",   "Partner / Engagement Quality Reviewer"

    class Method(models.TextChoices):
        DRAWN     = "drawn",     "Drawn (canvas)"
        TYPED     = "typed",     "Typed name"
        OTP       = "otp",       "One-time-password verification"
        X509_CERT = "x509",      "X.509 certificate"

    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    paper     = models.ForeignKey(WorkingPaper, on_delete=models.CASCADE,
                                  related_name="signatures")
    user      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                  related_name="wp_signatures")
    role      = models.CharField(max_length=16, choices=Role.choices)
    method    = models.CharField(max_length=16, choices=Method.choices,
                                 default=Method.TYPED)
    # Free-form payload depending on method:
    #   drawn  → {"strokes": [[x,y,t], ...]}
    #   typed  → {"name": "Mohammed Al-..."}
    #   otp    → {"verified_at": "...", "channel": "email"}
    #   x509   → {"subject": "CN=...", "fingerprint_sha256": "...", "issuer": "..."}
    signature_data = models.JSONField(default=dict, blank=True)
    notes     = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    signed_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_wp_signatures"
        ordering = ["-signed_at"]
        indexes = [
            models.Index(fields=["paper", "role"]),
        ]

    def __str__(self) -> str:
        return f"{self.role} sign on {self.paper_id} by {self.user} at {self.signed_at}"


class WPAttachment(models.Model):
    """A supporting file attached to a working paper (e.g. a PBC document)."""

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    paper       = models.ForeignKey(WorkingPaper, on_delete=models.CASCADE,
                                    related_name="attachments")
    file        = models.FileField(upload_to="working_papers/%Y/%m/")
    filename    = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                    related_name="wp_attachments")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_wp_attachments"
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"{self.filename} on {self.paper_id}"
