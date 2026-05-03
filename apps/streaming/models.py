"""Persisted state for the continuous-auditing pipeline.

  • ``AnomalyHit``        — every detector trigger lands here, so the live
                            ops dashboard, alerts, and Phase 3.2 alert
                            channels can all read from a single source.
  • ``StreamProcessingLog`` — running window of (event_type, latency_ms,
                              ok) so the dashboard can show throughput
                              and p95 latency without scraping logs.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class AnomalyHit(models.Model):
    """One row per detector trigger."""

    class Severity(models.TextChoices):
        LOW      = "low",      "Low"
        MEDIUM   = "medium",   "Medium"
        HIGH     = "high",     "High"
        CRITICAL = "critical", "Critical"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization    = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="anomaly_hits",
    )
    detector        = models.CharField(max_length=64, db_index=True)
    severity        = models.CharField(max_length=12, choices=Severity.choices,
                                       default=Severity.MEDIUM, db_index=True)
    invoice_id      = models.CharField(max_length=64, blank=True, db_index=True)
    vendor_name     = models.CharField(max_length=255, blank=True, db_index=True)
    explanation     = models.TextField(blank=True)
    details         = models.JSONField(default=dict, blank=True)
    occurred_at     = models.DateTimeField(default=timezone.now, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="acknowledged_anomalies",
    )

    class Meta:
        db_table = "streaming_anomaly_hits"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["organization", "severity", "occurred_at"]),
            models.Index(fields=["organization", "detector"]),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.detector} on {self.invoice_id or '-'}"


class StreamProcessingLog(models.Model):
    """Sliding window of consumer-side metrics. Trimmed to last N rows by
    the consumer so the table stays bounded — we don't need permanent history."""

    id            = models.BigAutoField(primary_key=True)
    event_type    = models.CharField(max_length=64, db_index=True)
    stream        = models.CharField(max_length=64, blank=True)
    latency_ms    = models.PositiveIntegerField(default=0)
    ok            = models.BooleanField(default=True)
    error_message = models.CharField(max_length=255, blank=True)
    processed_at  = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "streaming_processing_log"
        ordering = ["-processed_at"]
        indexes = [
            models.Index(fields=["event_type", "processed_at"]),
        ]
