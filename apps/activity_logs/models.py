import hashlib
import json
import uuid

from django.conf import settings
from django.db import models

from apps.audit.integrity import HashChainMixin
from apps.authentication.models import Organization


class ActivityLog(HashChainMixin):
    """Append-only activity log with a tamper-evident hash chain.

    Every save links to the previous row in the org's chain via
    ``previous_hash`` and computes its own ``chain_hash`` over the
    canonical JSON of (action, entity_type, entity_id, user, ip,
    metadata, timestamp). Edits are forbidden post-creation — the
    save() override rejects them.
    """
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
        # Engagement events (TADGEEG-G0 — ISA engagement audit trail)
        ENGAGEMENT_STAGE_CHANGED = "engagement_stage_changed", "Engagement Stage Changed"
        FINDING_STATUS_CHANGED = "finding_status_changed", "Finding Status Changed"

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

    # Tamper-evidence comes from HashChainMixin: previous_hash, event_hash and
    # chain_position. The hand-rolled `chain_hash` that used to live here
    # ordered by created_at and took no lock, so two writes in the same
    # microsecond both chained off the same predecessor and forked the chain
    # without raising. See tests/test_audit_trail_integrity.py.

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["action"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    # ── Append-only enforcement ────────────────────────────────────────
    def save(self, *args, **kwargs):
        if self.pk and ActivityLog.objects.filter(pk=self.pk).exists():
            raise ValueError(
                "ActivityLog rows are append-only — save() on an existing "
                "row is forbidden."
            )
        # Chain assignment is the mixin's pre_save signal, not ours. Doing it
        # here would run outside its lock.
        return super().save(*args, **kwargs)

    # ── HashChainMixin contract ────────────────────────────────────────

    @classmethod
    def _chain_org_filter_key(cls) -> str:
        return "organization_id"

    def _chain_organization_id(self):
        return self.organization_id

    def _chain_payload(self) -> dict:
        """The immutable snapshot the hash commits to.

        `created_at` is excluded deliberately: auto_now_add populates it in the
        field-level pre_save, which fires AFTER the chain signal, so the value
        is still None when we hash. chain_position already encodes order —
        see InvoiceAuditEvent._chain_payload for the same reasoning.
        """
        return {
            "org":         str(self.organization_id or ""),
            "user":        str(self.user_id or ""),
            "action":      self.action,
            "entity_type": self.entity_type,
            "entity_id":   self.entity_id,
            "ip":          str(self.ip_address or ""),
            "metadata":    self.metadata or {},
        }

    def __str__(self):
        return f"{self.action} by {self.user} at {self.created_at:%Y-%m-%d %H:%M}"


# ─── Chain of Custody — Evidence access log ─────────────────────────────────
class EvidenceAccess(models.Model):
    """Every read/download/copy of a piece of evidence.

    Required by ISA 230 §A6 and standard forensic-audit practice. A
    forensic auditor must be able to answer "who touched this evidence
    between upload and trial". Backed by the same append-only +
    hash-chain pattern as ActivityLog.
    """

    class Action(models.TextChoices):
        VIEWED       = "viewed",       "Viewed"
        DOWNLOADED   = "downloaded",   "Downloaded"
        EMAILED      = "emailed",      "Emailed"
        EXPORTED     = "exported",     "Exported"
        HASH_VERIFY  = "hash_verify",  "Hash re-verified"
        ATTACHED     = "attached",     "Attached to case"
        DETACHED     = "detached",     "Detached from case"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="evidence_accesses",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="evidence_accesses",
    )

    evidence_kind  = models.CharField(max_length=32,
                                      help_text='"document" | "working_paper" | "report" | ...')
    evidence_id    = models.CharField(max_length=64, db_index=True)
    evidence_sha   = models.CharField(max_length=64, blank=True,
                                      help_text="Content hash at moment of access.")

    action      = models.CharField(max_length=16, choices=Action.choices)
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    user_agent  = models.CharField(max_length=255, blank=True)
    case_id     = models.CharField(max_length=64, blank=True, db_index=True,
                                   help_text="AuditCase id at the moment of access.")
    metadata    = models.JSONField(default=dict, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    # Hash chain — per organization, like ActivityLog.
    previous_hash = models.CharField(max_length=64, blank=True, db_index=True)
    chain_hash    = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        db_table = "evidence_access"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=("organization", "created_at")),
            models.Index(fields=("evidence_kind", "evidence_id")),
            models.Index(fields=("user", "created_at")),
        ]

    def save(self, *args, **kwargs):
        if self.pk and EvidenceAccess.objects.filter(pk=self.pk).exists():
            raise ValueError(
                "EvidenceAccess rows are append-only — modification is forbidden."
            )
        if not self.chain_hash:
            prev = (
                EvidenceAccess.objects
                .filter(organization=self.organization)
                .order_by("-created_at")
                .first()
            )
            self.previous_hash = prev.chain_hash if prev else ""
            self.chain_hash = self._compute_chain_hash()
        return super().save(*args, **kwargs)

    def _payload(self) -> dict:
        return {
            "org":  str(self.organization_id or ""),
            "user": str(self.user_id or ""),
            "kind": self.evidence_kind,
            "evid": self.evidence_id,
            "sha":  self.evidence_sha,
            "act":  self.action,
            "ip":   str(self.ip_address or ""),
            "ua":   self.user_agent,
            "case": self.case_id,
            "meta": self.metadata or {},
        }

    def _compute_chain_hash(self) -> str:
        body = json.dumps(self._payload(), sort_keys=True,
                          separators=(",", ":"), default=str).encode("utf-8")
        material = (self.previous_hash + "|").encode("utf-8") + body
        return hashlib.sha256(material).hexdigest()
