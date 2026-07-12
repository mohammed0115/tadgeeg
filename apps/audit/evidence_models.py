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
from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
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

    # A request targets a GL finding OR a SAD item (validated in ``clean``).
    gl_finding = models.ForeignKey(
        GeneralLedgerRiskFinding, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_requests")
    sad_item = models.ForeignKey(
        AuditDifferenceItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="evidence_requests")

    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requested_evidence")
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_evidence")

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
        ]

    def __str__(self) -> str:
        return f"AuditEvidenceRequest {self.id} ({self.status})"

    @property
    def is_final(self) -> bool:
        return self.status in self.FINAL_STATUSES

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
        if not self.gl_finding_id and not self.sad_item_id:
            raise ValidationError(
                "An evidence request must link a GL finding or a SAD item.")


class AuditEvidenceAttachment(models.Model):
    """A file (or Document reference) attached as evidence to a request."""

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
    is_active = models.BooleanField(default=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_evidence_attachments"
        ordering = ("-uploaded_at",)
        indexes = [
            models.Index(fields=["evidence_request", "-uploaded_at"]),
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"AuditEvidenceAttachment {self.id} ({self.original_filename})"

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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence_request = models.ForeignKey(
        AuditEvidenceRequest, on_delete=models.CASCADE, related_name="events")
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
