"""High-level payment orchestration.

This is the only layer business code should touch. It deliberately knows
nothing about specific providers — everything goes through the gateway
factory + adapter contract.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction as db_transaction
from django.utils import timezone

from apps.payments.choices import (
    PAID_STATUSES,
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
    TERMINAL_STATUSES,
)
from apps.payments.gateways.base import GatewayError
from apps.payments.gateways.factory import get_payment_gateway
from apps.payments.models import PaymentLog, PaymentTransaction
from apps.payments.pricing import (
    PriceMismatchError,
    PriceResolutionError,
    resolve_or_validate,
)


logger = logging.getLogger("payments.service")


class PaymentValidationError(ValueError):
    """Raised when input to PaymentService is invalid."""


class PaymentService:
    """Stateless orchestrator — instantiate freely, no shared state."""

    # ------------------------------------------------- transaction lifecycle

    def create_transaction(
        self,
        *,
        organization,
        user,
        amount,
        currency: str = "SAR",
        purpose: str,
        reference_type: str = "",
        reference_id: str = "",
        provider: Optional[str] = None,
        success_url: str = "",
        cancel_url: str = "",
        failure_url: str = "",
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None,
        request_ip: Optional[str] = None,
        user_agent: str = "",
    ) -> PaymentTransaction:
        """Create a new PaymentTransaction and kick off the gateway call.

        Returns the persisted transaction with ``checkout_url`` populated
        (when the provider returns one). On idempotency-key match,
        returns the prior transaction unchanged — even if it later
        transitioned to a terminal state."""
        amount = _coerce_amount(amount)
        if amount <= 0:
            raise PaymentValidationError("amount must be > 0")

        currency = (currency or "SAR").upper()
        if len(currency) != 3:
            raise PaymentValidationError("currency must be a 3-letter ISO code")

        # Replace client-supplied amount with the server-side authoritative
        # price for guarded purposes. Strict-deny: unknown purposes are
        # rejected. See apps/payments/pricing.py for the policy.
        try:
            amount, resolved_currency = resolve_or_validate(
                purpose=purpose,
                reference_type=reference_type or "",
                reference_id=reference_id or "",
                organization=organization,
                requested_amount=amount,
            )
        except PriceMismatchError as exc:
            raise PaymentValidationError(str(exc)) from exc
        except PriceResolutionError as exc:
            raise PaymentValidationError(str(exc)) from exc
        if resolved_currency:
            currency = resolved_currency.upper()

        if idempotency_key:
            existing = PaymentTransaction.objects.filter(
                idempotency_key=idempotency_key,
                organization=organization,
            ).first()
            if existing is not None:
                return existing

        gateway = get_payment_gateway(provider)

        with db_transaction.atomic():
            txn = PaymentTransaction.objects.create(
                organization=organization,
                user=user,
                provider=gateway.PROVIDER,
                purpose=purpose,
                reference_type=reference_type or "",
                reference_id=str(reference_id or ""),
                amount=amount,
                currency=currency,
                status=PaymentStatus.PENDING,
                success_url=success_url or "",
                cancel_url=cancel_url or "",
                failure_url=failure_url or "",
                idempotency_key=idempotency_key or None,
                raw_request=metadata or {},
                request_ip=request_ip,
                user_agent=user_agent or "",
            )
            PaymentLog.objects.create(
                transaction=txn, event_type="created",
                status_before="", status_after=txn.status,
                message=f"PaymentTransaction created (provider={gateway.PROVIDER})",
                payload=metadata or {},
            )

        # Substitute ``{transaction_id}`` in the redirect URLs now that
        # we have the persisted id. Callers can build URLs like
        #   "/payments/callback/moyasar/?transaction_id={transaction_id}"
        # without needing to pre-allocate UUIDs.
        url_dirty = False
        for attr in ("success_url", "cancel_url", "failure_url"):
            val = getattr(txn, attr, "") or ""
            if "{transaction_id}" in val:
                setattr(txn, attr, val.format(transaction_id=str(txn.id)))
                url_dirty = True
        if url_dirty:
            txn.save(update_fields=["success_url", "cancel_url", "failure_url", "updated_at"])

        # Gateway call happens OUTSIDE the atomic block — we want the
        # transaction row to survive even if the provider call fails so
        # there is something to retry against.
        try:
            response = gateway.create_payment(txn)
        except GatewayError as exc:
            self.mark_failed(txn, reason=str(exc), payload={})
            raise

        prior = txn.status
        txn.provider_payment_id = response.provider_payment_id or txn.provider_payment_id
        txn.provider_reference  = response.provider_reference  or txn.provider_reference
        txn.checkout_url        = response.checkout_url        or txn.checkout_url
        txn.raw_response        = response.raw_response or {}
        # If provider returned a recognised status, take it; otherwise
        # the safe default for a hosted-checkout flow is REDIRECT_REQUIRED.
        new_status = response.status or PaymentStatus.REDIRECT_REQUIRED
        if new_status == PaymentStatus.PENDING and txn.checkout_url:
            new_status = PaymentStatus.REDIRECT_REQUIRED
        txn.status = new_status
        txn.save(update_fields=[
            "provider_payment_id", "provider_reference", "checkout_url",
            "raw_response", "status", "updated_at",
        ])
        PaymentLog.objects.create(
            transaction=txn, event_type="gateway_created",
            status_before=prior, status_after=txn.status,
            message="Gateway create_payment succeeded",
            payload=response.as_dict(),
        )
        return txn

    # ------------------------------------------------ manual (offline) payment

    def create_manual_payment(
        self,
        *,
        organization,
        user,
        subscription,
        amount,
        currency: str,
        reference: str,
        reason: Optional[str] = None,
        request=None,
    ) -> PaymentTransaction:
        """Create a PENDING manual (offline/bank-transfer) payment for a
        subscription — with NO gateway call, NO signal, and NO activation.

        Confirmation is a separate later step (``mark_paid``), which runs the
        existing payment_paid → subscription-activation signal chain. This
        method only records the intended payment in PENDING state.

        Guards (raise ``PaymentValidationError``):
          * subscription must belong to ``organization``;
          * subscription.status must be PENDING_PAYMENT (not active/trialing/
            expired/canceled/payment_failed);
          * the org must have NO other usable (active/trialing) subscription —
            prevents a double-active subscription on later confirm;
          * ``amount`` must equal the plan price; ``currency`` must match the
            plan currency; ``reference`` is required.

        Idempotent per subscription via ``idempotency_key=manual-sub-<id>``:
        a second attempt is rejected (one manual payment per subscription).
        """
        from apps.billing.choices import USABLE_STATUSES, SubscriptionStatus
        from apps.billing.models import OrganizationSubscription

        # ownership
        if subscription.organization_id != getattr(organization, "id", None):
            raise PaymentValidationError(
                "Subscription does not belong to this organization."
            )
        # only a pending-payment subscription
        if subscription.status != SubscriptionStatus.PENDING_PAYMENT:
            raise PaymentValidationError(
                f"Manual payment is only allowed for a pending_payment "
                f"subscription (got {subscription.status!r})."
            )
        # double-active guard: no OTHER usable subscription
        if (
            OrganizationSubscription.objects
            .filter(
                organization_id=subscription.organization_id,
                status__in=USABLE_STATUSES,
            )
            .exclude(pk=subscription.pk)
            .exists()
        ):
            raise PaymentValidationError(
                "Organization already has a usable subscription; a manual "
                "payment would create a second active subscription."
            )
        # reference required
        reference = (reference or "").strip()
        if not reference:
            raise PaymentValidationError(
                "A payment reference is required for manual payments."
            )
        # amount must equal the authoritative plan price
        plan = subscription.plan
        amount = _coerce_amount(amount).quantize(Decimal("0.01"))
        authoritative = Decimal(plan.price).quantize(Decimal("0.01"))
        if amount != authoritative:
            raise PaymentValidationError(
                f"Manual amount {amount} does not match the plan price "
                f"{authoritative}."
            )
        # currency must match the plan currency
        currency = (currency or "").upper()
        plan_currency = (plan.currency or "SAR").upper()
        if currency != plan_currency:
            raise PaymentValidationError(
                f"Currency {currency!r} does not match the plan currency "
                f"{plan_currency!r}."
            )

        # idempotency: one manual payment per subscription
        idem = f"manual-sub-{subscription.id}"
        if PaymentTransaction.objects.filter(
            idempotency_key=idem,
            organization_id=subscription.organization_id,
        ).exists():
            raise PaymentValidationError(
                "A manual payment already exists for this subscription."
            )

        request_ip = None
        if request is not None:
            from core.utils.coerce import get_client_ip
            request_ip = get_client_ip(request)

        with db_transaction.atomic():
            txn = PaymentTransaction.objects.create(
                organization=subscription.organization,
                user=user,
                provider=PaymentProvider.MANUAL.value,
                purpose=PaymentPurpose.SUBSCRIPTION.value,
                reference_type="organization_subscription",
                reference_id=str(subscription.id),
                amount=authoritative,
                currency=plan_currency,
                status=PaymentStatus.PENDING,
                provider_reference=reference,   # the bank/transfer reference
                idempotency_key=idem,
                request_ip=request_ip,
                # raw_request / raw_response / raw_webhook / checkout_url /
                # provider_payment_id are intentionally left at their empty
                # defaults — there is no gateway and no secrets to store.
            )
            PaymentLog.objects.create(
                transaction=txn,
                event_type="manual_created",
                status_before="",
                status_after=txn.status,
                message=f"Manual payment created (reference={reference})",
                payload={
                    "source": "crm_manual",
                    "reference": reference,
                    "reason": (reason or "").strip() or None,
                    "user_id": str(getattr(user, "id", "") or "") or None,
                },
            )
        return txn

    # ------------------------------------------------ state transitions

    def mark_paid(self, txn: PaymentTransaction, payload: Optional[dict] = None) -> bool:
        """Set status=paid and run the business action.

        Returns True if the transition happened, False if the txn was
        already paid (so callers can short-circuit business actions on
        duplicate webhooks)."""
        # Re-read under a row lock to make this idempotent under
        # concurrent webhook deliveries.
        with db_transaction.atomic():
            locked = (
                PaymentTransaction.objects
                .select_for_update()
                .get(pk=txn.pk)
            )
            if locked.status == PaymentStatus.PAID:
                PaymentLog.objects.create(
                    transaction=locked, event_type="paid_duplicate",
                    status_before=locked.status, status_after=locked.status,
                    message="Duplicate paid event ignored",
                    payload=payload or {},
                )
                return False
            prior = locked.status
            locked.status  = PaymentStatus.PAID
            locked.paid_at = timezone.now()
            locked.save(update_fields=["status", "paid_at", "updated_at"])
            PaymentLog.objects.create(
                transaction=locked, event_type="paid",
                status_before=prior, status_after=locked.status,
                message="Payment confirmed",
                payload=payload or {},
            )
            # Mutate the caller's instance to reflect new state.
            txn.status  = locked.status
            txn.paid_at = locked.paid_at

        try:
            self._run_business_action(txn, payload or {})
        except Exception:  # business actions must never undo the paid state
            logger.exception("Business action for txn %s raised", txn.pk)
        return True

    def mark_failed(self, txn: PaymentTransaction, *, reason: str, payload: Optional[dict] = None) -> bool:
        with db_transaction.atomic():
            locked = (
                PaymentTransaction.objects
                .select_for_update()
                .get(pk=txn.pk)
            )
            if locked.status in TERMINAL_STATUSES and locked.status != PaymentStatus.PAID:
                return False
            if locked.status == PaymentStatus.PAID:
                # Paid trumps failed — never demote a confirmed payment.
                return False
            prior = locked.status
            locked.status        = PaymentStatus.FAILED
            locked.failed_reason = (reason or "")[:512]
            locked.save(update_fields=["status", "failed_reason", "updated_at"])
            PaymentLog.objects.create(
                transaction=locked, event_type="failed",
                status_before=prior, status_after=locked.status,
                message=(reason or "")[:512],
                payload=payload or {},
            )
            txn.status        = locked.status
            txn.failed_reason = locked.failed_reason

        # Fan out the failure to whoever owns the referenced row
        # (subscription, invoice, etc).
        try:
            from apps.payments.signals import payment_failed
            payment_failed.send(
                sender=PaymentTransaction, transaction=txn,
                reason=reason or "", payload=payload or {},
            )
        except Exception:  # pragma: no cover — never undo state on receiver error
            logger.exception("payment_failed receivers raised for txn=%s", txn.pk)
        return True

    def mark_canceled(self, txn: PaymentTransaction, *, payload: Optional[dict] = None) -> bool:
        with db_transaction.atomic():
            locked = (
                PaymentTransaction.objects
                .select_for_update()
                .get(pk=txn.pk)
            )
            if locked.status in TERMINAL_STATUSES:
                return False
            prior = locked.status
            locked.status = PaymentStatus.CANCELED
            locked.save(update_fields=["status", "updated_at"])
            PaymentLog.objects.create(
                transaction=locked, event_type="canceled",
                status_before=prior, status_after=locked.status,
                payload=payload or {},
            )
            txn.status = locked.status
        return True

    # -------------------------------------------------------- syncing

    def sync_status(self, txn: PaymentTransaction) -> PaymentTransaction:
        """Re-query the provider and reconcile our row. Authoritative when
        webhook delivery is unreliable (e.g. user closed the tab)."""
        if not txn.provider_payment_id:
            raise PaymentValidationError("Transaction has no provider_payment_id yet")
        gateway = get_payment_gateway(txn.provider)
        response = gateway.retrieve_payment(txn.provider_payment_id)

        prior = txn.status
        target = response.status or txn.status
        # Don't move to a non-terminal state if we are already terminal.
        if txn.status in TERMINAL_STATUSES and target not in TERMINAL_STATUSES:
            return txn

        if target == PaymentStatus.PAID:
            self.mark_paid(txn, payload=response.raw_response)
        elif target == PaymentStatus.FAILED:
            self.mark_failed(txn, reason="Failed on retrieve sync", payload=response.raw_response)
        elif target == PaymentStatus.CANCELED:
            self.mark_canceled(txn, payload=response.raw_response)
        elif target != txn.status:
            txn.status = target
            txn.save(update_fields=["status", "updated_at"])
            PaymentLog.objects.create(
                transaction=txn, event_type="sync",
                status_before=prior, status_after=target,
                message="Status updated from retrieve_payment",
                payload=response.raw_response or {},
            )
        return txn

    # --------------------------------------------------------- refund

    def refund(self, txn: PaymentTransaction, *, amount: Optional[Decimal] = None) -> PaymentTransaction:
        """Issue a (partial or full) refund through the original gateway.

        Refunds are only valid for transactions that have actually been
        paid. ``amount=None`` issues a full refund.
        """
        if txn.status != PaymentStatus.PAID:
            raise PaymentValidationError(
                f"Only paid transactions can be refunded (current: {txn.status})"
            )
        if amount is not None:
            amount = _coerce_amount(amount)
            if amount <= 0 or amount > txn.amount:
                raise PaymentValidationError(
                    "Refund amount must be > 0 and <= the original amount."
                )

        gateway = get_payment_gateway(txn.provider)
        try:
            response = gateway.refund_payment(txn, amount=amount)
        except GatewayError as exc:
            PaymentLog.objects.create(
                transaction=txn,
                event_type="refund_failed",
                status_before=txn.status, status_after=txn.status,
                message=str(exc)[:512], payload={},
            )
            raise

        with db_transaction.atomic():
            locked = (
                PaymentTransaction.objects
                .select_for_update()
                .get(pk=txn.pk)
            )
            prior = locked.status
            full = amount is None or Decimal(amount) >= Decimal(locked.amount)
            locked.status = (
                PaymentStatus.REFUNDED if full else PaymentStatus.PARTIALLY_REFUNDED
            )
            locked.save(update_fields=["status", "updated_at"])
            PaymentLog.objects.create(
                transaction=locked,
                event_type="refunded" if full else "partially_refunded",
                status_before=prior,
                status_after=locked.status,
                message=f"Refund of {amount if amount is not None else locked.amount} issued",
                payload=response.as_dict(),
            )
            txn.status = locked.status
        return txn

    # -------------------------------------------------- business hook

    def _run_business_action(self, txn: PaymentTransaction, payload: dict) -> None:
        """Hook point for activating subscriptions, marking invoices paid, etc.

        Intentionally a no-op in this scaffold — wire concrete handlers
        in the apps that own the referenced resource (e.g. subscriptions
        signal handlers listen for ``PaymentLog`` ``paid`` events)."""
        from apps.payments.signals import payment_paid
        payment_paid.send(sender=PaymentTransaction, transaction=txn, payload=payload)


# ----------------------------------------------------------- helpers

def _coerce_amount(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise PaymentValidationError(f"amount is not a valid decimal: {value!r}") from exc
