"""Billing receivers.

Listen to payments-domain signals and drive subscription lifecycle.

These handlers are the entire "Payment → Subscription Activation"
wiring — Stage 4. They are intentionally thin: all the real work
(idempotency, snapshotting, select_for_update) lives in
SubscriptionService.
"""
from __future__ import annotations

import logging

from django.dispatch import receiver

from apps.billing.services.subscription_service import (
    SubscriptionError,
    SubscriptionService,
)
from apps.payments.signals import payment_failed, subscription_paid


logger = logging.getLogger("billing.receivers")


@receiver(subscription_paid)
def activate_subscription_after_payment(sender, transaction, payload, **kwargs):
    """Webhook PAID for a purpose=subscription payment → activate the sub."""
    try:
        SubscriptionService().activate_after_payment(transaction)
    except SubscriptionError:
        logger.exception(
            "Could not activate subscription after payment %s", transaction.pk,
        )
        raise


@receiver(payment_failed)
def fail_subscription_on_payment_failure(sender, transaction, reason="", payload=None, **kwargs):
    """Payment for a subscription failed → flip OrganizationSubscription
    to PAYMENT_FAILED so the UI can surface a retry prompt."""
    try:
        SubscriptionService().mark_payment_failed_from_transaction(transaction)
    except Exception:  # pragma: no cover
        logger.exception(
            "Could not mark subscription payment_failed for txn %s", transaction.pk,
        )
