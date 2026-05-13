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
