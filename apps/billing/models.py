"""Billing core models.

Design notes:
- ``Plan`` is the catalogue row — name/price/quota — managed by ops and
  seeded via ``manage.py seed_billing_plans``.
- ``OrganizationSubscription`` is a *snapshot* of the plan at purchase
  time. ``invoice_limit`` is duplicated onto the subscription so that
  raising the price or quota on the ``Plan`` row later does NOT silently
  upgrade or downgrade existing customers.
- ``UsageLedger`` is append-only — every reserve/consume/release writes
  a row so audit/finance can answer "where did the 100 invoices go?".

This module is intentionally standalone: no signals, no integration
with the audit pipeline yet. Stage 5 wires it in.
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from apps.authentication.models import Organization
from apps.billing.choices import (
    AddonBillingType,
    AddonDimension,
    PlanCode,
    SubscriptionStatus,
    UsageAction,
)


class Plan(models.Model):
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    code = models.CharField(
        # 32, not 20: "accounting_professional" is 23 characters. Widening a
        # CharField is a safe, non-destructive schema change.
        max_length=32, unique=True, choices=PlanCode.choices,
        help_text="Stable identifier used by code and APIs.",
    )

    name_ar = models.CharField(max_length=128)
    name_en = models.CharField(max_length=128)

    description_ar = models.TextField(blank=True, default="")
    description_en = models.TextField(blank=True, default="")

    # ── Limits ──────────────────────────────────────────────────────────
    # NULL means UNLIMITED, not zero. Zero already means "no allowance at all"
    # on these columns, so overloading it would make an enterprise plan
    # indistinguishable from a disabled one. Every read path must therefore ask
    # "is this None?" before comparing — see UNLIMITED / has_limit() below.
    invoice_limit  = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Invoices auditable per billing period. NULL = unlimited.",
    )
    user_limit = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Seats (active users in the organisation). NULL = unlimited.",
    )
    # company_limit is deliberately ABSENT. See docs/adr/0006-plan-limit-dimensions.md:
    # one OrganizationSubscription FKs to exactly one Organization and a unique
    # constraint enforces one usable subscription per organisation, so "one
    # subscription covering 20 client companies" cannot be expressed today.
    # Storing an unenforceable number would be a guarantee that does not exist.

    # ── Price ───────────────────────────────────────────────────────────
    # NULL price + is_custom_quote=True means "contact sales". NOT 0.00, which
    # would read as FREE and make the plan purchasable through self-service
    # checkout at no charge.
    price          = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="NULL when is_custom_quote is set — the plan has no list price.",
    )
    is_custom_quote = models.BooleanField(
        default=False,
        help_text="Priced by negotiation. Not purchasable through self-service checkout.",
    )
    currency       = models.CharField(max_length=3, default="SAR")
    duration_days  = models.PositiveIntegerField(default=30)

    is_free  = models.BooleanField(default=False)
    is_trial = models.BooleanField(
        default=False,
        help_text="Trial plans can be activated only once per organisation.",
    )
    is_active = models.BooleanField(default=True)

    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price"]
        indexes  = [models.Index(fields=["is_active", "sort_order"])]

    UNLIMITED = None

    @staticmethod
    def has_limit(value) -> bool:
        """True when a limit column actually constrains something.

        The one place the None-means-unlimited convention is interpreted, so
        enforcement never open-codes ``if limit is not None`` and never compares
        against a sentinel big number.
        """
        return value is not None

    @property
    def is_purchasable(self) -> bool:
        """Self-service checkout eligibility.

        Custom-quote plans are excluded: they have no list price, so there is
        nothing for the payment resolver to charge.
        """
        return self.is_active and not self.is_custom_quote and self.price is not None

    def __str__(self):
        invoices = self.invoice_limit if self.invoice_limit is not None else "unlimited"
        price = f"{self.price} {self.currency}" if self.price is not None else "custom quote"
        return f"{self.code} ({invoices} inv / {price})"


class OrganizationSubscription(models.Model):
    """One row per (org, billing period). ``invoice_limit`` is frozen at
    activation — see module docstring for rationale."""
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="subscriptions",
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="subscriptions",
    )

    status = models.CharField(
        max_length=20, choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.PENDING_PAYMENT,
    )

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at   = models.DateTimeField(null=True, blank=True)

    # Snapshot of the plan's quota at activation time — frozen.
    # Snapshot of the plan's limits at activation — frozen. A later catalogue
    # edit must never reprice or re-limit a paying customer, and this is the
    # mechanism that guarantees it. NULL = unlimited, same convention as Plan.
    invoice_limit      = models.PositiveIntegerField(null=True, blank=True, default=0)
    user_limit         = models.PositiveIntegerField(null=True, blank=True, default=None)
    used_invoices      = models.PositiveIntegerField(default=0)
    reserved_invoices  = models.PositiveIntegerField(default=0)

    # The price this customer agreed to, frozen the same way the limits are.
    #
    # Until now only limits were snapshotted: payment resolved the amount from
    # the LIVE plan, so editing a catalogue price changed what an already-placed
    # subscription would be charged — a price the customer never agreed to.
    #
    # NULL does NOT mean free and does NOT mean "look it up". It means this row
    # predates the snapshot and its agreed price is unknowable. Backfilling from
    # today's catalogue would invent history, so resolution refuses instead; see
    # payments/pricing.py.
    price_at_purchase = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Agreed price, frozen at creation. NULL = pre-snapshot row.",
    )
    currency_at_purchase = models.CharField(
        max_length=8, blank=True, default="",
        help_text="Currency frozen alongside price_at_purchase.",
    )
    # Set when staff record a negotiated amount for a custom-quote plan, which
    # has no list price to freeze. Kept separate from the value itself so the
    # provenance of an amount is never a guess.
    price_is_negotiated = models.BooleanField(default=False)

    auto_renew = models.BooleanField(default=False)

    # FK to PaymentTransaction (Stage-9 QA hardening D-2). String FK
    # keeps this app importable when apps/payments is installed last;
    # on_delete=SET_NULL because deleting the txn shouldn't cascade
    # away the subscription it paid for — the sub stays so finance
    # can still investigate. Indexed via the FK by default.
    payment_transaction = models.ForeignKey(
        "payments.PaymentTransaction",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="subscriptions_funded",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["status", "ends_at"]),
        ]
        constraints = [
            # One usable subscription per organisation at any time —
            # closes the M-1 gap from the Stage 9 QA report. Backstops
            # the application-level _reuse_recent_pending logic so two
            # different paid plans cannot both end up ACTIVE for the
            # same org (e.g. a race between concurrent webhook
            # deliveries). Status migrations remain free; only the
            # ACTIVE+TRIALING set is constrained.
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(status__in=["active", "trialing"]),
                name="billing_one_usable_sub_per_org",
            ),
        ]

    def __str__(self):
        return f"{self.organization_id} → {self.plan.code} ({self.status})"

    # ---- derived helpers ----
    @property
    def has_frozen_price(self) -> bool:
        """Whether this row carries the price its customer agreed to.

        False only for rows created before the snapshot existed. Callers must
        branch on this rather than treating a NULL price as zero — one of those
        readings charges nothing, the other refuses, and they are not the same.
        """
        return self.price_at_purchase is not None

    @property
    def is_unlimited_invoices(self) -> bool:
        return self.invoice_limit is None

    @property
    def remaining_invoices(self):
        """Remaining allowance, or None when unlimited.

        Returns None rather than a huge number so callers must handle the
        unlimited case explicitly instead of accidentally arithmetic-ing on a
        sentinel.
        """
        if self.invoice_limit is None:
            return None
        return max(0, self.invoice_limit - self.used_invoices - self.reserved_invoices)

    @property
    def is_usable(self) -> bool:
        from apps.billing.choices import USABLE_STATUSES
        return self.status in USABLE_STATUSES


class UsageLedger(models.Model):
    """Append-only record of every quota change. Drives forensic
    reconstruction of ``used_invoices`` / ``reserved_invoices`` if the
    counters ever drift from reality."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="usage_ledger_entries",
    )
    subscription = models.ForeignKey(
        OrganizationSubscription, on_delete=models.CASCADE, related_name="ledger_entries",
    )

    # String FKs so this app stays importable even when documents/audit
    # apps aren't in a deployment. Both nullable since reserve happens
    # before audit_run exists.
    document  = models.ForeignKey(
        "documents.Document",       on_delete=models.SET_NULL, null=True, blank=True,
        related_name="billing_ledger_entries",
    )
    audit_run = models.ForeignKey(
        "rule_engine.AuditRun",     on_delete=models.SET_NULL, null=True, blank=True,
        related_name="billing_ledger_entries",
    )

    action   = models.CharField(max_length=10, choices=UsageAction.choices)
    quantity = models.PositiveIntegerField(default=1)
    reason   = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "action"]),
            models.Index(fields=["subscription", "action"]),
            models.Index(fields=["document", "action"]),
        ]

    def __str__(self):
        return f"{self.organization_id} {self.action} {self.quantity} ({self.created_at:%Y-%m-%d})"


