"""
Alert dispatcher — Phase 3.2.

Public entry points:

  • ``dispatch_for_anomaly(hit)`` — given a streaming.AnomalyHit, find every
    matching active AlertRule in the org and fan out the notification to its
    configured channels.

The dispatcher applies:

  • severity floor (rule.min_severity must be ≤ hit severity)
  • per-detector filter (rule.trigger_detector either blank or matches)
  • cooldown — same (rule, dedup_key) within ``cooldown_minutes`` is
    persisted as ``status=SUPPRESSED`` rather than re-sent
  • per-channel send + result capture, one AlertEvent per (rule, channel)

Channel failures are isolated — a Slack outage doesn't abort the email send.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterable

from django.utils import timezone

from apps.alerts.channels.base import Notification
from apps.alerts.channels.email   import EmailChannel
from apps.alerts.channels.sms     import SMSChannel
from apps.alerts.channels.slack   import SlackChannel
from apps.alerts.channels.teams   import TeamsChannel
from apps.alerts.channels.webhook import WebhookChannel
from apps.alerts.models import AlertEvent, AlertRule

logger = logging.getLogger("finai.alerts")


_CHANNEL_REGISTRY = {
    "email":   EmailChannel(),
    "sms":     SMSChannel(),
    "slack":   SlackChannel(),
    "teams":   TeamsChannel(),
    "webhook": WebhookChannel(),
}


_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


# ─────────────────────────────────────────────────────────────────────────────
# Rule matching
# ─────────────────────────────────────────────────────────────────────────────

def _matches(rule: AlertRule, *, severity: str, detector: str = "") -> bool:
    """Does ``rule`` apply to this trigger?"""
    if not rule.is_active:
        return False
    if _SEVERITY_RANK.get(severity, 0) < _SEVERITY_RANK.get(rule.min_severity, 0):
        return False
    if rule.trigger_detector and detector and rule.trigger_detector != detector:
        return False
    return True


def _is_in_cooldown(rule: AlertRule, dedup_key: str) -> bool:
    """True if a SENT or ACKNOWLEDGED event for the same dedup_key landed within
    the rule's cooldown window."""
    if not dedup_key or not rule.cooldown_minutes:
        return False
    cutoff = timezone.now() - timedelta(minutes=rule.cooldown_minutes)
    return AlertEvent.objects.filter(
        rule=rule, dedup_key=dedup_key,
        status__in=[AlertEvent.Status.SENT, AlertEvent.Status.ACKNOWLEDGED],
        sent_at__gte=cutoff,
    ).exists()


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────

def _build_notification_from_anomaly(hit) -> Notification:
    """Render an AnomalyHit into the channel-agnostic Notification."""
    invoice_link = (
        f"/invoices/{hit.invoice_id}/" if hit.invoice_id else ""
    )
    return Notification(
        title=f"Anomaly: {hit.detector.replace('_', ' ').title()}",
        body=(
            f"Detector: {hit.detector}\n"
            f"Vendor:   {hit.vendor_name or '-'}\n\n"
            f"{hit.explanation}\n"
        ),
        severity=hit.severity,
        summary=f"{hit.detector}: {(hit.explanation or '')[:120]}",
        deep_link=invoice_link,
        data={
            "hit_id":       str(hit.id) if getattr(hit, "id", None) else "",
            "invoice_id":   hit.invoice_id,
            "vendor_name":  hit.vendor_name,
            "detector":     hit.detector,
            "details":      hit.details if isinstance(hit.details, dict) else {},
        },
    )


def dispatch_for_anomaly(hit) -> dict:
    """Find matching AlertRules and fan out the notification.

    ``hit`` may be a streaming.AnomalyHit Django row OR a detectors.AnomalyHit
    dataclass — both expose the same surface (detector, severity, vendor_name,
    invoice_id, explanation, details, organization_id).
    """
    org_id = getattr(hit, "organization_id", None)
    if not org_id:
        return {"sent": 0, "suppressed": 0, "failed": 0, "rules_matched": 0}

    detector = getattr(hit, "detector", "") or ""
    severity = getattr(hit, "severity", "medium") or "medium"
    dedup_key = f"{detector}:{getattr(hit, 'vendor_name', '') or ''}"

    notif = _build_notification_from_anomaly(hit)

    rules = list(
        AlertRule.objects.filter(
            organization_id=org_id, is_active=True,
            trigger_type=AlertRule.TriggerType.ANOMALY,
        )
    )
    summary = {"sent": 0, "suppressed": 0, "failed": 0, "rules_matched": 0,
               "events": []}

    for rule in rules:
        if not _matches(rule, severity=severity, detector=detector):
            continue
        summary["rules_matched"] += 1

        if _is_in_cooldown(rule, dedup_key):
            event = AlertEvent.objects.create(
                organization_id=org_id, rule=rule,
                channel_type="*", channel_target="(cooldown)",
                status=AlertEvent.Status.SUPPRESSED,
                source_type="anomaly_hit",
                source_id=str(getattr(hit, "id", "") or ""),
                severity=severity, summary=notif.summary,
                payload=notif.data, dedup_key=dedup_key,
                error_message=f"cooldown {rule.cooldown_minutes} min",
            )
            summary["suppressed"] += 1
            summary["events"].append(str(event.id))
            continue

        for channel_cfg in (rule.channels or []):
            ctype = (channel_cfg.get("type") or "").lower()
            adapter = _CHANNEL_REGISTRY.get(ctype)
            if adapter is None:
                AlertEvent.objects.create(
                    organization_id=org_id, rule=rule,
                    channel_type=ctype or "?", channel_target="",
                    status=AlertEvent.Status.FAILED,
                    error_message=f"unknown channel type: {ctype}",
                    severity=severity, summary=notif.summary,
                    dedup_key=dedup_key,
                    source_type="anomaly_hit",
                    source_id=str(getattr(hit, "id", "") or ""),
                    payload=notif.data,
                )
                summary["failed"] += 1
                continue

            try:
                result = adapter.send(channel_cfg, notif)
            except Exception as exc:
                logger.exception("[alerts] channel %s crashed", ctype)
                result = {"ok": False, "error": f"crash: {exc}"}

            ok = bool(result.get("ok"))
            event = AlertEvent.objects.create(
                organization_id=org_id, rule=rule,
                channel_type=ctype,
                channel_target=adapter.target_label(channel_cfg),
                status=(AlertEvent.Status.SENT if ok else AlertEvent.Status.FAILED),
                error_message="" if ok else (result.get("error") or "")[:512],
                severity=severity, summary=notif.summary,
                payload={**notif.data, "channel_result": result},
                dedup_key=dedup_key,
                source_type="anomaly_hit",
                source_id=str(getattr(hit, "id", "") or ""),
            )
            if ok:
                summary["sent"] += 1
            else:
                summary["failed"] += 1
            summary["events"].append(str(event.id))

    return summary
