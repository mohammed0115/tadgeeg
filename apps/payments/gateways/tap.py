"""Tap Payments adapter.

Tap uses the ``/v2/charges`` endpoint. Customer information is mandatory.
The charge response includes ``transaction.url`` which is the hosted
payment page the user must be redirected to.

Docs: https://developers.tap.company/reference/create
Webhook verification: Tap sends ``hashstring`` in the body and supports a
``hash_string`` header — both can be recomputed from the charge id +
amount + currency + status + a shared secret (configured per-merchant
in the Tap dashboard, not auto-generated). The adapter ships with a
hash-based verifier; deployments must set TAP_WEBHOOK_SECRET.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings

from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import (
    BasePaymentGateway,
    GatewayError,
    GatewayResponse,
    WebhookEvent,
    WebhookVerificationError,
)


logger = logging.getLogger("payments.tap")

_DEFAULT_BASE_URL = "https://api.tap.company/v2"
_TIMEOUT = 20

_STATUS_MAP = {
    "initiated":  PaymentStatus.REDIRECT_REQUIRED,
    "in_progress": PaymentStatus.INITIATED,
    "captured":   PaymentStatus.PAID,
    "authorized": PaymentStatus.INITIATED,
    "declined":   PaymentStatus.FAILED,
    "failed":     PaymentStatus.FAILED,
    "abandoned":  PaymentStatus.CANCELED,
    "cancelled":  PaymentStatus.CANCELED,
    "void":       PaymentStatus.CANCELED,
    "timedout":   PaymentStatus.EXPIRED,
    "expired":    PaymentStatus.EXPIRED,
    "refunded":   PaymentStatus.REFUNDED,
    "unknown":    PaymentStatus.PENDING,
}


class TapGateway(BasePaymentGateway):
    PROVIDER = "tap"

    def __init__(self):
        self.secret_key     = getattr(settings, "TAP_SECRET_KEY", "") or ""
        self.public_key     = getattr(settings, "TAP_PUBLIC_KEY", "") or ""
        self.base_url       = (getattr(settings, "TAP_BASE_URL", "") or _DEFAULT_BASE_URL).rstrip("/")
        self.webhook_url    = getattr(settings, "TAP_WEBHOOK_URL", "") or ""
        self.redirect_url   = getattr(settings, "TAP_REDIRECT_URL", "") or ""
        self.webhook_secret = getattr(settings, "TAP_WEBHOOK_SECRET", "") or ""

    # ----------------------------------------------------------- helpers

    def _headers(self):
        if not self.secret_key:
            raise GatewayError("TAP_SECRET_KEY is not configured.")
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type":  "application/json",
        }

    def map_provider_status(self, provider_status: str) -> str:
        return _STATUS_MAP.get((provider_status or "").lower(), PaymentStatus.PENDING)

    # ------------------------------------------------------------ create

    def create_payment(self, transaction) -> GatewayResponse:
        # Tap requires a first/last name + an email or phone. If the
        # caller hasn't supplied any, we fall back to placeholders keyed
        # on the transaction id so the API call still succeeds in test.
        user = getattr(transaction, "user", None)
        first = (getattr(user, "first_name", "") or "").strip() or "Customer"
        last  = (getattr(user, "last_name", "")  or "").strip() or str(transaction.id)[:8]
        email = (getattr(user, "email", "")     or "").strip() or f"no-reply+{transaction.id}@tadgeeg.local"

        body = {
            "amount":   str(Decimal(transaction.amount).quantize(Decimal("0.01"))),
            "currency": transaction.currency or "SAR",
            "threeDSecure": True,
            "save_card":    False,
            "description":  f"{transaction.purpose}:{transaction.id}",
            "metadata": {
                "transaction_id":  str(transaction.id),
                "organization_id": str(transaction.organization_id),
            },
            "reference": {
                "transaction": str(transaction.id),
                "order":       str(transaction.id),
            },
            "receipt": {"email": False, "sms": False},
            "customer": {
                "first_name": first,
                "last_name":  last,
                "email":      email,
            },
            "source": {"id": "src_all"},
            "redirect": {"url": transaction.success_url or self.redirect_url},
            "post":     {"url": self.webhook_url},
        }
        try:
            r = requests.post(
                f"{self.base_url}/charges",
                json=body, headers=self._headers(), timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GatewayError(f"Tap request failed: {exc}") from exc
        if r.status_code >= 400:
            raise GatewayError(
                f"Tap create_payment HTTP {r.status_code}: {r.text[:300]}"
            )
        return self._gateway_response(r.json())

    # ---------------------------------------------------------- retrieve

    def retrieve_payment(self, provider_payment_id: str) -> GatewayResponse:
        try:
            r = requests.get(
                f"{self.base_url}/charges/{provider_payment_id}",
                headers=self._headers(), timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GatewayError(f"Tap retrieve failed: {exc}") from exc
        if r.status_code >= 400:
            raise GatewayError(
                f"Tap retrieve_payment HTTP {r.status_code}: {r.text[:300]}"
            )
        return self._gateway_response(r.json())

    # ------------------------------------------------------------ webhook

    def verify_webhook(self, request) -> bool:
        if not self.webhook_secret:
            logger.warning("TAP_WEBHOOK_SECRET is not set — refusing to verify webhook")
            return False
        provided = request.META.get("HTTP_HASHSTRING") or request.META.get("HTTP_HASH_STRING") or ""
        if not provided:
            return False
        body = request.body or b""
        # HMAC-SHA256 of the raw body with the shared secret.
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(provided.strip().lower(), expected)

    def parse_webhook(self, request) -> WebhookEvent:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookVerificationError(f"Invalid webhook body: {exc}") from exc
        provider_status = (payload.get("status") or "").lower()
        return WebhookEvent(
            provider=self.PROVIDER,
            provider_payment_id=str(payload.get("id") or ""),
            status=self.map_provider_status(provider_status),
            amount=_safe_decimal(payload.get("amount")),
            currency=payload.get("currency"),
            raw_payload=payload,
        )

    # ------------------------------------------------------------ refund

    def refund_payment(self, transaction, amount: Optional[Decimal] = None) -> GatewayResponse:
        body = {
            "charge_id": transaction.provider_payment_id,
            "currency":  transaction.currency or "SAR",
            "reason":    "requested_by_customer",
            "metadata":  {"transaction_id": str(transaction.id)},
        }
        if amount is not None:
            body["amount"] = str(Decimal(amount).quantize(Decimal("0.01")))
        try:
            r = requests.post(
                f"{self.base_url}/refunds",
                json=body, headers=self._headers(), timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GatewayError(f"Tap refund failed: {exc}") from exc
        if r.status_code >= 400:
            raise GatewayError(
                f"Tap refund HTTP {r.status_code}: {r.text[:300]}"
            )
        return self._gateway_response(r.json())

    # ---------------------------------------------------------- shaping

    def _gateway_response(self, data: dict) -> GatewayResponse:
        return GatewayResponse(
            provider=self.PROVIDER,
            provider_payment_id=str(data.get("id") or ""),
            provider_reference=str(((data.get("reference") or {}).get("order") or "")),
            checkout_url=((data.get("transaction") or {}).get("url") or ""),
            status=self.map_provider_status((data.get("status") or "").lower()),
            raw_response=data,
        )


def _safe_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
