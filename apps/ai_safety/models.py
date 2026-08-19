"""AI Safety persistence — one model: ``AICostEvent``.

Every LM call we make is recorded here for budget enforcement and
auditor traceability. The row is append-only by convention — there is
no update path and no admin edit form. It joins on:

  • organization → who paid
  • prompt_name, prompt_version, prompt_sha → which prompt
  • model → which model produced the output (registry name)
  • user → which staff member triggered the call (nullable: nightly jobs)

Cost is denormalized at write time (the registry can change later but
the historical SAR amount must stay stable).
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.authentication.models import Organization


class AICostEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name="ai_cost_events",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="ai_cost_events",
    )

    model           = models.CharField(max_length=64)
    prompt_name     = models.CharField(max_length=120, blank=True, default="")
    prompt_version  = models.PositiveIntegerField(default=0)
    prompt_sha      = models.CharField(max_length=64, blank=True, default="")

    input_tokens    = models.PositiveIntegerField(default=0)
    output_tokens   = models.PositiveIntegerField(default=0)
    cost_usd        = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    created_at      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("organization", "created_at")),
            models.Index(fields=("organization", "model")),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}/{self.model}/{self.cost_usd}USD"


class AIUsageRecord(models.Model):
    """Append-only, tenant-owned accounting record for one provider request.

    ``estimated_cost`` is written using the model price table at request time;
    it is never recomputed from a later price table.  A failed request is also
    a record: an apparently empty invoice must not hide authentication, rate or
    transport failures.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    class FailureKind(models.TextChoices):
        NONE = "", "None"
        AUTH_401 = "auth_401", "Authentication / 401"
        RATE_LIMIT = "rate_limit", "Rate limit"
        TIMEOUT = "timeout", "Timeout"
        PAYLOAD = "payload", "Payload"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="ai_usage_records"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_usage_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    model = models.CharField(max_length=64)
    operation = models.CharField(max_length=32)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    status = models.CharField(max_length=16, choices=Status.choices)
    failure_kind = models.CharField(
        max_length=16, choices=FailureKind.choices, blank=True, default=""
    )
    latency_ms = models.PositiveIntegerField(default=0)
    document_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("organization", "created_at")),
            models.Index(fields=("organization", "operation", "created_at")),
            models.Index(fields=("organization", "status", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}/{self.operation}/{self.status}/{self.model}"


class AIUsagePayload(models.Model):
    """Short-lived diagnostic payload for one metered provider request.

    The gateway strips credentials and opaque media before persisting these
    fields.  The retention task deletes only these rows; the accounting record
    remains available for billing and audit evidence.
    """

    usage_record = models.OneToOneField(
        AIUsageRecord, on_delete=models.CASCADE, related_name="payload"
    )
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"payload:{self.usage_record_id}"


class AnalysisRequest(models.Model):
    """Immutable event for a user request to analyse one tenant document.

    A new request and a cached/debounced request are both recorded. This keeps
    the CRM count honest while allowing the caller to suppress duplicate model
    work during the cooldown window.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="analysis_requests"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="analysis_requests",
    )
    document_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_cached = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("organization", "document_id", "created_at")),
            models.Index(fields=("organization", "created_at")),
        ]

    def __str__(self) -> str:
        return f"{self.organization_id}/{self.document_id}/{self.is_cached}"
