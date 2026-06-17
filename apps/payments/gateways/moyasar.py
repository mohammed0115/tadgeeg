"""Moyasar adapter.

Hosted-invoice flow: we create an Invoice via ``POST /v1/invoices`` and the
customer pays on Moyasar's hosted page (``url``) — card data is entered on
Moyasar's side and NEVER touches our backend (no ``source``/PAN/CVV). Status
is confirmed via webhook (HMAC-signed if a webhook secret is configured) or
via a ``GET /invoices/<id>`` retrieve. The invoice id is stored as the
transaction's ``provider_payment_id``.

Docs: https://docs.moyasar.com/api-reference/invoices
Money handling: Moyasar takes the smallest currency unit (halalas for SAR),
so 12.50 SAR is sent as 1250.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
from decimal import Decimal
from typing import Optional

import requests
from apps.payments.gateways._http import http_get, http_post
from django.conf import settings

from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import (
    BasePaymentGateway,
    GatewayError,
    GatewayResponse,
    WebhookEvent,
    WebhookVerificationError,
)


logger = logging.getLogger("payments.moyasar")

_DEFAULT_BASE_URL = "https://api.moyasar.com/v1"
_TIMEOUT = 20

# Map Moyasar's native status strings → our internal PaymentStatus.
_STATUS_MAP = {
    "initiated":   PaymentStatus.INITIATED,
    "paid":        PaymentStatus.PAID,
    "failed":      PaymentStatus.FAILED,
    "authorized":  PaymentStatus.INITIATED,
    "captured":    PaymentStatus.PAID,
    "refunded":    PaymentStatus.REFUNDED,
    "voided":      PaymentStatus.CANCELED,
    "expired":     PaymentStatus.EXPIRED,
}


class MoyasarGateway(BasePaymentGateway):
    PROVIDER = "moyasar"

    def __init__(self):
        self.secret_key      = getattr(settings, "MOYASAR_SECRET_KEY", "") or ""
        self.publishable_key = getattr(settings, "MOYASAR_PUBLISHABLE_KEY", "") or ""
        self.base_url        = (getattr(settings, "MOYASAR_BASE_URL", "") or _DEFAULT_BASE_URL).rstrip("/")
        self.callback_url    = getattr(settings, "MOYASAR_CALLBACK_URL", "") or ""
        self.webhook_url     = getattr(settings, "MOYASAR_WEBHOOK_URL", "") or ""
        self.webhook_secret  = getattr(settings, "MOYASAR_WEBHOOK_SECRET", "") or ""

    # ----------------------------------------------------------- helpers

    def _auth(self):
        if not self.secret_key:
            raise GatewayError("MOYASAR_SECRET_KEY is not configured.")
        return (self.secret_key, "")

    @staticmethod
    def _to_smallest_unit(amount: Decimal) -> int:
        """Decimal SAR → integer halalas. Two-decimal currencies only."""
        return int((Decimal(amount) * Decimal(100)).quantize(Decimal("1")))

    @staticmethod
    def _with_tx(url: str, transaction_id) -> str:
        """Append our internal ``transaction_id=<id>`` to a redirect URL so the
        callback resolves the transaction by OUR id — Moyasar appends its own
        ``id`` (a payment id, not the invoice id we stored), which we must not
        depend on for lookup."""
        if not url:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}transaction_id={transaction_id}"

    def map_provider_status(self, provider_status: str) -> str:
        return _STATUS_MAP.get((provider_status or "").lower(), PaymentStatus.PENDING)

    # ------------------------------------------------------------ create

    def create_payment(self, transaction) -> GatewayResponse:
        # Hosted invoice flow: POST /invoices returns a Moyasar-hosted payment
        # page (``url``) where the customer enters card details on Moyasar's
        # side. We never collect or forward PAN/CVV — there is deliberately NO
        # ``source`` object (that is the /payments API, which requires card
        # data and 400s without it). ``url`` becomes our ``checkout_url``.
        # Browser LANDING (success_url): where the customer is returned after
        # paying. Stamp OUR transaction_id so the callback resolves by our id,
        # not Moyasar's echoed payment ``id``. Metadata also carries it as a
        # secondary safe fallback.
        landing = self._with_tx(transaction.success_url or self.callback_url, transaction.id)
        body = {
            "amount":      self._to_smallest_unit(transaction.amount),
            "currency":    transaction.currency or "SAR",
            "description": f"{transaction.purpose}:{transaction.id}",
            "metadata": {
                "transaction_id":  str(transaction.id),
                "organization_id": str(transaction.organization_id),
                "purpose":         transaction.purpose,
            },
        }
        if landing:
            body["success_url"] = landing
        # callback_url is SEPARATE from the browser landing: it is the
        # server-to-server notification endpoint (our signed webhook). Falls
        # back to the landing page only if no webhook URL is configured.
        body["callback_url"] = self.webhook_url or landing
        back_url = getattr(transaction, "cancel_url", "") or ""
        if back_url:
            body["back_url"] = self._with_tx(back_url, transaction.id)
        try:
            r = http_post(
                f"{self.base_url}/invoices",
                json=body, auth=self._auth(), timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GatewayError(f"Moyasar request failed: {exc}") from exc

        if r.status_code >= 400:
            raise GatewayError(
                f"Moyasar create_invoice HTTP {r.status_code}: {r.text[:300]}"
            )
        data = r.json()
        return self._gateway_response(data)

    # ---------------------------------------------------------- retrieve

    def retrieve_payment(self, provider_payment_id: str) -> GatewayResponse:
        # provider_payment_id holds the Moyasar invoice id (hosted flow), so we
        # reconcile status against /invoices/<id>, not /payments/<id>.
        try:
            r = http_get(
                f"{self.base_url}/invoices/{provider_payment_id}",
                auth=self._auth(), timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GatewayError(f"Moyasar retrieve failed: {exc}") from exc
        if r.status_code >= 400:
            raise GatewayError(
                f"Moyasar retrieve_invoice HTTP {r.status_code}: {r.text[:300]}"
            )
        return self._gateway_response(r.json())

    # ------------------------------------------------------------ webhook

    def verify_webhook(self, request) -> bool:
        """Moyasar signs webhooks with HMAC-SHA256 using your webhook secret.

        Header: ``X-Moyasar-Signature: sha256=<hex>``. If you have not
        configured a secret in the dashboard, no signature is sent and
        this returns False — do NOT process such webhooks in production.
        """
        if not self.webhook_secret:
            logger.warning("MOYASAR_WEBHOOK_SECRET is not set — refusing to verify webhook")
            return False
        signature = request.META.get("HTTP_X_MOYASAR_SIGNATURE", "")
        if not signature.startswith("sha256="):
            return False
        provided = signature.split("=", 1)[1].strip()
        body = request.body or b""
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(provided, expected)

    def parse_webhook(self, request) -> WebhookEvent:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookVerificationError(f"Invalid webhook body: {exc}") from exc
        data = payload.get("data") or payload
        provider_status = (data.get("status") or "").lower()
        # Hosted-invoice flow: we store the INVOICE id as provider_payment_id.
        # A webhook may arrive as the invoice object (``id`` == invoice id) or
        # as a payment object that references its invoice via ``invoice_id`` —
        # match on invoice_id first so both shapes resolve to our transaction.
        provider_payment_id = str(data.get("invoice_id") or data.get("id") or "")
        return WebhookEvent(
            provider=self.PROVIDER,
            provider_payment_id=provider_payment_id,
            status=self.map_provider_status(provider_status),
            amount=self._from_smallest_unit(data.get("amount")),
            currency=data.get("currency"),
            raw_payload=payload,
        )

    @staticmethod
    def _from_smallest_unit(amount) -> Optional[Decimal]:
        if amount is None:
            return None
        try:
            return (Decimal(amount) / Decimal(100)).quantize(Decimal("0.01"))
        except Exception:
            return None

    # ------------------------------------------------------------ refund

    def refund_payment(self, transaction, amount: Optional[Decimal] = None) -> GatewayResponse:
        body = {}
        if amount is not None:
            body["amount"] = self._to_smallest_unit(amount)
        try:
            r = http_post(
                f"{self.base_url}/payments/{transaction.provider_payment_id}/refund",
                json=body, auth=self._auth(), timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GatewayError(f"Moyasar refund failed: {exc}") from exc
        if r.status_code >= 400:
            raise GatewayError(
                f"Moyasar refund HTTP {r.status_code}: {r.text[:300]}"
            )
        return self._gateway_response(r.json())

    # ---------------------------------------------------------- shaping

    def _gateway_response(self, data: dict) -> GatewayResponse:
        source = data.get("source") or {}
        return GatewayResponse(
            provider=self.PROVIDER,
            provider_payment_id=str(data.get("id") or ""),
            provider_reference=str(data.get("reference") or data.get("invoice_id") or ""),
            checkout_url=source.get("transaction_url") or data.get("url") or "",
            status=self.map_provider_status((data.get("status") or "").lower()),
            raw_response=data,
        )