class Addon(models.Model):
    """Catalogue of purchasable add-ons (§I).

    One table, three billing types — and the type, not a convention, decides
    what happens at renewal. §I is explicit that these must not be treated as
    one billing type, so `billing_type` drives `SubscriptionAddon.renew()`
    rather than being descriptive metadata.

    `dimension` says which ceiling the add-on raises. Professional services
    raise none: they are billable but grant no quota, and folding them in with
    quota packs would inflate an allowance nobody bought.
    """

    UNLIMITED = None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=48, unique=True)
    name_en = models.CharField(max_length=120)
    name_ar = models.CharField(max_length=120, blank=True, default="")

    billing_type = models.CharField(
        max_length=16, choices=AddonBillingType.choices,
    )
    dimension = models.CharField(
        max_length=16, choices=AddonDimension.choices,
        default=AddonDimension.NONE,
    )
    #: How much of `dimension` this add-on grants. NULL for services and for
    #: custom quotes, which grant nothing measurable.
    quantity = models.PositiveIntegerField(null=True, blank=True)

    #: NULL price means "no list price". For CUSTOM_QUOTE that is the whole
    #: point; the same NULL-is-not-zero rule as Plan.price applies — 0.00 would
    #: read as free and let it through self-service for nothing.
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default="SAR")

    #: "يبدأ من" in §I.3 — a floor for a negotiated engagement, not a price
    #: anyone can pay today. Treated as not self-service purchasable.
    is_price_from = models.BooleanField(
        default=False,
        help_text='Spec says "starts from": a floor for negotiation, not a payable price.',
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "code"]

    def __str__(self):
        return f"{self.code} ({self.billing_type})"

    @property
    def is_purchasable(self) -> bool:
        """Self-service eligibility.

        A custom quote has nothing to charge, and a "from" price is a floor
        under a negotiation — neither can be bought from a page.
        """
        return (
            self.is_active
            and self.billing_type != AddonBillingType.CUSTOM_QUOTE
            and self.price is not None
            and not self.is_price_from
        )

    @property
    def renews(self) -> bool:
        """Whether buying this again happens automatically at renewal."""
        return self.billing_type == AddonBillingType.RECURRING


