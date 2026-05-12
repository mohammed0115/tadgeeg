"""Quota service.

The single entry point any caller (audit pipeline, bulk upload, API)
must go through before consuming a unit of invoice-audit quota. Three
states per audit:

    reserve  → counter goes up, no consumption yet (audit starting)
    consume  → reservation becomes a real consumption (audit succeeded)
    release  → reservation released, no consumption (audit failed by
               system error or was cancelled)

Race-safety: ``reserve``, ``consume``, and ``release`` all run inside
``transaction.atomic`` with ``select_for_update`` on the subscription
row. Two concurrent requests competing for the last available unit
will be serialised by Postgres' row lock — only one can succeed.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.billing.choices import (
    SubscriptionStatus,
    USABLE_STATUSES,
    UsageAction,
)
from apps.billing.models import OrganizationSubscription, UsageLedger


logger = logging.getLogger("billing.quota")


class QuotaError(Exception):
    """Base — caller surfaces ``str(exc)`` to the user."""


class NoActiveSubscription(QuotaError):
    pass


class SubscriptionExpired(QuotaError):
    pass


class QuotaExceeded(QuotaError):
    pass


class QuotaService:
    """Stateless. Instantiate freely or call as instance methods on
    a singleton — there is no per-instance state."""

    # ---- reads ----

    def get_active_subscription(self, organization) -> Optional[OrganizationSubscription]:
        """Return the org's usable subscription or None.

        "Usable" = status in {trialing, active} AND now is inside
        [starts_at, ends_at]. We deliberately don't auto-expire here —
        a separate job/command flips status to EXPIRED.
        """
        now = timezone.now()
        return (
            OrganizationSubscription.objects
            .select_related("plan")
            .filter(
                organization=organization,
                status__in=tuple(USABLE_STATUSES),
                starts_at__lte=now,
                ends_at__gte=now,
            )
            .order_by("-created_at")
            .first()
        )

    def get_remaining_quota(self, organization) -> int:
        sub = self.get_active_subscription(organization)
        return sub.remaining_invoices if sub else 0

    def can_audit(self, organization, quantity: int = 1) -> dict:
        """Return a structured decision dict. Never raises — callers can
        branch on ``allowed`` instead of catch/finally."""
        if quantity <= 0:
            return {"allowed": False, "reason": "Quantity must be > 0",
                    "remaining": 0, "subscription": None}

        sub = self.get_active_subscription(organization)
        if sub is None:
            # Distinguish "never had one" vs "had one and it expired".
            has_history = OrganizationSubscription.objects.filter(
                organization=organization,
            ).exists()
            reason = (
                "subscription_expired" if has_history else "no_subscription"
            )
            return {"allowed": False, "reason": reason,
                    "remaining": 0, "subscription": None}

        remaining = sub.remaining_invoices
        if remaining < quantity:
            return {"allowed": False, "reason": "quota_exceeded",
                    "remaining": remaining, "subscription": sub}
        return {"allowed": True, "reason": "",
                "remaining": remaining, "subscription": sub}

    # ---- writes ----

    @transaction.atomic
    def reserve_invoice_audit(
        self, organization, *, document=None, quantity: int = 1,
        reason: str = "",
    ) -> UsageLedger:
        """Pre-allocate ``quantity`` units of quota under a row lock.

        Idempotency rule (Stage 5 enforces it on the pipeline side too):
        if a non-consumed ``reserve`` ledger entry already exists for
        the same document, return it instead of creating a duplicate.
        """
        if quantity <= 0:
            raise QuotaError("quantity must be > 0")

        sub = self.get_active_subscription(organization)
        if sub is None:
            raise NoActiveSubscription("No active subscription for this organization.")

        # Idempotency: skip if there's already a reserve for this document
        # that hasn't been consumed or released.
        if document is not None:
            already = UsageLedger.objects.filter(
                organization=organization,
                document=document,
                action=UsageAction.RESERVE,
            ).exists()
            consumed_or_released = UsageLedger.objects.filter(
                organization=organization,
                document=document,
                action__in=(UsageAction.CONSUME, UsageAction.RELEASE),
            ).exists()
            if already and not consumed_or_released:
                return (
                    UsageLedger.objects
                    .filter(organization=organization, document=document,
                            action=UsageAction.RESERVE)
                    .order_by("-created_at")
                    .first()
                )

        locked = (
            OrganizationSubscription.objects
            .select_for_update()
            .get(pk=sub.pk)
        )

        remaining = max(0, locked.invoice_limit - locked.used_invoices - locked.reserved_invoices)
        if remaining < quantity:
            raise QuotaExceeded(
                f"Not enough quota: requested {quantity}, remaining {remaining}."
            )

        locked.reserved_invoices += quantity
        locked.save(update_fields=["reserved_invoices", "updated_at"])

        return UsageLedger.objects.create(
            organization=organization,
            subscription=locked,
            document=document,
            action=UsageAction.RESERVE,
            quantity=quantity,
            reason=reason,
        )

    @transaction.atomic
    def consume_invoice_audit(
        self, organization, *, document=None, audit_run=None,
        quantity: int = 1, reason: str = "",
    ) -> UsageLedger:
        """Flip a prior reservation into consumption. Idempotent: if a
        ``consume`` already exists for this document we no-op and
        return the existing row."""
        if quantity <= 0:
            raise QuotaError("quantity must be > 0")

        if document is not None:
            existing = UsageLedger.objects.filter(
                organization=organization,
                document=document,
                action=UsageAction.CONSUME,
            ).order_by("-created_at").first()
            if existing is not None:
                return existing

        sub = self.get_active_subscription(organization)
        if sub is None:
            raise NoActiveSubscription(
                "Cannot consume — no active subscription. "
                "Did the subscription expire mid-audit?"
            )

        locked = (
            OrganizationSubscription.objects
            .select_for_update()
            .get(pk=sub.pk)
        )

        # Decrement reserved (clamped at 0 so a stray double-consume
        # doesn't underflow the unsigned column), increment used.
        locked.reserved_invoices = max(0, locked.reserved_invoices - quantity)
        locked.used_invoices    += quantity
        locked.save(update_fields=["reserved_invoices", "used_invoices", "updated_at"])

        return UsageLedger.objects.create(
            organization=organization,
            subscription=locked,
            document=document,
            audit_run=audit_run,
            action=UsageAction.CONSUME,
            quantity=quantity,
            reason=reason,
        )

    @transaction.atomic
    def release_invoice_audit(
        self, organization, *, document=None, quantity: int = 1,
        reason: str = "",
    ) -> UsageLedger:
        """Release a prior reservation without consuming. Idempotent on
        document — already-released reservations are not double-released."""
        if quantity <= 0:
            raise QuotaError("quantity must be > 0")

        if document is not None:
            already_released = UsageLedger.objects.filter(
                organization=organization,
                document=document,
                action=UsageAction.RELEASE,
            ).exists()
            already_consumed = UsageLedger.objects.filter(
                organization=organization,
                document=document,
                action=UsageAction.CONSUME,
            ).exists()
            if already_released or already_consumed:
                # No-op: nothing to release.
                return (
                    UsageLedger.objects
                    .filter(organization=organization, document=document,
                            action__in=(UsageAction.RELEASE, UsageAction.CONSUME))
                    .order_by("-created_at")
                    .first()
                )

        sub = self.get_active_subscription(organization)
        if sub is None:
            raise NoActiveSubscription("Cannot release — no active subscription.")

        locked = (
            OrganizationSubscription.objects
            .select_for_update()
            .get(pk=sub.pk)
        )
        locked.reserved_invoices = max(0, locked.reserved_invoices - quantity)
        locked.save(update_fields=["reserved_invoices", "updated_at"])

        return UsageLedger.objects.create(
            organization=organization,
            subscription=locked,
            document=document,
            action=UsageAction.RELEASE,
            quantity=quantity,
            reason=reason,
        )
