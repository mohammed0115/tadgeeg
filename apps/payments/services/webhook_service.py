"""Webhook entry point.

The flow is: factory → verify_webhook → parse_webhook → match
transaction → drive state transition through PaymentService. None of
this code knows which provider it is talking to; the adapter handles
all provider-specific shapes.
"""
from __future__ import annotations

import logging
from typing import Tuple

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import (
    GatewayError,
    WebhookEvent,
    WebhookVerificationError,
)
from apps.payments.gateways.factory import get_payment_gateway
from apps.payments.models import (
    FailedWebhookEvent,
    PaymentLog,
    PaymentTransaction,
)
from apps.payments.services.payment_service import PaymentService


logger = logging.getLogger("payments.webhook")


class WebhookResult:
    OK             = "ok"
    IGNORED        = "ignored"
    UNVERIFIED     = "unverified"
    UNKNOWN_TXN    = "unknown_transaction"
    BAD_PAYLOAD    = "bad_payload"


def process_webhook(provider: str, request) -> Tuple[str, int]:
    """Return (result_code, http_status) for the calling view to relay.

    HTTP status is intentionally 200 even for ignored/unknown events so
    providers don't escalate retries — but the result code lets us
    surface anomalies in logs / metrics.

    Anything that doesn't reach a clean ``OK`` is also written to the
    FailedWebhookEvent dead-letter queue so an operator can replay it
    after fixing the underlying issue.
    """
    # Strict-mode: refuse webhooks for any provider other than the currently
    # configured one. Allows operators to switch providers safely without
    # leaving the URL surface open to stale signing keys.
    if getattr(settings, "PAYMENT_STRICT_WEBHOOK_PROVIDER", True):
        active = (getattr(settings, "PAYMENT_PROVIDER", "") or "").strip().lower()
        if active and provider != active:
            logger.warning(
                "Webhook %s rejected — strict-mode requires provider==%s",
                provider, active,
            )
            return WebhookResult.IGNORED, 404

    try:
        gateway = get_payment_gateway(provider)
    except ImproperlyConfigured as exc:
        logger.warning("Webhook dispatched to unconfigured provider %s: %s", provider, exc)
        return WebhookResult.IGNORED, 400

    # 1. Verify signature first — never trust payload contents otherwise.
    try:
        if not gateway.verify_webhook(request):
            logger.warning("Webhook %s rejected — verification failed", provider)
            _dlq(provider, FailedWebhookEvent.Reason.UNVERIFIED,
                 "Signature/verification failed", request)
            return WebhookResult.UNVERIFIED, 401
    except WebhookVerificationError as exc:
        logger.warning("Webhook %s verification raised: %s", provider, exc)
        _dlq(provider, FailedWebhookEvent.Reason.UNVERIFIED, str(exc), request)
        return WebhookResult.UNVERIFIED, 401

    # 2. Parse payload into our normalised event shape.
    try:
        event: WebhookEvent = gateway.parse_webhook(request)
    except (WebhookVerificationError, ValueError) as exc:
        logger.warning("Webhook %s payload parse failed: %s", provider, exc)
        _dlq(provider, FailedWebhookEvent.Reason.BAD_PAYLOAD, str(exc), request)
        return WebhookResult.BAD_PAYLOAD, 400

    if not event.provider_payment_id:
        _dlq(provider, FailedWebhookEvent.Reason.BAD_PAYLOAD,
             "Missing provider_payment_id", request)
        return WebhookResult.BAD_PAYLOAD, 400

    # 3. Match transaction.
    txn = (
        PaymentTransaction.objects
        .filter(provider=provider, provider_payment_id=event.provider_payment_id)
        .first()
    )
    if txn is None:
        logger.warning(
            "Webhook %s for unknown provider_payment_id %s — recording in DLQ",
            provider, event.provider_payment_id,
        )
        _dlq(provider, FailedWebhookEvent.Reason.UNKNOWN_TXN,
             f"No transaction for provider_payment_id={event.provider_payment_id}",
             request)
        return WebhookResult.UNKNOWN_TXN, 200

    # 4. Always persist the raw webhook for audit before mutating state.
    txn.raw_webhook = event.raw_payload or {}
    txn.save(update_fields=["raw_webhook", "updated_at"])
    PaymentLog.objects.create(
        transaction=txn,
        event_type="webhook_received",
        status_before=txn.status,
        status_after=txn.status,
        message=f"Webhook from {provider} (status={event.status})",
        payload=event.raw_payload or {},
    )

    # 5. Drive the state transition via PaymentService.
    svc = PaymentService()
    if event.status == PaymentStatus.PAID:
        svc.mark_paid(txn, payload=event.raw_payload)
    elif event.status == PaymentStatus.FAILED:
        svc.mark_failed(txn, reason="Failed via webhook", payload=event.raw_payload)
    elif event.status == PaymentStatus.CANCELED:
        svc.mark_canceled(txn, payload=event.raw_payload)
    else:
        # Non-terminal update — record and move on.
        logger.info(
            "Webhook %s for txn %s reported status=%s — recorded, no state change",
            provider, txn.id, event.status,
        )

    return WebhookResult.OK, 200


def _dlq(provider: str, reason, message: str, request) -> None:
    """Capture an unprocessable webhook for forensic review + replay."""
    try:
        FailedWebhookEvent.objects.create(
            provider=provider,
            reason=reason,
            message=(message or "")[:512],
            body=request.body or b"",
            headers={k: v for k, v in request.META.items()
                     if k.startswith("HTTP_") or k in ("CONTENT_TYPE", "CONTENT_LENGTH")},
            remote_ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
        )
    except Exception:  # pragma: no cover — DLQ failure must never break the webhook
        logger.exception("Could not write to FailedWebhookEvent DLQ")
