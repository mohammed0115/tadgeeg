"""Microsoft Teams incoming-webhook channel.

Teams accepts MessageCard or AdaptiveCard JSON to its incoming-webhook URL.
We use MessageCard — it's older but ships everywhere without per-tenant setup.
"""

from __future__ import annotations

import json
import logging

from .base import BaseChannel, Notification

logger = logging.getLogger("finai.alerts")


_SEVERITY_THEME = {
    "low":      "10B981",
    "medium":   "F59E0B",
    "high":     "EF4444",
    "critical": "7F1D1D",
}


class TeamsChannel(BaseChannel):
    name = "teams"

    def target_label(self, config: dict) -> str:
        url = config.get("webhook_url") or ""
        return url.split("/webhook/", 1)[0] if "/webhook/" in url else url[:80]

    def send(self, config: dict, notif: Notification) -> dict:
        url = config.get("webhook_url") or ""
        if not url:
            return {"ok": False, "error": "missing webhook_url"}

        theme = _SEVERITY_THEME.get(notif.severity, "475569")
        card = {
            "@type":    "MessageCard",
            "@context": "https://schema.org/extensions",
            "themeColor": theme,
            "summary":  notif.summary or notif.title,
            "title":    notif.title,
            "text":     notif.body.replace("\n", "  \n"),
            "sections": [{
                "facts": [
                    {"name": "Severity", "value": notif.severity},
                ],
            }],
            "potentialAction": (
                [{
                    "@type": "OpenUri",
                    "name":  "Open invoice",
                    "targets": [{"os": "default", "uri": notif.deep_link}],
                }]
                if notif.deep_link else []
            ),
        }
        try:
            import requests
            r = requests.post(url, json=card, timeout=10)
            return {"ok": r.ok, "status": r.status_code, "response": r.text[:120]}
        except ImportError:
            logger.info("[teams-channel.mock] %s", json.dumps(card)[:240])
            return {"ok": True, "mock": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:240]}
