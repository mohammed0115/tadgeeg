"""Subscription lifecycle.

Stage 1 scope: create / activate / expire. Payment-integration glue
(``activate_after_payment``) is added in Stage 4 — it will read the
``payment_transaction`` UUID off the subscription and verify the linked
payment is actually PAID before flipping status.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.billing.choices import PlanCode, SubscriptionStatus, USABLE_STATUSES
from apps.billing.models import OrganizationSubscription, Plan


logger = logging.getLogger("billing.subscription")


class SubscriptionError(Exception):
    pass


class FreeTrialAlreadyUsed(SubscriptionError):
    """An organisation has already consumed its one-time free trial."""


class AlreadySubscribed(SubscriptionError):
    """The organisation already has an active/trialing subscription."""


class SubscriptionNotExtendable(SubscriptionError):
    """The subscription's current status (or missing end date) forbids extension."""


class SubscriptionService:
    """Stateless — instantiate freely."""

    # ---- creation paths ----

    def create_free_trial(self, organization) -> OrganizationSubscription:
        """One-time trial. Refuses if the org already used one."""
        if OrganizationSubscription.objects.filter(
            organization=organization,
            plan__is_trial=True,
        ).exists():
            raise FreeTrialAlreadyUsed(
                "This organization has already used its free trial."
            )

        try:
            plan = Plan.objects.get(code=PlanCode.FREE_TRIAL, is_active=True)
        except Plan.DoesNotExist as exc:
            raise SubscriptionError(
                "free_trial plan is not configured — run `manage.py seed_billing_plans`."
            ) from exc

        now = timezone.now()
        return OrganizationSubscription.objects.create(
            organization=organization,
            plan=plan,
            status=SubscriptionStatus.TRIALING,
            starts_at=now,
            ends_at=now + timedelta(days=plan.duration_days),
            invoice_limit=plan.invoice_limit,
            user_limit=plan.user_limit,
            price_at_purchase=plan.price,
            currency_at_purchase=(plan.currency or "SAR").upper(),
            used_invoices=0,
            reserved_invoices=0,
            auto_renew=False,
        )

    def create_pending_paid_subscription(
        self, organization, plan: Plan, *, negotiated_price=None,
    ) -> OrganizationSubscription:
        """For paid plans only — creates the row in PENDING_PAYMENT state.

        The caller is expected to immediately initiate payment and store
        the resulting ``PaymentTransaction.id`` on the returned row.
        ``activate_subscription`` (or Stage 4's ``activate_after_payment``)
        is the only path that flips this to ACTIVE.
        """
        if plan.is_free or plan.is_trial:
            raise SubscriptionError(
                f"Plan {plan.code} is free/trial — use create_free_trial instead."
            )
        # A custom-quote plan has no list price. Letting one through would
        # produce a payable subscription that `payments.pricing` cannot price:
        # `_subscription_resolver` does `Decimal(sub.plan.price)` on a NULL and
        # raises TypeError at payment time. Refuse in the domain layer so every
        # caller is covered, not just the self-service view.
        if plan.is_custom_quote or plan.price is None:
            # A custom-quote plan has no list price, so self-service still has
            # nothing to charge. It becomes sellable only when someone supplies
            # the negotiated amount, which is what unblocks Enterprise.
            if negotiated_price is None:
                raise SubscriptionError(
                    f"Plan {plan.code} is priced by quotation and cannot be "
                    f"purchased through self-service checkout."
                )
            negotiated_price = Decimal(str(negotiated_price))
            if negotiated_price <= 0:
                raise SubscriptionError(
                    "A negotiated price must be greater than zero."
                )
        elif negotiated_price is not None:
            # Refusing here keeps one amount per subscription. Allowing an
            # override on a listed plan would mean the catalogue price and the
            # charged price could disagree with nothing recording which won.
            raise SubscriptionError(
                f"Plan {plan.code} has a list price; a negotiated amount "
                f"cannot override it."
            )
        return OrganizationSubscription.objects.create(
            organization=organization,
            plan=plan,
            status=SubscriptionStatus.PENDING_PAYMENT,
            # Both limits are frozen at creation time. NULL = unlimited.
            invoice_limit=plan.invoice_limit,
            user_limit=plan.user_limit,
            # …and so is the price, so a later catalogue edit cannot change
            # what this customer is charged.
            price_at_purchase=(
                negotiated_price if negotiated_price is not None else plan.price
            ),
            currency_at_purchase=(plan.currency or "SAR").upper(),
            price_is_negotiated=negotiated_price is not None,
            used_invoices=0,
            reserved_invoices=0,
        )

    # ---- activation ----

    @transaction.atomic
    def activate_subscription(self, subscription: OrganizationSubscription) -> OrganizationSubscription:
        """Flip a PENDING_PAYMENT row to ACTIVE and start its clock.

        Idempotent: if the subscription is already ACTIVE we leave it
        alone so duplicate webhook deliveries don't extend the period.
        """
        locked = (
            OrganizationSubscription.objects
            .select_for_update()
            .get(pk=subscription.pk)
        )
        if locked.status == SubscriptionStatus.ACTIVE:
            return locked

        if locked.status not in (
            SubscriptionStatus.PENDING_PAYMENT,
            SubscriptionStatus.PAYMENT_FAILED,
        ):
            raise SubscriptionError(
                f"Cannot activate subscription in status {locked.status!r}"
            )

        plan = locked.plan
        now  = timezone.now()

        # One usable subscription per org — enforced at the APPLICATION level.
        # The partial UniqueConstraint (billing_one_usable_sub_per_org) only
        # works on Postgres/SQLite; MySQL (our deploy DB) silently ignores the
        # condition, so it cannot be relied on. Before flipping this row to
        # ACTIVE, supersede any OTHER usable (active/trialing) subscription for
        # the same org — covers re-purchase (renewal: fresh period replaces the
        # old one) and plan change (upgrade/downgrade). Idempotent: a duplicate
        # webhook/callback returns early above, so this runs at most once.
        superseded = (
            OrganizationSubscription.objects
            .select_for_update()
            .filter(
                organization_id=locked.organization_id,
                status__in=tuple(USABLE_STATUSES),
            )
            .exclude(pk=locked.pk)
        )
        for old in superseded:
            old.status = SubscriptionStatus.CANCELED
            old.save(update_fields=["status", "updated_at"])

        locked.status            = SubscriptionStatus.ACTIVE
        locked.starts_at         = now
        locked.ends_at           = now + timedelta(days=plan.duration_days)
        locked.invoice_limit     = plan.invoice_limit
        locked.user_limit        = plan.user_limit
        # Price is deliberately NOT re-read from the plan here. Limits are
        # re-snapshotted at activation because the customer receives the
        # current allowance, but the amount was agreed when the subscription
        # was created — re-reading it would let a catalogue edit between
        # creation and payment change what is charged, which is the defect
        # this whole change exists to close. Only fill it if it is missing.
        if locked.price_at_purchase is None and not locked.price_is_negotiated:
            locked.price_at_purchase = plan.price
            locked.currency_at_purchase = (plan.currency or "SAR").upper()
        locked.used_invoices     = 0
        locked.reserved_invoices = 0
        locked.save(update_fields=[
            "status", "starts_at", "ends_at",
            "invoice_limit", "user_limit", "used_invoices", "reserved_invoices",
            "price_at_purchase", "currency_at_purchase",
            "updated_at",
        ])

        # Mutate the caller's reference too.
        subscription.refresh_from_db()
        return locked

    def mark_payment_failed(self, subscription: OrganizationSubscription) -> OrganizationSubscription:
        if subscription.status == SubscriptionStatus.ACTIVE:
            # Don't demote a confirmed-active subscription on a stray fail event.
            return subscription
        subscription.status = SubscriptionStatus.PAYMENT_FAILED
        subscription.save(update_fields=["status", "updated_at"])
        return subscription

    # ---- payment-driven activation ----

    def activate_after_payment(self, payment_transaction):
        """Activate the subscription linked to a PAID payment transaction.

        Validates the payment is for a subscription (purpose +
        reference_type + paid status) and delegates to
        ``activate_subscription`` which is idempotent — so a duplicate
        webhook delivery cannot activate twice or extend the period.

        Returns the activated subscription, or None if the payment was
        not for a subscription (so the caller doesn't have to filter)."""
        from apps.payments.choices import PaymentStatus

        if payment_transaction.purpose != "subscription":
            return None
        if payment_transaction.reference_type != "organization_subscription":
            return None
        if payment_transaction.status != PaymentStatus.PAID:
            raise SubscriptionError(
                f"Cannot activate from non-paid payment "
                f"(status={payment_transaction.status!r})"
            )

        try:
            sub = OrganizationSubscription.objects.get(
                pk=payment_transaction.reference_id,
                organization=payment_transaction.organization,
            )
        except (OrganizationSubscription.DoesNotExist, ValueError) as exc:
            raise SubscriptionError(
                f"Subscription {payment_transaction.reference_id} not found"
            ) from exc

        # Stamp the linkage from sub → payment for forensic queries.
        if sub.payment_transaction_id != payment_transaction.id:
            sub.payment_transaction = payment_transaction
            sub.save(update_fields=["payment_transaction", "updated_at"])

        return self.activate_subscription(sub)

    def mark_payment_failed_from_transaction(self, payment_transaction):
        """Mirror for the failure path. Returns the subscription so the
        caller can surface the error to the user. None if the payment is
        not for a subscription."""
        if payment_transaction.purpose != "subscription":
            return None
        if payment_transaction.reference_type != "organization_subscription":
            return None
        try:
            sub = OrganizationSubscription.objects.get(
                pk=payment_transaction.reference_id,
                organization=payment_transaction.organization,
            )
        except (OrganizationSubscription.DoesNotExist, ValueError):
            return None
        return self.mark_payment_failed(sub)

    # ---- lifecycle batch jobs ----

    def expire_old_subscriptions(self) -> int:
        """Flip everything whose ends_at < now to EXPIRED.

        Run from Celery beat or a management command. Returns the count
        of affected rows."""
        now = timezone.now()
        qs = OrganizationSubscription.objects.filter(
            status__in=(SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING),
            ends_at__lt=now,
        )
        count = qs.update(status=SubscriptionStatus.EXPIRED)
        if count:
            logger.info("Expired %d subscriptions whose ends_at < %s", count, now)
        return count

    # ---- operations ----

    @transaction.atomic
    def extend_subscription(
        self,
        subscription: OrganizationSubscription,
        *,
        days: int,
        reason: Optional[str] = None,
        actor=None,
    ) -> OrganizationSubscription:
        """Push a usable subscription's ``ends_at`` forward by ``days``.

        Official billing operation (NOT a CRM wrapper). It ONLY moves
        ``ends_at`` forward — it does not touch plan, quota counters,
        ``invoice_limit``, ``starts_at``, ``status`` or ``payment_transaction``,
        emits no payment signals, and creates no PaymentTransaction.

        Rules:
          * ``days`` must be a positive ``int`` (bools rejected).
          * Only usable subscriptions (TRIALING/ACTIVE) can be extended;
            EXPIRED/CANCELED/PAYMENT_FAILED/PENDING_PAYMENT are refused.
          * A usable subscription with no ``ends_at`` is a data anomaly and is
            refused rather than silently anchored to "now" (safest choice).

        ``reason``/``actor`` are accepted for traceability and are logged here,
        but the formal AuditLog + CustomerActivity are written by the CRM
        wrapper (CRM-1F-1B), not by this billing service.

        Returns the locked, updated subscription. Raises ``ValidationError``
        for a bad ``days`` value and ``SubscriptionNotExtendable`` for an
        invalid status / missing end date.
        """
        if isinstance(days, bool) or not isinstance(days, int):
            raise ValidationError("days must be a positive integer.")
        if days <= 0:
            raise ValidationError("days must be a positive integer.")

        locked = (
            OrganizationSubscription.objects
            .select_for_update()
            .get(pk=subscription.pk)
        )

        if locked.status not in USABLE_STATUSES:
            raise SubscriptionNotExtendable(
                f"Cannot extend subscription in status {locked.status!r}; "
                f"only {sorted(USABLE_STATUSES)} are extendable."
            )
        if locked.ends_at is None:
            raise SubscriptionNotExtendable(
                "Cannot extend a usable subscription that has no end date."
            )

        locked.ends_at = locked.ends_at + timedelta(days=days)
        locked.save(update_fields=["ends_at", "updated_at"])

        logger.info(
            "Extended subscription %s by %d days (new ends_at=%s, reason=%r, actor=%s)",
            locked.pk, days, locked.ends_at, reason, getattr(actor, "pk", None),
        )

        # Keep the caller's reference consistent with the persisted row.
        subscription.refresh_from_db()
        return locked
