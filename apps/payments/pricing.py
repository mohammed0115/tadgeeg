"""Server-side price resolution.

Clients send ``amount`` in the payment request, but for billable
purposes that amount is treated as advisory — the authoritative price
comes from the referenced domain row. This prevents an attacker from
paying SAR 0.01 for a SAR 5,000 subscription by tampering with the JSON
body.

Adding a new purpose:
    1. Register the resolver with ``register_resolver(purpose, fn)``.
    2. Implementation should look up the referenced row, verify it
       belongs to ``organization``, and return ``(Decimal, currency)``.
    3. Strict-deny is the default: any purpose without a registered
       resolver and that is NOT in ``UNGUARDED_PURPOSES`` will be
       rejected by ``resolve_or_validate``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Optional, Tuple

from apps.payments.choices import PaymentPurpose


class PriceMismatchError(ValueError):
    """Raised when the requested amount disagrees with the authoritative price."""


class PriceResolutionError(ValueError):
    """Raised when we cannot determine an authoritative price."""


# A resolver returns (price, currency) or raises PriceResolutionError.
Resolver = Callable[[str, str, object], Tuple[Decimal, str]]
#                  ^reference_type ^reference_id ^organization

_REGISTRY: dict[str, Resolver] = {}

# Purposes where the client-supplied amount is genuinely the source of
# truth (wallet top-ups: user picks how much to load, no domain price).
UNGUARDED_PURPOSES = frozenset({
    PaymentPurpose.WALLET_TOPUP.value,
    PaymentPurpose.OTHER.value,
})


def register_resolver(purpose: str, fn: Resolver) -> None:
    _REGISTRY[purpose] = fn


def get_resolver(purpose: str) -> Optional[Resolver]:
    return _REGISTRY.get(purpose)


def resolve_or_validate(
    *, purpose: str, reference_type: str, reference_id: str,
    organization, requested_amount: Decimal,
) -> Tuple[Decimal, str | None]:
    """Return the authoritative ``(amount, currency)`` for the request.

    For guarded purposes:
      - The resolver MUST find a matching row scoped to ``organization``.
      - The requested amount MUST equal the authoritative one (rounded to
        2 decimals). Mismatch raises PriceMismatchError.

    For unguarded purposes (wallet top-up / other):
      - Returns the requested amount as-is.
    """
    if purpose in UNGUARDED_PURPOSES:
        return Decimal(requested_amount).quantize(Decimal("0.01")), None

    resolver = _REGISTRY.get(purpose)
    if resolver is None:
        raise PriceResolutionError(
            f"No server-side price resolver registered for purpose={purpose!r}. "
            "Register one with apps.payments.pricing.register_resolver() before "
            "accepting payments for this purpose."
        )
    if not reference_id:
        raise PriceResolutionError(
            f"purpose={purpose!r} requires a reference_id to look up the price."
        )

    authoritative, currency = resolver(reference_type or "", str(reference_id), organization)
    authoritative = Decimal(authoritative).quantize(Decimal("0.01"))
    requested     = Decimal(requested_amount).quantize(Decimal("0.01"))
    if authoritative != requested:
        raise PriceMismatchError(
            f"Amount mismatch for {purpose}/{reference_id}: "
            f"requested {requested}, authoritative {authoritative}"
        )
    return authoritative, currency


# ─── Built-in resolvers ─────────────────────────────────────────────────────
def _invoice_resolver(reference_type: str, reference_id: str, organization) -> Tuple[Decimal, str]:
    """Resolve a tadgeeg domain Invoice (the audit-pipeline kind).

    NOTE: This codebase's Invoice model is the *audit* invoice. If you
    later add a separate BillingInvoice for SaaS billing, register that
    resolver here instead and the public API stays unchanged.
    """
    from apps.invoices.models import Invoice
    from django.core.exceptions import ValidationError
    try:
        inv = Invoice.objects.get(pk=reference_id, organization=organization)
    except (Invoice.DoesNotExist, ValueError, ValidationError):
        raise PriceResolutionError(
            f"Invoice {reference_id} not found in this organization."
        )
    return Decimal(inv.total_amount or 0), (inv.currency or "SAR").upper()


register_resolver(PaymentPurpose.INVOICE.value, _invoice_resolver)


def _subscription_resolver(reference_type: str, reference_id: str, organization) -> Tuple[Decimal, str]:
    """Resolve an OrganizationSubscription's plan price.

    Strict contract enforced by ``PaymentService.create_transaction``:
      reference_type = "organization_subscription"
      reference_id   = subscription.id
    """
    if reference_type and reference_type != "organization_subscription":
        raise PriceResolutionError(
            f"purpose=subscription expects reference_type='organization_subscription', "
            f"got {reference_type!r}"
        )
    from apps.billing.models import OrganizationSubscription
    from django.core.exceptions import ValidationError
    try:
        sub = OrganizationSubscription.objects.select_related("plan").get(
            pk=reference_id, organization=organization,
        )
    except (OrganizationSubscription.DoesNotExist, ValueError, ValidationError):
        raise PriceResolutionError(
            f"Subscription {reference_id} not found in this organization."
        )
    if sub.plan.price is None:
        # Custom-quote plan: no list price exists, so there is nothing
        # authoritative to charge. Refuse rather than let Decimal(None) raise
        # TypeError — this resolver is the server-side authority on amounts and
        # must fail as a priced-refusal, not as a crash. See ADR 0006.
        raise PriceResolutionError(
            f"Plan {sub.plan.code} is priced by quotation; no list price is "
            f"available to authorise this payment."
        )
    return Decimal(sub.plan.price), (sub.plan.currency or "SAR").upper()


register_resolver(PaymentPurpose.SUBSCRIPTION.value, _subscription_resolver)


# ── SERVICE_ORDER — intentionally unregistered (strict-deny) ────────────────
#
# There is no service-order domain in this codebase. Any payment request
# with ``purpose="service_order"`` will fail at ``resolve_or_validate``
# with ``PriceResolutionError`` because this branch never registered a
# resolver. That refusal surfaces as ``PaymentValidationError`` →
# HTTP 400 at the API.
#
# Operationally: if you see a 400 with "No server-side price resolver
# registered for purpose='service_order'" in the logs, your frontend
# is sending a purpose the backend doesn't yet support — NOT a quota
# issue. Register a resolver here when the service-order domain lands.
#
# Example:
#
#     def _service_order_resolver(reference_type, reference_id, organization):
#         from apps.service_orders.models import ServiceOrder
#         order = ServiceOrder.objects.get(pk=reference_id, organization=organization)
#         return Decimal(order.amount), order.currency
#     register_resolver(PaymentPurpose.SERVICE_ORDER.value, _service_order_resolver)
