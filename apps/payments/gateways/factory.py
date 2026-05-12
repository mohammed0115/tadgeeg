"""Gateway selection.

The active provider is read from ``settings.PAYMENT_PROVIDER`` only —
NEVER from a request, form input, or query param. This is a hard rule:
allowing the caller to choose their gateway would defeat the purpose of
funnelling secrets / signing / merchant accounts through a single
configured backend.
"""
from __future__ import annotations

from typing import Type

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.payments.choices import PaymentProvider
from apps.payments.gateways.base import BasePaymentGateway


SUPPORTED_PROVIDERS = frozenset({
    PaymentProvider.MOYASAR.value,
    PaymentProvider.TAP.value,
    PaymentProvider.TELR.value,
})


def _provider_class(provider: str) -> Type[BasePaymentGateway]:
    if provider == PaymentProvider.MOYASAR.value:
        from apps.payments.gateways.moyasar import MoyasarGateway
        return MoyasarGateway
    if provider == PaymentProvider.TAP.value:
        from apps.payments.gateways.tap import TapGateway
        return TapGateway
    if provider == PaymentProvider.TELR.value:
        from apps.payments.gateways.telr import TelrGateway
        return TelrGateway
    raise ImproperlyConfigured(
        f"Unknown PAYMENT_PROVIDER {provider!r}. "
        f"Supported: {sorted(SUPPORTED_PROVIDERS)}"
    )


def get_payment_gateway(provider: str | None = None) -> BasePaymentGateway:
    """Return an instantiated gateway for the configured (or given) provider.

    ``provider`` is only meant for internal callers — webhook dispatch,
    background sync — that need to talk to a specific provider regardless
    of the system-wide setting. Public APIs MUST omit it.
    """
    active = (provider or getattr(settings, "PAYMENT_PROVIDER", "") or "").strip().lower()
    if not active:
        raise ImproperlyConfigured(
            "PAYMENT_PROVIDER is not configured. "
            f"Set one of {sorted(SUPPORTED_PROVIDERS)} in the environment."
        )
    if active not in SUPPORTED_PROVIDERS:
        raise ImproperlyConfigured(
            f"PAYMENT_PROVIDER={active!r} is not supported. "
            f"Allowed values: {sorted(SUPPORTED_PROVIDERS)}"
        )
    return _provider_class(active)()


def validate_configured_provider() -> None:
    """Boot-time check. Allows blank (deployments that disable payments)
    but rejects unknown values immediately so misconfigurations are
    caught at startup, not on first POST /create/."""
    active = (getattr(settings, "PAYMENT_PROVIDER", "") or "").strip().lower()
    if not active:
        return  # payments not enabled in this deployment
    if active not in SUPPORTED_PROVIDERS:
        raise ImproperlyConfigured(
            f"PAYMENT_PROVIDER={active!r} is not supported. "
            f"Allowed values: {sorted(SUPPORTED_PROVIDERS)}"
        )
