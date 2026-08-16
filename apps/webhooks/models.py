"""
Outbound webhooks — let customers subscribe to invoice/audit events so their
ERPs can react in real time.

Two models:
- ``WebhookEndpoint`` — a subscription URL belonging to one organization.
- ``WebhookDelivery`` — every dispatch attempt (success or failure) with
  status code, response body, retry counter, and HMAC signature replayed.

Events fired:
    invoice.created       — new invoice persisted
    invoice.approved      — invoice marked approved
    invoice.rejected      — invoice marked rejected
    invoice.flagged       — risk_level escalated to high/critical
    audit.completed       — audit run finished (V2 pipeline)
    document.uploaded     — typed document upload completed
"""
from __future__ import annotations

import uuid
from django.db import models


_EVENT_CHOICES = [
    ("invoice.created",   "Invoice created"),
    ("invoice.approved",  "Invoice approved"),
    ("invoice.rejected",  "Invoice rejected"),
    ("invoice.flagged",   "Invoice flagged"),
    ("audit.completed",   "Audit completed"),
    ("document.uploaded", "Document uploaded"),
]


class WebhookEndpoint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE, related_name="webhook_endpoints",
    )
    url = models.URLField(max_length=500)
    secret = models.CharField(
        max_length=64,
        help_text="HMAC-SHA256 secret. We sign every delivery with this so receivers can verify authenticity.",
    )
    events = models.JSONField(
        default=list,
        help_text='List of event types to subscribe to, e.g. ["invoice.created", "invoice.flagged"]',
    )
    is_active = models.BooleanField(default=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL, null=True, related_name="created_webhooks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "webhook_endpoints"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self):
        return f"{self.url} ({'active' if self.is_active else 'paused'})"


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING   = "pending",   "Pending"
        SUCCESS   = "success",   "Success"
        FAILED    = "failed",    "Failed"
        RETRYING  = "retrying",  "Retrying"
        EXHAUSTED = "exhausted", "Exhausted (gave up)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries",
    )
    event_type = models.CharField(max_length=64, choices=_EVENT_CHOICES)
    # Nullable keeps historical deliveries valid; new emits populate a stable
    # SHA-256 event key and are unique per subscribed endpoint.
    event_key = models.CharField(max_length=64, null=True, blank=True)
    payload = models.JSONField(default=dict)
    signature = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_response_body = models.TextField(blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "webhook_deliveries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["endpoint", "created_at"]),
            models.Index(fields=["status", "next_retry_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["endpoint", "event_key"], name="unique_webhook_endpoint_event"),
        ]