class SubscriptionAddon(models.Model):
    """An add-on actually bought by an organisation.

    Prices are frozen here for the same reason they are frozen on the
    subscription (D1): what someone agreed to pay must survive a catalogue
    edit. `quantity_at_purchase` is frozen too, so re-sizing a pack in the
    catalogue never silently changes an existing customer's ceiling.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        "billing.OrganizationSubscription",
        on_delete=models.CASCADE, related_name="addons",
    )
    addon = models.ForeignKey(Addon, on_delete=models.PROTECT, related_name="purchases")

    billing_type = models.CharField(max_length=16, choices=AddonBillingType.choices)
    dimension = models.CharField(max_length=16, choices=AddonDimension.choices)
    quantity_at_purchase = models.PositiveIntegerField(null=True, blank=True)
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)
    currency_at_purchase = models.CharField(max_length=8, default="SAR")

    #: An add-on counts toward the effective quota only while active. A
    #: recurring add-on that lapses must drop the ceiling automatically, which
    #: is why this is a queryable column rather than an inference.
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    #: NULL = no end date. For one-time credit this is deliberate: the credit
    #: belongs to the customer until consumed, subject to the rollover policy.
    ends_at = models.DateTimeField(null=True, blank=True)

    #: One-time invoice credit is consumed like plan quota, so it needs its own
    #: counter — otherwise "how much of the pack is left" has no answer.
    used_units = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["subscription", "is_active"]),
            models.Index(fields=["subscription", "dimension", "is_active"]),
        ]

    def __str__(self):
        return f"{self.addon.code} x{self.quantity_at_purchase or 0}"

    @property
    def renews(self) -> bool:
        return self.billing_type == AddonBillingType.RECURRING

    @property
    def remaining_units(self) -> int:
        """Unconsumed credit on a one-time pack."""
        total = self.quantity_at_purchase or 0
        return max(total - (self.used_units or 0), 0)
