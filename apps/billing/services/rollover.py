"""Rollover policy for unused one-time invoice credit (D3).

Two behaviours, both implemented, switchable by an administrator:

* **carry_over** — bought 1,000, used 300, 700 remains next cycle. Default.
* **expire** — unused credit is dropped at reset.

**Where this lives, and why not in cms.PlatformSetting.** That table is
admin-editable and would have been the quick route, but a billing behaviour
stored in the CMS settings table recreates exactly the split that made
`cms.PricingPlan` a source-of-truth problem (ADR 0001) — two places that look
authoritative, one that actually is. It also carries an `is_public` flag, and a
billing policy must never be publicly readable. So it lives in `apps/billing`,
which owns the behaviour it governs.

**MONEY RULE 2 is the constraint that shapes this module.** A policy change
applies to future cycles only. Credit already accrued while carry-over was
enabled belongs to the customer who paid for it, and flipping the switch must
never reach back and delete it. That is why the policy is read *at the moment a
cycle resets* and never applied retroactively, and why the effective date is
recorded rather than assumed.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.billing.choices import RolloverPolicy
from apps.billing.models import BillingPolicy


class RolloverService:
    """Read and change the policy, and apply it at a cycle reset."""

    def get_policy(self) -> BillingPolicy:
        """The current policy row, created with the shipped default if absent."""
        obj, _created = BillingPolicy.objects.get_or_create(
            pk=BillingPolicy.SINGLETON_PK,
        )
        return obj

    def carry_over_enabled(self) -> bool:
        return self.get_policy().invoice_credit_rollover == RolloverPolicy.CARRY_OVER

    @transaction.atomic
    def set_policy(self, *, value: str, actor, request=None, reason: str = "") -> BillingPolicy:
        """Change the policy, audited.

        The change takes effect from now; it is never applied to cycles that
        have already reset. Credit a customer already holds was paid for under
        the old rule and keeps it (MONEY RULE 2).
        """
        if value not in RolloverPolicy.values:
            raise ValueError(f"Unknown rollover policy {value!r}")

        policy = self.get_policy()
        old = policy.invoice_credit_rollover
        if old == value:
            return policy

        policy.invoice_credit_rollover = value
        policy.effective_from = timezone.now()
        policy.updated_by = actor if getattr(actor, "pk", None) else None
        policy.save()

        # Audited through the same hash-chained writer the CRM uses, so a
        # billing-policy change is attributable in the same place as every
        # other privileged action.
        from apps.platform_admin.services.crm_audit import log_crm_action

        log_crm_action(
            actor=actor,
            organization=None,
            action_type="billing_policy_changed",
            resource_type="BillingPolicy",
            resource_id=policy.pk,
            reason=reason or "Rollover policy changed",
            old_value={"invoice_credit_rollover": old},
            new_value={"invoice_credit_rollover": value},
            metadata={"effective_from": policy.effective_from.isoformat()},
            record_activity=False,
        )
        return policy

    @transaction.atomic
    def apply_cycle_reset(self, subscription) -> dict:
        """Reset the subscription's cycle counters, honouring the policy.

        Under **carry_over**, unconsumed one-time credit is left alone and
        remains available. Under **expire**, it is closed out.

        Either way this reads the policy *now*, at the reset — which is what
        keeps a later policy change from reaching backwards.
        """
        from apps.billing.services.addon_service import AddonService

        carry = self.carry_over_enabled()
        result = AddonService().renew_for_cycle(subscription, carry_over_credit=carry)

        subscription.used_invoices = 0
        subscription.reserved_invoices = 0
        subscription.save(update_fields=[
            "used_invoices", "reserved_invoices", "updated_at",
        ])

        result["policy"] = (
            RolloverPolicy.CARRY_OVER if carry else RolloverPolicy.EXPIRE
        )
        return result
