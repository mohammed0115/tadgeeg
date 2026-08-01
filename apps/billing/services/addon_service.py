"""Buying add-ons, and what happens to them at renewal.

§I defines three billing types and says plainly they must not be treated as
one. The consequence lives here: :meth:`AddonService.renew_for_cycle` keeps
recurring add-ons and drops one-time ones, driven by the stored
``billing_type`` rather than by a caller remembering which is which.

Prices and quantities are frozen at purchase for the same reason D1 freezes the
subscription price: a catalogue edit must not change what an existing customer
pays or how much allowance they hold.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.billing.choices import AddonBillingType, AddonDimension
from apps.billing.models import Addon, SubscriptionAddon


class AddonError(Exception):
    """Raised when an add-on cannot be attached to a subscription."""


class AddonService:
    """Purchase and lifecycle for add-ons."""

    @transaction.atomic
    def purchase(
        self, subscription, addon: Addon, *, negotiated_price=None,
    ) -> SubscriptionAddon:
        """Attach an add-on to a subscription, freezing price and quantity.

        Custom-quote add-ons and "starts from" services are refused unless an
        agreed amount is supplied — a floor under a negotiation is not a price
        anyone can pay from a page.
        """
        if not addon.is_active:
            raise AddonError(f"Add-on {addon.code} is not active.")

        price = addon.price
        if not addon.is_purchasable:
            if negotiated_price is None:
                reason = (
                    "is priced by quotation"
                    if addon.billing_type == AddonBillingType.CUSTOM_QUOTE
                    else "has a starting price that must be negotiated"
                )
                raise AddonError(
                    f"Add-on {addon.code} {reason} and cannot be purchased "
                    f"through self-service."
                )
            price = Decimal(str(negotiated_price))
            if price <= 0:
                raise AddonError("A negotiated price must be greater than zero.")
        elif negotiated_price is not None:
            raise AddonError(
                f"Add-on {addon.code} has a list price; a negotiated amount "
                f"cannot override it."
            )

        return SubscriptionAddon.objects.create(
            subscription=subscription,
            addon=addon,
            # Type and dimension are copied, not looked up later: they decide
            # renewal and which ceiling moves, and both must survive a
            # catalogue edit exactly as the price does.
            billing_type=addon.billing_type,
            dimension=addon.dimension,
            quantity_at_purchase=addon.quantity,
            price_at_purchase=price,
            currency_at_purchase=(addon.currency or "SAR").upper(),
            is_active=True,
            starts_at=timezone.now(),
        )

    @transaction.atomic
    def renew_for_cycle(self, subscription, *, carry_over_credit: bool = True) -> dict:
        """Roll add-ons into the next billing cycle.

        The distinction §I insists on, made operational:

        * **recurring** — stays active and is charged again.
        * **one-time** — never renews. Whether its *unused credit* survives is
          a separate question answered by the rollover policy, and the two must
          not be confused: the add-on does not renew either way.

        ``carry_over_credit`` is passed in rather than read here so this method
        has no opinion on policy; the caller owns that decision.
        """
        recurring = list(
            subscription.addons.filter(
                is_active=True, billing_type=AddonBillingType.RECURRING,
            )
        )
        one_time = list(
            subscription.addons.filter(
                is_active=True, billing_type=AddonBillingType.ONE_TIME,
            )
        )

        expired, carried = 0, 0
        for sa in one_time:
            if carry_over_credit and sa.remaining_units > 0:
                # Untouched: unconsumed credit was paid for and stays. It is
                # still not "renewed" — nothing is charged again.
                carried += 1
                continue
            # Either the policy expires unused credit, or there is none left.
            sa.is_active = False
            sa.ends_at = timezone.now()
            sa.save(update_fields=["is_active", "ends_at", "updated_at"])
            expired += 1

        return {
            "renewed": len(recurring),
            "carried_over": carried,
            "expired": expired,
        }

    @transaction.atomic
    def lapse(self, subscription_addon: SubscriptionAddon) -> SubscriptionAddon:
        """End an add-on now; the effective ceiling drops on the next read."""
        subscription_addon.is_active = False
        subscription_addon.ends_at = timezone.now()
        subscription_addon.save(update_fields=["is_active", "ends_at", "updated_at"])
        return subscription_addon

    def purchasable(self, *, dimension: Optional[str] = None):
        """Add-ons a customer can buy without talking to sales."""
        qs = Addon.objects.filter(is_active=True).exclude(
            billing_type=AddonBillingType.CUSTOM_QUOTE,
        ).exclude(price__isnull=True).exclude(is_price_from=True)
        if dimension is not None:
            qs = qs.filter(dimension=dimension)
        return qs.order_by("sort_order", "code")
