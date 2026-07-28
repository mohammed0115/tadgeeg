"""Evidence Request workflow (TADGEEG-FIN-AUDIT-6A).

Lets an auditor formally request supporting evidence for a machine-suggested GL
risk finding (typically ``needs_evidence``/``escalated``) or an accepted SAD
difference item, attach files, track an append-only event history, and review
the submitted evidence (accept / reject / request more / cancel).

Safety boundaries (same as the surrounding audit app):
  * accepting evidence NEVER auto-accepts or dismisses the linked GL finding —
    the auditor must review the finding separately via the 3B workflow;
  * nothing here is a formal audit opinion;
  * never writes to ``apps.ledger``;
  * no AI;
  * every row is organization-scoped and validated against its engagement.
"""
from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.audit.audit_difference_models import AuditDifferenceItem
from apps.audit.confirmation_models import AuditConfirmationRequest
from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.audit.procedure_models import AuditProcedure
from apps.audit.substantive_test_models import SubstantiveTestItem
from apps.authentication.models import Organization, User


def _evidence_upload_path(instance, filename):
    """Org- and request-scoped upload path (keeps tenants isolated on disk)."""
    return f"audit_evidence/{instance.organization_id}/{instance.evidence_request_id}/{filename}"


class AuditEvidenceRequest(models.Model):
    """A request for supporting evidence against a GL finding or SAD item."""

    class RequestReason(models.TextChoices):
        SUPPORT_FINDING        = "support_finding",        "Support finding"
        MANAGEMENT_EXPLANATION = "management_explanation", "Management explanation"
        SUPPORTING_DOCUMENT    = "supporting_document",    "Supporting document"
        BANK_SUPPORT           = "bank_support",           "Bank support"
        INVOICE_SUPPORT        = "invoice_support",        "Invoice support"
        CONTRACT_SUPPORT       = "contract_support",       "Contract support"
        APPROVAL_SUPPORT       = "approval_support",       "Approval support"
        OTHER                  = "other",                  "Other"

    class Status(models.TextChoices):
        OPEN                   = "open",                   "Open"
        SUBMITTED              = "submitted",              "Submitted"
        UNDER_REVIEW           = "under_review",           "Under review"
        ACCEPTED               = "accepted",               "Accepted"
        REJECTED               = "rejected",               "Rejected"
        MORE_EVIDENCE_REQUIRED = "more_evidence_required", "More evidence required"
        CANCELLED              = "cancelled",              "Cancelled"

    class Priority(models.TextChoices):
        LOW      = "low",      "Low"
        MEDIUM   = "medium",   "Medium"
        HIGH     = "high",     "High"
        CRITICAL = "critical", "Critical"

    # Terminal states — no further transitions allowed.
    FINAL_STATUSES = frozenset({Status.ACCEPTED, Status.REJECTED, Status.CANCELLED})
    # Transitions that must carry a reviewer note.
    NOTE_REQUIRED_STATUSES = frozenset({Status.REJECTED, Status.MORE_EVIDENCE_REQUIRED})
    # ``management_explanation`` requests may be accepted without an attachment.
    EXPLANATION_ONLY_REASONS = frozenset({RequestReason.MANAGEMENT_EXPLANATION})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="evidence_requests")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="evidence_requests")

    # A request targets a GL finding, a SAD item, a substantive-test item, or an
    # external confirmation (at least one — validated in ``clean``).
    gl_finding = models.ForeignKey(
        GeneralLedgerRiskFinding, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_requests")
    sad_item = models.ForeignKey(
        AuditDifferenceItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_requests")
    # TADGEEG-FIN-AUDIT-9F — link a flagged substantive variance (9D) or an
    # external-confirmation discrepancy/no-reply (9C) to its evidence request.
    substantive_item = models.ForeignKey(
        SubstantiveTestItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_requests")
    confirmation_request = models.ForeignKey(
        AuditConfirmationRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_requests")
    # TADGEEG-G2.2 — link evidence to the procedure it supports, closing the
    # traceability chain Risk -> Procedure -> Evidence.
    procedure = models.ForeignKey(
        AuditProcedure, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_requests")

    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requested_evidence")
    # Assigned AUDITOR (reviewer side).
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_evidence")
    # TADGEEG-FIN-AUDIT-6B — assigned CLIENT user. Client-portal access is
    # driven by this FK (not by a role), so no authentication changes are
    # needed: a user is a "client" for a request only if assigned here.
    assigned_client_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="client_assigned_evidence")

    # Human-readable identifier (e.g. "EVR-00042"), unique per organization.
    request_number = models.CharField(max_length=32, blank=True, db_index=True)

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    request_reason = models.CharField(
        max_length=32, choices=RequestReason.choices,
        default=RequestReason.SUPPORT_FINDING)

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True)
    priority = models.CharField(
        max_length=12, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    due_date = models.DateField(null=True, blank=True)

    requested_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_evidence")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)
    # TADGEEG-FIN-AUDIT-6B — client-supplied management explanation.
    management_explanation = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_evidence_requests"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["engagement", "-created_at"]),
            models.Index(fields=["gl_finding"]),
            models.Index(fields=["sad_item"]),
            models.Index(fields=["assigned_client_user", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "request_number"],
                condition=models.Q(request_number__gt=""),
                name="uniq_evidence_request_number_per_org"),
        ]

    def __str__(self) -> str:
        return f"AuditEvidenceRequest {self.request_number or self.id} ({self.status})"

    @property
    def is_final(self) -> bool:
        return self.status in self.FINAL_STATUSES

    # ── TADGEEG-FIN-AUDIT-6B — SLA helpers (read-only, no stored state) ───────
    @property
    def days_remaining(self):
        """Whole days until the due date (negative if past). None if no due date."""
        if not self.due_date:
            return None
        from django.utils import timezone as _tz
        return (self.due_date - _tz.now().date()).days

    @property
    def is_overdue(self) -> bool:
        """Past its due date and still awaiting action (never for final states)."""
        if self.is_final or not self.due_date:
            return False
        remaining = self.days_remaining
        return remaining is not None and remaining < 0

    @property
    def sla_state(self) -> str:
        """One of: completed · waiting · overdue · due_soon · on_track · none."""
        if self.is_final:
            return "completed"
        if self.is_overdue:
            return "overdue"
        if self.status in (self.Status.SUBMITTED, self.Status.UNDER_REVIEW):
            return "waiting"
        if self.due_date is None:
            return "none"
        return "due_soon" if (self.days_remaining or 0) <= 3 else "on_track"

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "organization must match engagement.organization.")
        if self.gl_finding_id:
            f = self.gl_finding
            if f.engagement_id != self.engagement_id or f.organization_id != self.organization_id:
                raise ValidationError(
                    "gl_finding must belong to the same engagement and organization.")
        if self.sad_item_id:
            it = self.sad_item
            if it.engagement_id != self.engagement_id or it.organization_id != self.organization_id:
                raise ValidationError(
                    "sad_item must belong to the same engagement and organization.")
        if self.substantive_item_id:
            si = self.substantive_item
            if si.engagement_id != self.engagement_id or si.organization_id != self.organization_id:
                raise ValidationError(
                    "substantive_item must belong to the same engagement and organization.")
        if self.confirmation_request_id:
            cr = self.confirmation_request
            if cr.engagement_id != self.engagement_id or cr.organization_id != self.organization_id:
                raise ValidationError(
                    "confirmation_request must belong to the same engagement and organization.")
        if self.procedure_id:
            pr = self.procedure
            if pr.engagement_id != self.engagement_id or pr.organization_id != self.organization_id:
                raise ValidationError(
                    "procedure must belong to the same engagement and organization.")
        if not (self.gl_finding_id or self.sad_item_id
                or self.substantive_item_id or self.confirmation_request_id
                or self.procedure_id):
            raise ValidationError(
                "An evidence request must link a GL finding, a SAD item, a "
                "substantive-test item, a confirmation request, or a procedure.")


class AuditEvidenceAttachment(models.Model):
    """A file (or Document reference) attached as evidence to a request.

    TADGEEG-FIN-AUDIT-6C adds lifecycle + versioning. Attachments are NEVER
    overwritten and NEVER hard-deleted: each upload is a new immutable version,
    and retirement is expressed via :attr:`lifecycle_state`.
    """

    class Lifecycle(models.TextChoices):
        ACTIVE   = "active",   "Active"
        ARCHIVED = "archived", "Archived"
        FROZEN   = "frozen",   "Frozen"
        EXPIRED  = "expired",  "Expired"

    class VerificationResult(models.TextChoices):
        """TADGEEG-FIN-AUDIT-6D — detailed integrity-sweep outcome."""
        PENDING       = "pending",       "Pending verification"
        OK            = "ok",            "Verified"
        HASH_MISMATCH = "hash_mismatch", "Hash mismatch (corrupted)"
        MISSING_FILE  = "missing_file",  "File missing"
        UNREADABLE    = "unreadable",    "File unreadable"
        NO_DIGEST     = "no_digest",     "No stored digest"

    # Results that represent an integrity EXCEPTION requiring auditor attention.
    FAILED_VERIFICATION_RESULTS = frozenset({
        VerificationResult.HASH_MISMATCH,
        VerificationResult.MISSING_FILE,
        VerificationResult.UNREADABLE,
    })

    # States in which the attachment may no longer be modified at all.
    IMMUTABLE_STATES = frozenset({Lifecycle.FROZEN})
    # States that count as "live" evidence for review purposes.
    LIVE_STATES = frozenset({Lifecycle.ACTIVE, Lifecycle.FROZEN})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence_request = models.ForeignKey(
        AuditEvidenceRequest, on_delete=models.CASCADE, related_name="attachments")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="evidence_attachments")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="evidence_attachments")

    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="uploaded_evidence_attachments")
    # Optional link to a reusable documents.Document; the lightweight FileField
    # path is the default in this phase (no coupling to the document pipeline).
    document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_evidence_attachments")
    # max_length accommodates the org/request UUID-scoped upload path.
    uploaded_file = models.FileField(
        upload_to=_evidence_upload_path, max_length=255, null=True, blank=True)

    original_filename = models.CharField(max_length=255, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    description = models.TextField(blank=True)
    # ``is_active`` predates 6C and is kept as a MIRROR of lifecycle_state so
    # existing queries (``attachments.filter(is_active=True)``) keep working.
    # ``lifecycle_state`` is authoritative.
    is_active = models.BooleanField(default=True)

    # ── TADGEEG-FIN-AUDIT-6C — lifecycle, versioning, retention, integrity ────
    lifecycle_state = models.CharField(
        max_length=12, choices=Lifecycle.choices, default=Lifecycle.ACTIVE,
        db_index=True)
    lifecycle_changed_at = models.DateTimeField(null=True, blank=True)
    lifecycle_changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_lifecycle_changes")
    retention_until = models.DateField(null=True, blank=True)

    # Version chain. Each upload is a new row; ``replaces`` points at the
    # version it supersedes. Old versions stay immutable and readable.
    version = models.PositiveIntegerField(default=1)
    replaces = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="superseded_by")
    notes = models.TextField(blank=True)

    # Integrity verification bookkeeping (SHA-256 re-check on download).
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_verification_ok = models.BooleanField(null=True, blank=True)

    # ── TADGEEG-FIN-AUDIT-6D — assurance sweep detail ────────────────────────
    # ``verification_result`` is the detailed outcome; ``last_verification_ok``
    # (6C) is kept as its boolean MIRROR so existing code keeps working.
    verification_result = models.CharField(
        max_length=20, choices=VerificationResult.choices,
        default=VerificationResult.PENDING, db_index=True)
    verification_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    verification_error = models.TextField(blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_evidence_attachments"
        ordering = ("-uploaded_at",)
        indexes = [
            models.Index(fields=["evidence_request", "-uploaded_at"]),
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["organization", "lifecycle_state"]),
            models.Index(fields=["evidence_request", "version"]),
        ]

    def __str__(self) -> str:
        return f"AuditEvidenceAttachment {self.id} v{self.version} ({self.original_filename})"

    @property
    def is_frozen(self) -> bool:
        return self.lifecycle_state == self.Lifecycle.FROZEN

    @property
    def is_archived(self) -> bool:
        return self.lifecycle_state == self.Lifecycle.ARCHIVED

    @property
    def is_expired(self) -> bool:
        """Retention window elapsed. Computed — nothing is ever auto-purged."""
        if self.lifecycle_state == self.Lifecycle.EXPIRED:
            return True
        if not self.retention_until:
            return False
        from django.utils import timezone as _tz
        return self.retention_until < _tz.now().date()

    @property
    def integrity_badge(self) -> str:
        """UI badge: verified · failed · unverified."""
        if self.last_verification_ok is None:
            return "unverified"
        return "verified" if self.last_verification_ok else "failed"

    def clean(self):
        if self.evidence_request_id:
            req = self.evidence_request
            if req.organization_id != self.organization_id:
                raise ValidationError("attachment organization must match the request.")
            if req.engagement_id != self.engagement_id:
                raise ValidationError("attachment engagement must match the request.")


