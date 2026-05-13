"""Payments — core models.

The design splits payment state across two tables: ``PaymentTransaction``
holds the durable financial record (one row per intended payment),
``PaymentLog`` records every state transition / webhook / sync event so
that disputes and forensic questions can be answered from the database
alone — never from provider dashboards.

We never store PAN/CVV: the gateway adapters always use hosted checkout
or redirect-style flows, and only opaque provider IDs land in our DB.
"""
import uuid
from decimal import Decimal

from django.db import models

from apps.authentication.models import Organization, User
from apps.payments.choices import (
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
)
from apps.payments.encryption import EncryptedTextField


class PaymentTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="payment_transactions",
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="payment_transactions",
        null=True, blank=True,
    )

    provider = models.CharField(max_length=16, choices=PaymentProvider.choices)
    purpose  = models.CharField(max_length=20, choices=PaymentPurpose.choices)

    # Generic link to whatever is being paid for. Kept as
    # type+id rather than a GenericForeignKey to keep migrations simple and
    # to allow the reference to live in a different schema/service later.
    reference_type = models.CharField(max_length=64, blank=True, default="")
    reference_id   = models.CharField(max_length=64, blank=True, default="")

    amount   = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="SAR")

    status = models.CharField(
        max_length=24, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
    )

    # Identifiers issued by the provider after create_payment succeeds.
    provider_payment_id = models.CharField(max_length=128, blank=True, default="")
    provider_reference  = models.CharField(max_length=128, blank=True, default="")

    checkout_url = models.URLField(max_length=1024, blank=True, default="")
    success_url  = models.URLField(max_length=1024, blank=True, default="")
    cancel_url   = models.URLField(max_length=1024, blank=True, default="")
    failure_url  = models.URLField(max_length=1024, blank=True, default="")

    raw_request  = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    raw_webhook  = models.JSONField(default=dict, blank=True)

    # Caller-provided idempotency token. Unique across the table so a
    # retried request returns the original transaction instead of charging twice.
    idempotency_key = models.CharField(
        max_length=128, unique=True, null=True, blank=True,
    )

    paid_at       = models.DateTimeField(null=True, blank=True)
    failed_reason = models.CharField(max_length=512, blank=True, default="")

    # Forensic context for hardened endpoints.
    request_ip   = models.GenericIPAddressField(null=True, blank=True)
    user_agent   = models.CharField(max_length=512, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["provider", "provider_payment_id"]),
            models.Index(fields=["purpose", "reference_type", "reference_id"]),
        ]

    def __str__(self):
        return f"{self.provider}:{self.id} {self.amount} {self.currency} ({self.status})"

    @property
    def is_terminal(self):
        from apps.payments.choices import TERMINAL_STATUSES
        return self.status in TERMINAL_STATUSES

    @property
    def is_paid(self):
        return self.status == PaymentStatus.PAID


class PaymentLog(models.Model):
    """Append-only audit trail of everything that happened to a transaction."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    transaction = models.ForeignKey(
        PaymentTransaction, on_delete=models.CASCADE, related_name="logs",
    )
    event_type    = models.CharField(max_length=64)
    status_before = models.CharField(max_length=24, blank=True, default="")
    status_after  = models.CharField(max_length=24, blank=True, default="")
    message       = models.CharField(max_length=512, blank=True, default="")
    payload       = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["transaction", "event_type"]),
        ]

    def __str__(self):
        return f"{self.event_type} on {self.transaction_id}"


class FailedWebhookEvent(models.Model):
    """Dead-letter queue for webhook deliveries we couldn't process.

    Anything that doesn't reach a clean ``OK`` outcome — bad signature,
    unparseable body, no matching transaction — is captured here so an
    operator can investigate and replay via the admin once the
    underlying cause is fixed (typically: misconfigured webhook secret,
    or a transaction created on a different env).
    """
    class Reason(models.TextChoices):
        UNVERIFIED   = "unverified",   "Signature/verification failed"
        BAD_PAYLOAD  = "bad_payload",  "Unparseable body"
        UNKNOWN_TXN  = "unknown_txn",  "No matching transaction"
        DISPATCH_ERR = "dispatch_err", "Error during dispatch"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider    = models.CharField(max_length=16)
    reason      = models.CharField(max_length=20, choices=Reason.choices)
    message     = models.CharField(max_length=512, blank=True, default="")

    # Raw HTTP envelope — enough to replay the request through the same
    # adapter once the underlying problem is fixed.
    body        = models.BinaryField(blank=True, null=True)
    headers     = models.JSONField(default=dict, blank=True)

    # Forensic
    remote_ip   = models.GenericIPAddressField(null=True, blank=True)
    user_agent  = models.CharField(max_length=512, blank=True, default="")

    replayed    = models.BooleanField(default=False)
    replayed_at = models.DateTimeField(null=True, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "reason"]),
            models.Index(fields=["replayed"]),
        ]

    def __str__(self):
        return f"{self.provider}:{self.reason} @ {self.created_at:%Y-%m-%d %H:%M}"


# Removed in Stage-9 cleanup (QA report M-3):
#   class PaymentProviderConfig(models.Model): ...
#
# The factory and every adapter read from env vars only. No code path
# ever consulted the table, so it stays dropped. If per-tenant provider
# overrides become a requirement, reintroduce this model AND wire it
# into ``apps.payments.gateways.factory.get_payment_gateway`` (accepting
# an organization parameter, falling back to env when no active config
# exists). Until then, env-only is the single source of truth.
