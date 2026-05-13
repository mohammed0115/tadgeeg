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


@shared_task(name="billing.detect_counter_drift")
def detect_counter_drift(*, auto_correct: bool = False) -> dict:
    """Nightly sanity check: compare ``used_invoices`` /
    ``reserved_invoices`` against the UsageLedger.

    Drift can creep in if someone hand-edits a counter via dbshell, a
    migration rewrites quota fields, or a fault during consume corrupts
    the row. The ledger is append-only and authoritative.

    Default mode logs every drifted subscription as a WARNING — useful
    for monitoring/alerting. ``auto_correct=True`` rewrites the counters
    from the ledger sum (same logic as the admin
    "recalculate_usage_from_ledger" action). Recommend running in
    log-only mode first to confirm the rate of drift is acceptable
    before flipping to auto-correct.

    Returns a summary dict with the number of subs checked, drifted,
    and corrected so beat logs are searchable.
    """
    from django.db.models import Sum
    from apps.billing.choices import (
        SubscriptionStatus,
        USABLE_STATUSES,
        UsageAction,
    )
    from apps.billing.models import OrganizationSubscription, UsageLedger

    qs = OrganizationSubscription.objects.filter(
        status__in=tuple(USABLE_STATUSES),
    )

    checked = drifted = corrected = 0
    for sub in qs.iterator(chunk_size=200):
        checked += 1
        agg = UsageLedger.objects.filter(
            organization_id=sub.organization_id, subscription=sub,
        ).values("action").annotate(total=Sum("quantity"))
        totals = {row["action"]: int(row["total"] or 0) for row in agg}
        consume = totals.get(UsageAction.CONSUME, 0)
        reserve = totals.get(UsageAction.RESERVE, 0)
        release = totals.get(UsageAction.RELEASE, 0)
        refund  = totals.get(UsageAction.REFUND,  0)

        expected_used     = max(0, consume - refund)
        expected_reserved = max(0, reserve - consume - release)

        if sub.used_invoices == expected_used and sub.reserved_invoices == expected_reserved:
            continue

        drifted += 1
        logger.warning(
            "[counter_drift] sub=%s org=%s used=%d (expected %d)  reserved=%d (expected %d)",
            sub.pk, sub.organization_id,
            sub.used_invoices, expected_used,
            sub.reserved_invoices, expected_reserved,
        )
        if auto_correct:
            sub.used_invoices = expected_used
            sub.reserved_invoices = expected_reserved
            sub.save(update_fields=["used_invoices", "reserved_invoices", "updated_at"])
            corrected += 1

    summary = {"checked": checked, "drifted": drifted, "corrected": corrected}
    logger.info("detect_counter_drift finished: %s", summary)
    return summary
