"""Telr adapter.

Telr's primary integration is the ``/gateway/order.json`` endpoint which
creates an order and returns a hosted payment page URL. After payment,
the merchant queries ``order/status`` to confirm — return URLs alone are
NEVER trusted as proof of payment.

Docs: https://telr.com/support/knowledge-base/hosted-payment-page-integration/
Verification: Telr does NOT sign webhooks. Hosted-page integrations rely
on server-to-server status check via ``order/status`` keyed on the order
reference. ``verify_webhook`` therefore performs a live status check
against Telr instead of validating a signature.
"""
from __future__ import annotations

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


logger = logging.getLogger("payments.telr")

_DEFAULT_BASE_URL = "https://secure.telr.com"
_TIMEOUT = 20

_STATUS_MAP = {
    # Telr returns an integer status code in `order.status.code` —
    # we expose both names and numeric codes here.
    "0": PaymentStatus.PENDING,         # not paid
    "1": PaymentStatus.INITIATED,       # checked
    "2": PaymentStatus.PAID,            # authorised
    "3": PaymentStatus.PAID,            # paid
    "-1": PaymentStatus.CANCELED,
    "-2": PaymentStatus.FAILED,
    "-3": PaymentStatus.EXPIRED,
    "authorised": PaymentStatus.PAID,
    "paid":       PaymentStatus.PAID,
    "cancelled":  PaymentStatus.CANCELED,
    "declined":   PaymentStatus.FAILED,
    "expired":    PaymentStatus.EXPIRED,
}


class TelrGateway(BasePaymentGateway):
    PROVIDER = "telr"

    def __init__(self):
        self.store_id           = getattr(settings, "TELR_STORE_ID", "") or ""
        self.auth_key           = getattr(settings, "TELR_AUTH_KEY", "") or ""
        self.base_url           = (getattr(settings, "TELR_BASE_URL", "") or _DEFAULT_BASE_URL).rstrip("/")
        self.return_auth_url    = getattr(settings, "TELR_RETURN_AUTH_URL", "") or ""
        self.return_declined_url = getattr(settings, "TELR_RETURN_DECLINED_URL", "") or ""
        self.return_cancel_url  = getattr(settings, "TELR_RETURN_CANCELLED_URL", "") or ""
        self.test_mode          = (getattr(settings, "PAYMENT_MODE", "test") or "test").lower() != "live"

    def _require_credentials(self):
        if not self.store_id or not self.auth_key:
            raise GatewayError("TELR_STORE_ID / TELR_AUTH_KEY are not configured.")

    def map_provider_status(self, provider_status: str) -> str:
        return _STATUS_MAP.get(str(provider_status or "").lower(), PaymentStatus.PENDING)

    # ------------------------------------------------------------ create

    def create_payment(self, transaction) -> GatewayResponse:
        self._require_credentials()
        body = {
            "ivp_method":   "create",
            "ivp_store":    self.store_id,
            "ivp_authkey":  self.auth_key,
            "ivp_cart":     str(transaction.id),
            "ivp_test":     1 if self.test_mode else 0,
            "ivp_amount":   str(Decimal(transaction.amount).quantize(Decimal("0.01"))),
            "ivp_currency": transaction.currency or "SAR",
            "ivp_desc":     f"{transaction.purpose}:{transaction.id}",
            "return_auth":  transaction.success_url or self.return_auth_url,
            "return_can":   transaction.cancel_url  or self.return_cancel_url,
            "return_decl":  transaction.failure_url or self.return_declined_url,
        }
        try:
            r = http_post(
                f"{self.base_url}/gateway/order.json",
                json=body, timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GatewayError(f"Telr request failed: {exc}") from exc
        if r.status_code >= 400:
            raise GatewayError(
                f"Telr create_payment HTTP {r.status_code}: {r.text[:300]}"
            )
        data = r.json()
        # Telr returns errors inside the JSON body even on 200 OK.
        if "error" in data:
            err = data["error"]
            raise GatewayError(
                f"Telr error {err.get('code')}: {err.get('message') or err.get('note')}"
            )
        order = data.get("order") or {}
        return GatewayResponse(
            provider=self.PROVIDER,
            provider_payment_id=str(order.get("ref") or ""),
            provider_reference=str(order.get("cartid") or transaction.id),
            checkout_url=order.get("url") or "",
            status=PaymentStatus.REDIRECT_REQUIRED if order.get("url") else PaymentStatus.INITIATED,
            raw_response=data,
        )

    # ---------------------------------------------------------- retrieve

    def retrieve_payment(self, provider_payment_id: str) -> GatewayResponse:
        self._require_credentials()
        body = {
            "ivp_method":  "check",
            "ivp_store":   self.store_id,
            "ivp_authkey": self.auth_key,
            "order_ref":   provider_payment_id,
        }
        try:
            r = http_post(
                f"{self.base_url}/gateway/order.json",
                json=body, timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GatewayError(f"Telr retrieve failed: {exc}") from exc
        if r.status_code >= 400:
            raise GatewayError(
                f"Telr retrieve_payment HTTP {r.status_code}: {r.text[:300]}"
            )
        data = r.json()
        order = data.get("order") or {}
        status = (order.get("status") or {})
        return GatewayResponse(
            provider=self.PROVIDER,
            provider_payment_id=str(order.get("ref") or provider_payment_id),
            provider_reference=str(order.get("cartid") or ""),
            checkout_url=order.get("url") or "",
            status=self.map_provider_status(str(status.get("code") or status.get("text") or "")),
            raw_response=data,
        )

    # ------------------------------------------------------------ webhook

    def verify_webhook(self, request) -> bool:
        """Telr posts unsigned callbacks. Treat them as untrusted notifications:
        always re-query ``order/status`` server-to-server to confirm.

        This method returns True if (a) the body is parsable and (b) a
        subsequent ``retrieve_payment`` agrees with the posted status —
        otherwise False. ``WebhookService`` will then drive the actual
        state transition from the retrieve result, never from the body."""
        try:
            payload = json.loads((request.body or b"{}").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        ref = (payload.get("tran_ref") or payload.get("ref")
               or (payload.get("order") or {}).get("ref") or "")
        if not ref:
            return False
        try:
            self.retrieve_payment(str(ref))
        except GatewayError:
            return False
        return True

    def parse_webhook(self, request) -> WebhookEvent:
        try:
            payload = json.loads((request.body or b"{}").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookVerificationError(f"Invalid webhook body: {exc}") from exc
        order = payload.get("order") or payload
        ref = (order.get("ref") or payload.get("tran_ref") or payload.get("ref") or "")
        status = ((order.get("status") or {}).get("code")
                  or order.get("status_code") or order.get("status") or "")
        return WebhookEvent(
            provider=self.PROVIDER,
            provider_payment_id=str(ref),
            status=self.map_provider_status(str(status)),
            amount=_safe_decimal(order.get("amount")),
            currency=order.get("currency"),
            raw_payload=payload,
        )

    # ------------------------------------------------------------ refund

    def refund_payment(self, transaction, amount: Optional[Decimal] = None) -> GatewayResponse:
        # Telr refunds go through a separate auth-call; placeholder for now.
        raise GatewayError("Telr refunds require a remote-payment merchant role — implement when enabled.")


def _safe_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
