"""Built-in receivers for ``payment_paid``.

This is the bridge between the provider-agnostic payments domain and
the business apps that act on a successful charge. Each receiver is
purpose-scoped: it inspects the transaction, runs the minimal "did
something happen?" step we can verify here, and re-emits a typed signal
(e.g. ``subscription_paid``) for the owning app to subscribe to.

We deliberately keep the work here small. Anything that mutates a
domain row (activating a Subscription, flipping Invoice.status) belongs
in *that* domain's signal handler — not here.
"""
from __future__ import annotations

import logging

from django.dispatch import receiver

from apps.payments.choices import PaymentPurpose
from apps.payments.models import PaymentLog
from apps.payments.signals import (
    invoice_paid,
    payment_paid,
    service_order_paid,
    subscription_paid,
    wallet_topped_up,
)


logger = logging.getLogger("payments.receivers")


_PURPOSE_SIGNAL = {
    PaymentPurpose.SUBSCRIPTION.value:  subscription_paid,
    PaymentPurpose.INVOICE.value:       invoice_paid,
    PaymentPurpose.SERVICE_ORDER.value: service_order_paid,
    PaymentPurpose.WALLET_TOPUP.value:  wallet_topped_up,
}


@receiver(payment_paid)
def fanout_by_purpose(sender, transaction, payload, **kwargs):
    """Re-emit ``payment_paid`` as a purpose-typed signal so domain apps
    can listen to just the events they care about."""
    sig = _PURPOSE_SIGNAL.get(transaction.purpose)
    if sig is None:
        logger.info(
            "payment_paid for txn=%s has no purpose-specific signal (purpose=%s)",
            transaction.pk, transaction.purpose,
        )
        return
    sig.send(sender=transaction.__class__, transaction=transaction, payload=payload)


@receiver(invoice_paid)
def log_invoice_settlement(sender, transaction, payload, **kwargs):
    """Forensic record that the linked invoice has been settled.

    The current apps.invoices.Invoice model is the *audit* invoice and
    has no payment_status column. We don't flip its status here — that
    belongs to a future SaaS-billing-invoice domain. What we do record
    is a PaymentLog row so the link from txn → invoice is discoverable
    from the payments side."""
    if not transaction.reference_id:
        return
    PaymentLog.objects.create(
        transaction=transaction,
        event_type="business_action",
        status_before=transaction.status,
        status_after=transaction.status,
        message=f"invoice_paid for ref={transaction.reference_id}",
        payload={"reference_id": transaction.reference_id},
    )