class AuditEvidenceRequestEvent(models.Model):
    """An append-only audit-trail entry for an evidence request."""

    class EventType(models.TextChoices):
        CREATED                = "created",                "Created"
        SUBMITTED              = "submitted",              "Evidence submitted"
        UNDER_REVIEW           = "under_review",           "Marked under review"
        ACCEPTED               = "accepted",               "Evidence accepted"
        REJECTED               = "rejected",               "Evidence rejected"
        MORE_EVIDENCE_REQUIRED = "more_evidence_required", "More evidence requested"
        CANCELLED              = "cancelled",              "Request cancelled"
        ATTACHMENT_ADDED       = "attachment_added",       "Attachment added"
        NOTE_ADDED             = "note_added",             "Note added"
        # TADGEEG-FIN-AUDIT-6B — auditor/client assignment changes.
        ASSIGNED               = "assigned",               "Assigned"
        # TADGEEG-FIN-AUDIT-6C — delivery & lifecycle.
        DOWNLOADED             = "downloaded",             "Evidence downloaded"
        VERSION_CREATED        = "version_created",        "New version created"
        VERIFIED               = "verified",               "Integrity verified"
        VERIFICATION_FAILED    = "verification_failed",    "Integrity verification FAILED"
        ARCHIVED               = "archived",               "Attachment archived"
        RESTORED               = "restored",               "Attachment restored"
        FROZEN                 = "frozen",                 "Attachment frozen"
        EXPIRED                = "expired",                "Attachment expired"
        ESCALATED              = "escalated",              "SLA escalation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence_request = models.ForeignKey(
        AuditEvidenceRequest, on_delete=models.CASCADE, related_name="events")
    # 6C: attachment-scoped events (download/verify/archive/…) live in this SAME
    # append-only trail rather than a second event model.
    attachment = models.ForeignKey(
        AuditEvidenceAttachment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events")
    engagement = models.ForeignKey(
        AuditEngagement, on_delete=models.CASCADE, related_name="evidence_request_events")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="evidence_request_events")

    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_request_events")
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, blank=True)
    note = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_evidence_request_events"
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=["evidence_request", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"AuditEvidenceRequestEvent {self.event_type} ({self.evidence_request_id})"


class AuditEvidenceRetentionPolicy(models.Model):
    """Engagement-level evidence retention policy (TADGEEG-FIN-AUDIT-6D).

    Declares how long evidence for an engagement must be retained. Applying a
    policy only computes ``AuditEvidenceAttachment.retention_until`` — it is
    **metadata only**: no file is ever deleted, purged, or modified, and expiry
    is never enforced automatically.
    """

    class Policy(models.TextChoices):
        YEARS_7  = "years_7",  "7 years"
        YEARS_10 = "years_10", "10 years"
        FOREVER  = "forever",  "Retain forever"
        CUSTOM   = "custom",   "Custom (years)"

    POLICY_YEARS = {Policy.YEARS_7: 7, Policy.YEARS_10: 10}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.OneToOneField(
        AuditEngagement, on_delete=models.CASCADE, related_name="evidence_retention_policy")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="evidence_retention_policies")

    policy = models.CharField(max_length=12, choices=Policy.choices, default=Policy.YEARS_7)
    custom_years = models.PositiveSmallIntegerField(null=True, blank=True)
    reason = models.TextField(blank=True)

    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="applied_retention_policies")
    attachments_marked = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "audit_evidence_retention_policies"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["organization", "policy"])]

    def __str__(self) -> str:
        return f"RetentionPolicy {self.engagement_id} ({self.policy})"

    @property
    def years(self):
        """Retention length in years, or None for 'forever'."""
        if self.policy == self.Policy.FOREVER:
            return None
        if self.policy == self.Policy.CUSTOM:
            return self.custom_years or None
        return self.POLICY_YEARS.get(self.policy)

    def expiry_for(self, uploaded_at):
        """Calculated expiry date for evidence uploaded at ``uploaded_at``."""
        years = self.years
        if years is None or uploaded_at is None:
            return None
        base = uploaded_at.date() if hasattr(uploaded_at, "date") else uploaded_at
        try:
            return base.replace(year=base.year + years)
        except ValueError:  # 29 Feb → 28 Feb
            return base.replace(month=2, day=28, year=base.year + years)

    def clean(self):
        if self.engagement_id and self.organization_id:
            if self.engagement.organization_id != self.organization_id:
                raise ValidationError(
                    "retention policy organization must match engagement.organization.")
        if self.policy == self.Policy.CUSTOM and not self.custom_years:
            raise ValidationError("custom policy requires custom_years.")
