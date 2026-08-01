"""Effective quota — the single place plan quota and add-on quota compose.

§I.5: ``effective quota = plan quota + active add-on quota``.

    Business             →  10 users · 2,000 invoices/mo
    + 10-user pack       →  +10 users (recurring)
    + 1,000-invoice pack →  +1,000 invoices (one-time)
    ─────────────────────────────────────────────────────
    effective            →  20 users · 3,000 invoices

Why one module rather than a helper on each service: ``QuotaService`` and
``SeatService`` both need the composed number, and two implementations of the
same sum is how the invoice ceiling and the seat ceiling start disagreeing
about what "active" means.

Two rules this module exists to keep:

1. **Unlimited plus anything is unlimited, and no arithmetic happens.** ``None``
   means unlimited; ``None + 500`` is a TypeError and ``int(None or 0) + 500``
   is the far worse silent answer of 500. Both are avoided by returning early.
2. **Only active add-ons count.** A lapsed recurring add-on must drop the
   ceiling on its own, so the query filters rather than the caller remembering.

Aggregation is done in SQL (``Sum``), not by materialising rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db.models import Q, Sum
from django.utils import timezone

from apps.billing.choices import AddonDimension


@dataclass(frozen=True)
class Entitlement:
    """A composed ceiling, and where it came from.

    The breakdown is not decoration: when a customer asks why they can only add
    three users, "plan 3 + add-ons 0" answers it and a bare "3" does not.
    """

    plan_limit: Optional[int]
    addon_units: int
    is_unlimited: bool

    @property
    def total(self) -> Optional[int]:
        """The effective ceiling. ``None`` means unlimited."""
        return None if self.is_unlimited else (self.plan_limit or 0) + self.addon_units


def _active_addon_units(subscription, dimension: str) -> int:
    """Sum of active add-on quantity for one dimension, aggregated in SQL.

    "Active" means flagged active and inside its window. An add-on with no
    ``ends_at`` never expires by time — one-time invoice credit is owned until
    consumed, subject to the rollover policy.
    """
    now = timezone.now()
    agg = (
        subscription.addons
        .filter(is_active=True, dimension=dimension)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
        .aggregate(total=Sum("quantity_at_purchase"))
    )
    return int(agg["total"] or 0)


def effective_invoice_quota(subscription) -> Entitlement:
    """Plan invoice allowance plus active invoice packs."""
    if subscription is None:
        return Entitlement(plan_limit=0, addon_units=0, is_unlimited=False)

    if subscription.invoice_limit is None:
        # Unlimited: return before any arithmetic touches a None.
        return Entitlement(plan_limit=None, addon_units=0, is_unlimited=True)

    return Entitlement(
        plan_limit=subscription.invoice_limit,
        addon_units=_active_addon_units(subscription, AddonDimension.INVOICES),
        is_unlimited=False,
    )


def effective_seat_quota(subscription) -> Entitlement:
    """Plan seat allowance plus active seat packs."""
    if subscription is None:
        # No subscription is not a seat decision — SubscriptionRequiredMiddleware
        # owns that, and answering here would give two different errors for one
        # condition. Unlimited is the non-answer.
        return Entitlement(plan_limit=None, addon_units=0, is_unlimited=True)

    if subscription.user_limit is None:
        return Entitlement(plan_limit=None, addon_units=0, is_unlimited=True)

    return Entitlement(
        plan_limit=subscription.user_limit,
        addon_units=_active_addon_units(subscription, AddonDimension.USERS),
        is_unlimited=False,
    )
