"""SMS channel — Twilio when ``TWILIO_*`` settings are present, mock otherwise.

We deliberately do NOT add the ``twilio`` SDK as a hard dependency; in dev /
CI the channel logs the message so QA can verify routing without a paid Twilio
account.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .base import BaseChannel, Notification

logger = logging.getLogger("finai.alerts")


class SMSChannel(BaseChannel):
    name = "sms"

    def target_label(self, config: dict) -> str:
        nums = config.get("to") or []
        if isinstance(nums, str):
            nums = [nums]
        return ", ".join(nums)

    def send(self, config: dict, notif: Notification) -> dict:
        nums = config.get("to") or []
        if isinstance(nums, str):
            nums = [nums]
        if not nums:
            return {"ok": False, "error": "no phone numbers configured"}

        # Short body — SMS limit ≈ 160 chars.
        text = f"[Tadgeeg/{notif.severity}] {notif.summary or notif.title}"
        if notif.deep_link:
            text += f" {notif.deep_link}"
        text = text[:300]

        sid    = getattr(settings, "TWILIO_ACCOUNT_SID", "")
        token  = getattr(settings, "TWILIO_AUTH_TOKEN", "")
        sender = getattr(settings, "TWILIO_FROM_NUMBER", "")

        if not (sid and token and sender):
            logger.info("[sms-channel.mock] would send to %s: %s", nums, text)
            return {"ok": True, "mock": True, "delivered_to": nums, "preview": text}

        try:
            from twilio.rest import Client
            client = Client(sid, token)
            results = []
            for num in nums:
                msg = client.messages.create(body=text, from_=sender, to=num)
                results.append({"to": num, "sid": msg.sid})
            return {"ok": True, "results": results}
        except ImportError:
            logger.warning("[sms-channel] twilio package not installed; falling back to mock")
            return {"ok": True, "mock": True, "preview": text}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:240]}
