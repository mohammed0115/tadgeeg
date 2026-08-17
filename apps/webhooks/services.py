"""
Webhook dispatch service.

The public entry point is ``emit(event_type, organization, payload)``. It
fans out to every active subscription, records a ``WebhookDelivery`` row,
and ships it. Failures are retried with exponential backoff (1m, 5m, 30m,
2h, 8h) for up to 5 attempts before being marked exhausted.

Dispatch runs in a background thread (via ``core.services.async_runner``)
so the originating request never blocks on a slow webhook receiver.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger("finai")

# Retry schedule (seconds). Index = attempt number.
_RETRY_BACKOFF = [60, 300, 1800, 7200, 28800]
MAX_ATTEMPTS = len(_RETRY_BACKOFF)


def _sign(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex digest. Receiver verifies via the X-Tadgeeg-Signature header."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def emit(event_type: str, organization, payload: dict) -> int:
    """Fire-and-forget dispatch. Returns the number of subscribed endpoints."""
    if organization is None:
        return 0
    try:
        from .models import WebhookEndpoint, WebhookDelivery
    except Exception:
        # App not migrated yet — degrade silently.
        return 0

    endpoints = list(WebhookEndpoint.objects.filter(
        organization=organization, is_active=True,
    ))
    targets = [e for e in endpoints if not e.events or event_type in e.events]
    if not targets:
        return 0

    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    event_key = hashlib.sha256(event_type.encode("utf-8") + b"\x1f" + body).hexdigest()
    deliveries = []
    for ep in targets:
        sig = _sign(ep.secret or "", body)
        d, created = WebhookDelivery.objects.get_or_create(
            endpoint=ep,
            event_key=event_key,
            defaults={
                "event_type": event_type,
                "payload": payload,
                "signature": sig,
                "status": WebhookDelivery.Status.PENDING,
            },
        )
        if created:
            deliveries.append(d)

    # Dispatch asynchronously so the calling request returns immediately.
    from core.services.async_runner import run_in_background
    for d in deliveries:
        run_in_background(_deliver, d.id)
    return len(deliveries)


def _deliver(delivery_id) -> None:
    """Single delivery attempt (with retry-on-fail bookkeeping)."""
    import urllib.request
    import urllib.error

    from .models import WebhookDelivery

    try:
        d = WebhookDelivery.objects.select_related("endpoint").get(id=delivery_id)
    except WebhookDelivery.DoesNotExist:
        return

    ep = d.endpoint
    from core.security.outbound_guard import assert_outbound_allowed
    try:
        assert_outbound_allowed(ep.url)
    except ValueError as exc:
        d.status = WebhookDelivery.Status.EXHAUSTED
        d.last_response_body = f"outbound URL rejected: {exc}"[:2000]
        d.completed_at = timezone.now()
        d.save(update_fields=["status", "last_response_body", "completed_at", "updated_at"])
        return

    body = json.dumps(d.payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Tadgeeg-Webhooks/1.0",
        "X-Tadgeeg-Event": d.event_type,
        "X-Tadgeeg-Delivery-Id": str(d.id),
        "X-Tadgeeg-Signature": d.signature or _sign(ep.secret or "", body),
        "X-Tadgeeg-Timestamp": timezone.now().isoformat(),
    }

    req = urllib.request.Request(ep.url, data=body, headers=headers, method="POST")
    d.attempt_count += 1
    success = False
    response_body = ""
    status_code = None

    try:
        # The outbound guard above restricts scheme and destination.
        with urllib.request.urlopen(req, timeout=8) as resp:  # nosec B310
            status_code = resp.status
            response_body = resp.read(2048).decode("utf-8", errors="replace")
            success = 200 <= status_code < 300
    except urllib.error.HTTPError as e:
        status_code = e.code
        try:
            response_body = e.read(2048).decode("utf-8", errors="replace")
        except Exception:
            response_body = str(e)[:200]
    except Exception as exc:
        response_body = f"connection error: {exc}"[:500]

    d.last_response_status = status_code or 0
    d.last_response_body = response_body[:2000]

    if success:
        d.status = WebhookDelivery.Status.SUCCESS
        d.completed_at = timezone.now()
        ep.failure_count = 0
        ep.last_success_at = timezone.now()
        ep.last_response_status = status_code
        ep.save(update_fields=["failure_count", "last_success_at", "last_response_status"])
    elif d.attempt_count >= MAX_ATTEMPTS:
        d.status = WebhookDelivery.Status.EXHAUSTED
        d.completed_at = timezone.now()
        ep.failure_count += 1
        ep.last_failure_at = timezone.now()
        ep.last_response_status = status_code
        ep.save(update_fields=["failure_count", "last_failure_at", "last_response_status"])
        logger.warning("[webhooks] giving up on delivery %s after %d attempts", d.id, d.attempt_count)
    else:
        # Schedule next retry with exponential backoff.
        backoff = _RETRY_BACKOFF[min(d.attempt_count - 1, len(_RETRY_BACKOFF) - 1)]
        d.status = WebhookDelivery.Status.RETRYING
        d.next_retry_at = timezone.now() + timedelta(seconds=backoff)
        ep.failure_count += 1
        ep.last_failure_at = timezone.now()
        ep.last_response_status = status_code
        ep.save(update_fields=["failure_count", "last_failure_at", "last_response_status"])

    d.save()


def retry_pending() -> int:
    """Drain the pending-retry queue. Call from a periodic task / cron.

    Returns the number of deliveries reattempted.
    """
    from .models import WebhookDelivery
    from core.services.async_runner import run_in_background

    now = timezone.now()
    due = list(WebhookDelivery.objects.filter(
        status=WebhookDelivery.Status.RETRYING,
        next_retry_at__lte=now,
    ).values_list("id", flat=True)[:200])
    for did in due:
        run_in_background(_deliver, did)
    return len(due)
