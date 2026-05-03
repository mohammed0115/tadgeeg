"""Slack incoming-webhook channel.

The Slack workspace admin generates an incoming webhook URL — we POST a
Block-Kit payload to it. No client library required.
"""

from __future__ import annotations

import json
import logging

from .base import BaseChannel, Notification

logger = logging.getLogger("finai.alerts")


_SEVERITY_COLOR = {
    "low":      "#10B981",
    "medium":   "#f59e0b",
    "high":     "#ef4444",
    "critical": "#7f1d1d",
}


class SlackChannel(BaseChannel):
    name = "slack"

    def target_label(self, config: dict) -> str:
        url = config.get("webhook_url") or ""
        # Don't store the secret in clear text on AlertEvent — keep just the host.
        return url.split("/services/", 1)[0] if "/services/" in url else url[:80]

    def send(self, config: dict, notif: Notification) -> dict:
        url = config.get("webhook_url") or ""
        if not url:
            return {"ok": False, "error": "missing webhook_url"}

        color = _SEVERITY_COLOR.get(notif.severity, "#475569")
        payload = {
            "text": notif.summary or notif.title,
            "attachments": [{
                "color": color,
                "title": notif.title,
                "text":  notif.body,
                "fields": [
                    {"title": "Severity", "value": notif.severity, "short": True},
                ],
                "actions": (
                    [{"type": "button", "text": "Open invoice", "url": notif.deep_link}]
                    if notif.deep_link else []
                ),
                "footer": "Tadgeeg",
            }],
        }
        try:
            import requests
            r = requests.post(url, json=payload, timeout=10)
            return {"ok": r.ok, "status": r.status_code, "response": r.text[:120]}
        except ImportError:
            logger.info("[slack-channel.mock] %s", json.dumps(payload)[:240])
            return {"ok": True, "mock": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:240]}
