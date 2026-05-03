"""Generic webhook channel — HMAC-SHA256 signed JSON POST.

Config fields:
  url     — endpoint to POST to.
  secret  — shared secret. If set, the request carries a ``X-Tadgeeg-Signature``
            header equal to ``sha256=<hex>``, where the hex is HMAC-SHA256 over
            the raw request body. The receiver must verify the signature
            before trusting the payload.
  headers — optional dict of extra headers.
  retries — int (default 1). Server-side retry on 5xx / network error.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

from .base import BaseChannel, Notification

logger = logging.getLogger("finai.alerts")


def sign_payload(secret: str, body: bytes) -> str:
    """Build the ``X-Tadgeeg-Signature`` header value."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_payload(secret: str, body: bytes, header_value: str) -> bool:
    """Constant-time signature check the receiving server can copy-paste."""
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, header_value or "")


class WebhookChannel(BaseChannel):
    name = "webhook"

    def target_label(self, config: dict) -> str:
        return (config.get("url") or "")[:240]

    def send(self, config: dict, notif: Notification) -> dict:
        url = (config.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "missing url"}

        secret  = (config.get("secret") or "").strip()
        retries = int(config.get("retries") or 1)
        extra   = config.get("headers") or {}

        body = json.dumps({
            "event":     "audit.alert",
            "title":     notif.title,
            "summary":   notif.summary,
            "body":      notif.body,
            "severity":  notif.severity,
            "deep_link": notif.deep_link,
            "data":      notif.data,
            "ts":        int(time.time()),
        }, separators=(",", ":")).encode("utf-8")

        headers = {"Content-Type": "application/json", **extra}
        if secret:
            headers["X-Tadgeeg-Signature"] = sign_payload(secret, body)

        last_error = ""
        for attempt in range(max(1, retries)):
            try:
                import requests
                r = requests.post(url, data=body, headers=headers, timeout=10)
                if r.ok:
                    return {"ok": True, "status": r.status_code, "attempt": attempt + 1}
                if r.status_code < 500:
                    return {"ok": False, "status": r.status_code,
                            "response": r.text[:120], "attempt": attempt + 1}
                last_error = f"{r.status_code} {r.text[:120]}"
            except ImportError:
                logger.info("[webhook-channel.mock] %s headers=%s body=%s",
                            url, list(headers), body[:240])
                return {"ok": True, "mock": True}
            except Exception as exc:
                last_error = str(exc)[:240]
        return {"ok": False, "error": last_error}
