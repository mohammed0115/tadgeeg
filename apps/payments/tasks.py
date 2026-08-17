"""Celery tasks for the payments app.

Reconciliation rationale:
- Webhook delivery is best-effort. Users close tabs, gateways have
  outages, our receiver might crash.
- For any transaction stuck in a non-terminal state past a sensible
  grace window, we re-query the provider via retrieve_payment and
  reconcile our local row. The webhook view is still authoritative
  when it does arrive — sync just covers the gap.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.payments.choices import PaymentStatus
from apps.payments.gateways.base import GatewayError
from apps.payments.models import PaymentLog, PaymentTransaction
from apps.payments.services.payment_service import PaymentService


logger = logging.getLogger("payments.tasks")


_NON_TERMINAL = (
    PaymentStatus.PENDING,
    PaymentStatus.INITIATED,
    PaymentStatus.REDIRECT_REQUIRED,
)

# Grace window before we start polling. Users typically complete a 3DS
# challenge in well under 15 min; anything older is a webhook failure
# or an abandoned session.
DEFAULT_GRACE_MINUTES = 30
# Don't keep polling forever — after a few hours, mark as expired.
EXPIRY_HOURS = 24


@shared_task(bind=True, name="payments.process_payment_business_action", max_retries=5)
def process_payment_business_action(self, transaction_id: str) -> dict:
    """Run a paid transaction's entitlement action from durable state."""
    with transaction.atomic():
        txn = PaymentTransaction.objects.select_for_update().get(pk=transaction_id)
        if txn.status != PaymentStatus.PAID:
            return {"transaction_id": transaction_id, "skipped": "not_paid"}
        if txn.business_action_status == "completed":
            return {"transaction_id": transaction_id, "skipped": "completed"}
        txn.business_action_status = "processing"
        txn.business_action_attempts += 1
        txn.save(update_fields=["business_action_status", "business_action_attempts", "updated_at"])

    try:
        PaymentService()._run_business_action(txn, {})
    except Exception as exc:  # noqa: BLE001 - persist and retry domain failures
        with transaction.atomic():
            current = PaymentTransaction.objects.select_for_update().get(pk=transaction_id)
            current.business_action_status = "pending"
            current.business_action_error = str(exc)[:512]
            current.save(update_fields=["business_action_status", "business_action_error", "updated_at"])
            PaymentLog.objects.create(
                transaction=current,
                event_type="business_action_failed",
                status_before=current.status,
                status_after=current.status,
                message=current.business_action_error,
                payload={"attempt": current.business_action_attempts},
            )
        raise self.retry(exc=exc, countdown=min(300, 2 ** self.request.retries))

    with transaction.atomic():
        current = PaymentTransaction.objects.select_for_update().get(pk=transaction_id)
        current.business_action_status = "completed"
        current.business_action_error = ""
        current.save(update_fields=["business_action_status", "business_action_error", "updated_at"])
        PaymentLog.objects.create(
            transaction=current,
            event_type="business_action_completed",
            status_before=current.status,
            status_after=current.status,
            message="Post-payment business action completed",
            payload={"attempt": current.business_action_attempts},
        )
    return {"transaction_id": transaction_id, "completed": True}


@shared_task(name="payments.reconcile_payment_business_actions")
def reconcile_payment_business_actions(batch_size: int = 100) -> dict:
    """Re-dispatch durable actions left pending by broker or worker failures."""
    transaction_ids = list(
        PaymentTransaction.objects.filter(
            status=PaymentStatus.PAID,
            business_action_status__in=("pending", "processing"),
        ).order_by("updated_at").values_list("pk", flat=True)[:batch_size]
    )
    for transaction_id in transaction_ids:
        process_payment_business_action.delay(str(transaction_id))
    return {"dispatched": len(transaction_ids)}


@shared_task(name="payments.reconcile_stale_payments")
def reconcile_stale_payments(grace_minutes: int = DEFAULT_GRACE_MINUTES,
                             batch_size: int = 100) -> dict:
    """Re-query the provider for transactions stuck in a non-terminal state.

    Returns a small dict with counts so beat logs are readable.
    """
    cutoff = timezone.now() - timedelta(minutes=grace_minutes)
    expiry_cutoff = timezone.now() - timedelta(hours=EXPIRY_HOURS)

    qs = (
        PaymentTransaction.objects
        .filter(status__in=_NON_TERMINAL)
        .filter(updated_at__lt=cutoff)
        .exclude(provider_payment_id="")
        .order_by("updated_at")[:batch_size]
    )

    counts = {"checked": 0, "transitioned": 0, "expired": 0, "errors": 0}
    svc = PaymentService()

    for txn in qs:
        counts["checked"] += 1

        # Abandon sessions older than EXPIRY_HOURS so they stop being polled.
        if txn.created_at < expiry_cutoff:
            prior = txn.status
            txn.status = PaymentStatus.EXPIRED
            txn.save(update_fields=["status", "updated_at"])
            PaymentLog.objects.create(
                transaction=txn,
                event_type="expired_by_reconciler",
                status_before=prior,
                status_after=txn.status,
                message=f"Transaction abandoned after {EXPIRY_HOURS}h",
                payload={},
            )
            counts["expired"] += 1
            continue

        prior = txn.status
        try:
            svc.sync_status(txn)
        except GatewayError as exc:
            counts["errors"] += 1
            logger.warning("Reconcile %s: gateway error: %s", txn.pk, exc)
            PaymentLog.objects.create(
                transaction=txn,
                event_type="reconcile_error",
                status_before=prior, status_after=txn.status,
                message=str(exc)[:512],
                payload={},
            )
            continue
        if txn.status != prior:
            counts["transitioned"] += 1

    logger.info("reconcile_stale_payments finished: %s", counts)
    return counts
