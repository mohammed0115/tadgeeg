"""Trial → paid conversion, driven from the Trial Users Dashboard (§B.1).

This is a thin wrapper, on purpose. It owns three things — validation, the
audit trail, and idempotency — and delegates every actual subscription write to
``apps.billing.services.subscription_service.SubscriptionService``. It never
sets ``status``, ``ends_at``, ``invoice_limit`` or the quota counters itself.

Writing a second conversion path would mean two places that can create an
ACTIVE subscription, and the "one usable subscription per organisation" rule is
enforced in application code (the partial DB constraint does not apply on
MySQL — see ``subscription_service.activate_subscription``). A parallel path
would silently defeat it.
"""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.billing.choices import SubscriptionStatus, USABLE_STATUSES
from apps.billing.models import OrganizationSubscription, Plan
from apps.platform_admin.services.crm_audit import log_crm_action
from core.permissions import is_platform_user

logger = logging.getLogger("leads.trial_conversion")

#: The CRM verb recorded in AuditLog.details["action_type"].
ACTION_TYPE = "trial_converted_to_paid"


class TrialConversionError(Exception):
    """Conversion refused for a domain reason (already paid, no organisation…)."""


@transaction.atomic
def convert_trial_to_paid(*, actor, profile, plan_code, request=None):
    """Move a trial registrant onto a paid plan.

    Idempotent in the way that matters: if the organisation already holds an
    ACTIVE non-trial subscription, this raises ``TrialConversionError`` rather
    than creating a second one. Double-submitting the dashboard button cannot
    produce two paid subscriptions.

    Returns the activated ``OrganizationSubscription``.
    """
    if not is_platform_user(actor):
        raise PermissionDenied("Platform staff access is required to convert a trial.")

    organization = getattr(profile.user, "organization", None)
    if organization is None:
        raise TrialConversionError("This registrant has no organisation to convert.")

    try:
        plan = Plan.objects.get(code=plan_code, is_active=True)
    except Plan.DoesNotExist as exc:
        raise ValidationError(f"Unknown or inactive plan: {plan_code!r}") from exc

    if plan.is_trial or plan.is_free:
        raise ValidationError(
            f"Plan {plan.code} is free/trial — conversion requires a paid plan."
        )

    # Idempotency gate. Checked under the same transaction as the write below.
    already_paid = (
        OrganizationSubscription.objects.select_for_update()
        .filter(
            organization=organization,
            status=SubscriptionStatus.ACTIVE,
            plan__is_trial=False,
        )
        .exists()
    )
    if already_paid:
        raise TrialConversionError(
            "This customer already has an active paid subscription."
        )

    before = list(
        OrganizationSubscription.objects.filter(
            organization=organization, status__in=tuple(USABLE_STATUSES)
        ).values("id", "status", "plan__code")
    )

    # Delegate. create_pending_paid_subscription + activate_subscription is the
    # same pair the payment webhook uses; activate_subscription supersedes any
    # existing usable subscription and is row-locked and idempotent.
    from apps.billing.services.subscription_service import SubscriptionService

    service = SubscriptionService()
    subscription = service.create_pending_paid_subscription(organization, plan)
    subscription = service.activate_subscription(subscription)

    log_crm_action(
        actor=actor,
        organization=organization,
        action_type=ACTION_TYPE,
        resource_type="organization_subscription",
        resource_id=str(subscription.id),
        reason="Converted from trial via Trial Users Dashboard.",
        old_value={"subscriptions": [
            {**row, "id": str(row["id"])} for row in before
        ]},
        new_value={
            "subscription_id": str(subscription.id),
            "plan": plan.code,
            "status": subscription.status,
            "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None,
        },
        metadata={
            "trial_lead_profile_id": str(profile.id),
            "user_email": profile.user.email,
            # No payment was taken — this is an operator action, and the audit
            # trail must not imply otherwise.
            "payment_taken": False,
        },
        ip_address=_client_ip(request),
    )

    logger.info(
        "Trial converted: org=%s plan=%s sub=%s actor=%s",
        organization.pk, plan.code, subscription.pk, getattr(actor, "pk", None),
    )
    return subscription


def _client_ip(request):
    if request is None:
        return None
    from core.utils.coerce import get_client_ip

    return get_client_ip(request) or None
