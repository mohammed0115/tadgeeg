"""Gateway abstraction.

Every adapter returns a ``GatewayResponse`` dataclass with the same five
fields regardless of which provider is behind it. This is the contract
``PaymentService`` and ``WebhookService`` rely on — they never import
provider-specific code.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Any, Mapping, Optional

from apps.payments.choices import PaymentStatus


@dataclass
class GatewayResponse:
    """Unified response shape every gateway adapter must return."""
    provider:            str
    provider_payment_id: str
    provider_reference:  str
    checkout_url:        str
    status:              str  # one of PaymentStatus values
    raw_response:        dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class WebhookEvent:
    """Parsed webhook payload normalised across providers."""
    provider:            str
    provider_payment_id: str
    status:              str  # internal PaymentStatus
    amount:              Optional[Decimal] = None
    currency:            Optional[str] = None
    raw_payload:         dict = field(default_factory=dict)


class GatewayError(Exception):
    """Raised when a gateway cannot complete the requested operation.

    Adapters should use this for both transport failures (timeouts, 5xx)
    and protocol errors (declined transactions). Callers translate this
    into a 502/422 at the API layer."""


class WebhookVerificationError(GatewayError):
    """Raised when a webhook signature/hash fails verification."""


class BasePaymentGateway:
    """Abstract gateway. Subclasses implement provider-specific behaviour."""

    #: Lowercase provider id matching ``PaymentProvider``.
    PROVIDER: str = ""

    # ------------------------------------------------------------------ API

    def create_payment(self, transaction) -> GatewayResponse:
        raise NotImplementedError

    def retrieve_payment(self, provider_payment_id: str) -> GatewayResponse:
        raise NotImplementedError

    def verify_webhook(self, request) -> bool:
        """Return True iff the request's signature/hash is valid.

        Adapters that cannot verify cryptographically (no signing secret
        exposed by the provider) should at minimum match a shared-secret
        header and document the limitation in the adapter docstring.
        """
        raise NotImplementedError

    def parse_webhook(self, request) -> WebhookEvent:
        """Parse the request body into a ``WebhookEvent``.

        Must be safe to call BEFORE ``verify_webhook`` — adapters may want
        to look up the transaction to derive a verification secret."""
        raise NotImplementedError

    def refund_payment(self, transaction, amount: Optional[Decimal] = None) -> GatewayResponse:
        raise NotImplementedError

    # ----------------------------------------------------------- helpers

    def map_provider_status(self, provider_status: str) -> str:
        """Map a provider-native status string to our internal ``PaymentStatus``."""
        raise NotImplementedError
