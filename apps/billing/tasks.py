"""Celery tasks for the billing app.

Currently just the periodic ``expire_subscriptions`` job. The
implementation lives in
``apps.billing.services.subscription_service.SubscriptionService``;
this module is a thin Celery wrapper so beat can call it by name.
"""
from __future__ import annotations

import logging

from celery import shared_task

from apps.billing.services.subscription_service import SubscriptionService


logger = logging.getLogger("billing.tasks")


@shared_task(name="billing.expire_subscriptions")
def expire_subscriptions() -> int:
    """Periodic job that flips past-due active/trialing rows to EXPIRED.

    Returns the count of affected rows so beat logs are searchable.
    Idempotent — already-expired rows are excluded by the underlying
    query, so safe to schedule frequently.
    """
    count = SubscriptionService().expire_old_subscriptions()
    if count:
        logger.info("Periodic expire_subscriptions: flipped %d row(s).", count)
    return count
