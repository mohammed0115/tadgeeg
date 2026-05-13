"""Subscription lifecycle.

Stage 1 scope: create / activate / expire. Payment-integration glue
(``activate_after_payment``) is added in Stage 4 — it will read the
``payment_transaction`` UUID off the subscription and verify the linked
payment is actually PAID before flipping status.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan


logger = logging.getLogger("billing.subscription")


class SubscriptionError(Exception):
    pass


class FreeTrialAlreadyUsed(SubscriptionError):
    """An organisation has already consumed its one-time free trial."""


class AlreadySubscribed(SubscriptionError):
    """The organisation already has an active/trialing subscription."""


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
            used_invoices=0,
            reserved_invoices=0,
            auto_renew=False,
        )

    def create_pending_paid_subscription(
        self, organization, plan: Plan,
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
        return OrganizationSubscription.objects.create(
            organization=organization,
            plan=plan,
            status=SubscriptionStatus.PENDING_PAYMENT,
            invoice_limit=plan.invoice_limit,  # frozen at creation time
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
        locked.status            = SubscriptionStatus.ACTIVE
        locked.starts_at         = now
        locked.ends_at           = now + timedelta(days=plan.duration_days)
        locked.invoice_limit     = plan.invoice_limit
        locked.used_invoices     = 0
        locked.reserved_invoices = 0
        locked.save(update_fields=[
            "status", "starts_at", "ends_at",
            "invoice_limit", "used_invoices", "reserved_invoices",
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
        if sub.payment_transaction != payment_transaction.id:
            sub.payment_transaction = payment_transaction.id
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
