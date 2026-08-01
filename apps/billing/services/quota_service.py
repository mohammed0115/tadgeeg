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

        # Unlimited bypasses the comparison entirely rather than being compared
        # against a sentinel big number: remaining_invoices returns None for an
        # unlimited plan, and `None < quantity` would raise.
        if sub.is_unlimited_invoices:
            return {"allowed": True, "reason": "", "remaining": None, "subscription": sub}

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

        # Unlimited (invoice_limit IS NULL) skips the check. Guarded here as
        # well as in can_audit because this is the row-locked write path and is
        # reachable directly — an unlimited plan must not fall into arithmetic
        # on None.
        if locked.invoice_limit is not None:
            remaining = max(
                0, locked.invoice_limit - locked.used_invoices - locked.reserved_invoices
            )
            if remaining < quantity:
                raise QuotaExceeded(
                    f"Not enough invoice quota: requested {quantity}, remaining {remaining}."
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
        quantity: int = 1, reason: str = "", allow_rebill: bool = False,
    ) -> UsageLedger:
        """Flip a prior reservation into consumption.

        Idempotency:
          • Default (``allow_rebill=False``): if a CONSUME row already
            exists for this document, no-op and return it. This is the
            "signal + view + celery retry" safety net.
          • ``allow_rebill=True``: bypass the document-key check and
            create a fresh consume keyed on (document, audit_run). Used
            by the quota gate when ``force_rerun_confirmed=True`` so
            an explicitly-confirmed re-audit actually re-bills.

        In both modes, an existing CONSUME with the SAME audit_run_id
        is treated as a duplicate and short-circuited — so a celery
        retry of the same audit_run is still safe.
        """
        if quantity <= 0:
            raise QuotaError("quantity must be > 0")

        if document is not None:
            # Same-audit_run dedup always wins (celery-retry safety),
            # regardless of allow_rebill.
            if audit_run is not None:
                same_run = UsageLedger.objects.filter(
                    organization=organization,
                    document=document,
                    audit_run=audit_run,
                    action=UsageAction.CONSUME,
                ).order_by("-created_at").first()
                if same_run is not None:
                    return same_run

            # Document-key dedup only fires when re-billing is NOT allowed.
            if not allow_rebill:
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


# ─── Seat (user) limit enforcement — Phase 3A, spec §H ───────────────────────

class SeatLimitExceeded(QuotaError):
    """Adding another user would exceed the plan's seat allowance."""


class SeatService:
    """Enforcement for the ``user_limit`` dimension.

    Deliberately shaped like QuotaService rather than as a second mechanism:
    same "read the active subscription, compare against the snapshotted limit,
    refuse server-side" flow. The difference is that seats are a *live count*
    of the organisation's users, not a consumed-and-ledgered allowance — there
    is nothing to reserve or release, so no UsageLedger rows are written.

    Counting is done in SQL (``.count()``), never by materialising users.
    """

    def _active_subscription(self, organization):
        return QuotaService().get_active_subscription(organization)

    def seat_limit(self, organization):
        """The organisation's seat allowance, or None for unlimited.

        None is also returned when there is no active subscription: seat
        enforcement is not the right place to block an unsubscribed org — that
        is SubscriptionRequiredMiddleware's job, and duplicating it here would
        produce two different errors for the same condition.
        """
        sub = self._active_subscription(organization)
        if sub is None:
            return None
        return sub.user_limit

    def seats_used(self, organization) -> int:
        """Active users in the organisation, counted in the database."""
        from apps.authentication.models import User

        return User.objects.filter(organization=organization, is_active=True).count()

    def can_add_user(self, organization, quantity: int = 1) -> dict:
        """Structured decision. Never raises — mirrors QuotaService.can_audit."""
        if quantity <= 0:
            return {"allowed": False, "reason": "Quantity must be > 0",
                    "limit": None, "used": 0, "remaining": 0}

        limit = self.seat_limit(organization)
        used = self.seats_used(organization)

        if limit is None:
            # Unlimited (or no subscription — see seat_limit).
            return {"allowed": True, "reason": "", "limit": None,
                    "used": used, "remaining": None}

        remaining = max(0, limit - used)
        if remaining < quantity:
            return {"allowed": False, "reason": "seat_limit_exceeded",
                    "limit": limit, "used": used, "remaining": remaining}
        return {"allowed": True, "reason": "", "limit": limit,
                "used": used, "remaining": remaining}

    def assert_can_add_user(self, organization, quantity: int = 1):
        """Raise ``SeatLimitExceeded`` when the seat allowance is exhausted.

        The message names WHICH limit was hit — a caller staring at a bare
        "limit exceeded" cannot tell seats from invoices.
        """
        decision = self.can_add_user(organization, quantity)
        if not decision["allowed"]:
            if decision["reason"] == "seat_limit_exceeded":
                raise SeatLimitExceeded(
                    f"User limit reached: this plan allows {decision['limit']} "
                    f"user(s) and {decision['used']} are already active. "
                    f"Upgrade the plan to add more."
                )
            raise QuotaError(decision["reason"])
        return decision
