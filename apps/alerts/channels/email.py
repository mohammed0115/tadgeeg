"""Email channel — uses Django's configured SMTP backend."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .base import BaseChannel, Notification

logger = logging.getLogger("finai.alerts")


class EmailChannel(BaseChannel):
    name = "email"

    def target_label(self, config: dict) -> str:
        return ", ".join(config.get("to") or [])[:240]

    def send(self, config: dict, notif: Notification) -> dict:
        recipients = config.get("to") or []
        if isinstance(recipients, str):
            recipients = [recipients]
        if not recipients:
            return {"ok": False, "error": "no recipients configured"}

        from_email = config.get("from") or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        subject_prefix = (config.get("subject_prefix") or "[Tadgeeg]").strip()
        subject = f"{subject_prefix} {notif.title}".strip()

        # Plain-text body kept readable so SMS-fallback / log-grep stays useful.
        body = (
            f"{notif.title}\n"
            f"{'=' * len(notif.title)}\n\n"
            f"{notif.body}\n\n"
            f"Severity: {notif.severity}\n"
        )
        if notif.deep_link:
            body += f"Open: {notif.deep_link}\n"

        try:
            msg = EmailMultiAlternatives(
                subject=subject, body=body, from_email=from_email or None,
                to=recipients,
            )
            html = (
                f"<h2 style='font-family:Arial,sans-serif'>{notif.title}</h2>"
                f"<p style='font-size:14px'>{notif.body.replace(chr(10), '<br>')}</p>"
                f"<p><strong>Severity:</strong> {notif.severity}</p>"
            )
            if notif.deep_link:
                html += (f"<p><a href='{notif.deep_link}' "
                         "style='display:inline-block;padding:10px 16px;"
                         "background:#003366;color:white;border-radius:6px;"
                         "text-decoration:none'>Open in Tadgeeg</a></p>")
            msg.attach_alternative(html, "text/html")
            sent = msg.send(fail_silently=False)
            return {"ok": bool(sent), "delivered_to": recipients}
        except Exception as exc:
            logger.warning("[email-channel] send failed: %s", exc)
            return {"ok": False, "error": str(exc)[:240]}
