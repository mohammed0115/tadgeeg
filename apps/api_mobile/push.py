"""
Push notification dispatcher — Phase 2.1.

Provides one entry point — ``dispatch(user, title, body, data, channels=None)``
— that fans out a single payload to whatever channels the user has registered.

The shipping channels (FCM, APNs) are pluggable adapters. The default channel
when no live credentials are configured is ``MockChannel`` which logs to
``finai.push`` and stores the payload on the device row so the mobile-team
can verify wiring without a Firebase project.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

logger = logging.getLogger("finai.push")


@dataclass
class PushPayload:
    title: str
    body: str
    data: dict = field(default_factory=dict)
    sound: str = "default"
    badge: Optional[int] = None
    deep_link: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Channels
# ─────────────────────────────────────────────────────────────────────────────

class BaseChannel:
    """Channel adapter contract — one method, send()."""
    name = "base"

    def send(self, device, payload: PushPayload) -> dict:
        raise NotImplementedError


class MockChannel(BaseChannel):
    """Default channel — logs the payload and returns a fake message id.

    Useful in development and CI; the QA team verifies wiring by reading
    server logs / database, then swaps in a live channel via settings."""

    name = "mock"

    def send(self, device, payload: PushPayload) -> dict:
        logger.info(
            "[push.mock] %s → %s/%s '%s' data=%s",
            device.user_id, device.platform, (device.push_token or "")[:12],
            payload.title, payload.data,
        )
        return {"channel": "mock", "message_id": f"mock-{device.id}", "ok": True}


class FCMChannel(BaseChannel):
    """Firebase Cloud Messaging adapter.

    Activated when ``settings.FCM_SERVER_KEY`` is set. Requires the
    ``requests`` library, which is already a transitive dep. Falls back to
    MockChannel if the key is missing.
    """
    name = "fcm"

    def send(self, device, payload: PushPayload) -> dict:
        key = getattr(settings, "FCM_SERVER_KEY", "")
        if not key:
            return MockChannel().send(device, payload)
        if not device.push_token:
            return {"channel": "fcm", "ok": False, "error": "device has no push_token"}

        try:
            import requests
            res = requests.post(
                "https://fcm.googleapis.com/fcm/send",
                headers={"Authorization": f"key={key}", "Content-Type": "application/json"},
                json={
                    "to": device.push_token,
                    "notification": {
                        "title": payload.title,
                        "body":  payload.body,
                        "sound": payload.sound,
                        "badge": payload.badge,
                    },
                    "data": payload.data,
                },
                timeout=10,
            )
            return {"channel": "fcm", "ok": res.ok, "status": res.status_code,
                    "response": res.text[:200]}
        except Exception as exc:
            logger.error("[push.fcm] dispatch failed: %s", exc)
            return {"channel": "fcm", "ok": False, "error": str(exc)}


class APNsChannel(BaseChannel):
    """Apple Push Notification adapter — stub, returns mock by default.

    A real implementation would use ``aioapns`` or ``apns2`` with the team's
    .p8 key. Wiring it in is a small follow-up once the iOS team supplies
    the credentials.
    """
    name = "apns"

    def send(self, device, payload: PushPayload) -> dict:
        if not getattr(settings, "APNS_KEY_ID", ""):
            return MockChannel().send(device, payload)
        # Real implementation deferred — the mobile team hasn't shipped a
        # signed bundle yet. When they do, drop in apns2 here.
        logger.warning("[push.apns] APNS_KEY_ID set but APNs sender not implemented")
        return MockChannel().send(device, payload)


def _channel_for(device) -> BaseChannel:
    if device.platform == device.Platform.IOS:
        return APNsChannel()
    return FCMChannel()  # Android + Web both use FCM in practice


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def dispatch(user, payload: PushPayload, *, only_active=True) -> list[dict]:
    """Send ``payload`` to every device registered to ``user``.

    Returns one dict per device with the channel adapter's response, so the
    caller can log delivery success in an audit row.
    """
    from .models import MobileDevice

    qs = MobileDevice.objects.filter(user=user)
    if only_active:
        qs = qs.filter(is_active=True)

    out: list[dict] = []
    for device in qs:
        try:
            result = _channel_for(device).send(device, payload)
        except Exception as exc:
            logger.error("[push] dispatch failed for device %s: %s", device.id, exc)
            result = {"channel": "error", "ok": False, "error": str(exc)}
        result["device_id"] = str(device.id)
        out.append(result)
    return out


def notify_invoice_needs_action(invoice, recipient) -> list[dict]:
    """Convenience: send the standard "needs your approval" notification."""
    payload = PushPayload(
        title="Tadgeeg — needs approval",
        body=f"Invoice {invoice.invoice_number or str(invoice.pk)[:8]} flagged "
             f"({invoice.risk_level or 'medium'}). Tap to review.",
        data={
            "type": "invoice.needs_action",
            "invoice_id": str(invoice.pk),
            "vendor_name": invoice.vendor_name or "",
            "total_amount": str(invoice.total_amount or ""),
        },
        deep_link=f"tadgeeg://invoices/{invoice.pk}",
    )
    return dispatch(recipient, payload)
