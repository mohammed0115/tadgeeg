"""
Alert routing — Phase 3.2 of the Enterprise Roadmap.

  • ``AlertRule``  — what to alert on, where to send, how often.
  • ``AlertEvent`` — every dispatch attempt persists here so the team can
                     audit who-was-told-what-and-when, and the
                     acknowledgement flow has somewhere to write back.

A rule is "matched" when an incoming AnomalyHit (or any future
``audit.*`` event) satisfies its ``trigger_*`` filters. Cooldown is per
(rule, dedup_key) and stops alert storms when the same vendor or invoice
fires repeatedly.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class AlertRule(models.Model):
    """A user-defined routing policy: trigger filters → channels."""

    class TriggerType(models.TextChoices):
        ANOMALY     = "anomaly",     "Streaming anomaly hit"
        AUDIT_CASE  = "audit_case",  "Audit case created"
        SLA_BREACH  = "sla_breach",  "SLA breached"

    class MinSeverity(models.TextChoices):
        LOW      = "low",      "Low and above"
        MEDIUM   = "medium",   "Medium and above"
        HIGH     = "high",     "High and above"
        CRITICAL = "critical", "Critical only"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="alert_rules",
    )
    name          = models.CharField(max_length=200)
    description   = models.TextField(blank=True)

    trigger_type  = models.CharField(max_length=20, choices=TriggerType.choices,
                                     default=TriggerType.ANOMALY, db_index=True)
    # Detector filter (anomaly trigger only). Blank → match every detector.
    trigger_detector = models.CharField(max_length=64, blank=True)
    min_severity     = models.CharField(max_length=10, choices=MinSeverity.choices,
                                        default=MinSeverity.MEDIUM)

    # List of channel configs, e.g.
    #   [{"type": "email", "to": ["audit@org.com"]},
    #    {"type": "slack", "webhook_url": "..."},
    #    {"type": "webhook", "url": "...", "secret": "..."}]
    channels      = models.JSONField(default=list, blank=True)

    cooldown_minutes = models.PositiveSmallIntegerField(
        default=30,
        help_text="Suppress duplicate alerts for the same dedup_key within this many minutes.",
    )
    is_active     = models.BooleanField(default=True, db_index=True)

    created_by    = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="created_alert_rules",
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "alert_rules"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"],
                                    name="alert_rule_unique_name_per_org"),
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization_id})"


class AlertEvent(models.Model):
    """One row per dispatch attempt — kept forever for the audit trail."""

    class Status(models.TextChoices):
        SENT       = "sent",       "Sent"
        FAILED     = "failed",     "Failed"
        SUPPRESSED = "suppressed", "Suppressed by cooldown"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization    = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="alert_events",
    )
    rule            = models.ForeignKey(
        AlertRule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events",
    )
    channel_type    = models.CharField(max_length=24)
    channel_target  = models.CharField(max_length=255, blank=True,
                                       help_text="Email address / Slack webhook / phone number / URL.")
    status          = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    error_message   = models.CharField(max_length=512, blank=True)

    # What this alert was about — points at either the AnomalyHit
    # or AuditCase that triggered it.
    source_type     = models.CharField(max_length=32, blank=True)
    source_id       = models.CharField(max_length=64, blank=True, db_index=True)
    severity        = models.CharField(max_length=12, blank=True)
    summary         = models.CharField(max_length=255, blank=True)
    payload         = models.JSONField(default=dict, blank=True)

    # Cooldown grouping key — same key + same rule within cooldown_minutes
    # is suppressed. Defaults to (detector, vendor) for anomaly hits.
    dedup_key       = models.CharField(max_length=255, blank=True, db_index=True)

    sent_at         = models.DateTimeField(default=timezone.now, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="acknowledged_alerts",
    )

    class Meta:
        db_table = "alert_events"
        ordering = ["-sent_at"]
        indexes = [
            models.Index(fields=["organization", "status", "sent_at"]),
            models.Index(fields=["rule", "dedup_key", "sent_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel_type}:{self.status} → {self.channel_target} ({self.summary[:30]})"
