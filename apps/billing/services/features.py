"""Central commercial feature entitlements.

All package-gated surfaces resolve their capability through this module instead of
re-implementing plan-code comparisons in views.  A subscription snapshots the
plan's capabilities at purchase/activation so later catalogue edits never alter
an existing customer's contracted access.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.billing.choices import SubscriptionStatus


class FeatureUnavailable(PermissionError):
    """Raised when an organisation's active package does not include a feature."""


@dataclass(frozen=True)
class CapabilityDecision:
    feature: str
    tier: str | None
    enabled: bool
    source: str


def _usable_subscription(organization):
    """Return the current subscription or ``None`` without guessing a plan."""
    return (
        organization.subscriptions.select_related("plan")
        .filter(status__in=(SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING))
        .order_by("-starts_at", "-created_at")
        .first()
    )


def capabilities_for_subscription(subscription) -> dict[str, Any]:
    """Return the frozen commercial contract for a subscription.

    Legacy subscriptions created before the snapshot field intentionally fall
    back to the current Plan policy.  This is explicit in ``source`` at callers
    and must be backfilled before the catalogue becomes customer-editable.
    """
    if subscription is None:
        return {}
    snapshot = subscription.feature_tiers_snapshot
    if snapshot is not None:
        return dict(snapshot)
    return dict(subscription.plan.feature_tiers or {})


def capabilities_for_organization(organization) -> dict[str, Any]:
    return capabilities_for_subscription(_usable_subscription(organization))


def feature_decision(organization, feature: str, *, minimum_tier: str | None = None) -> CapabilityDecision:
    """Resolve one feature with an optional minimum tier.

    Boolean features use ``True``. Tiered features use a non-empty string;
    callers may require a concrete tier when they need more than availability.
    """
    subscription = _usable_subscription(organization)
    if subscription is None:
        return CapabilityDecision(feature, None, False, "no_subscription")

    capabilities = capabilities_for_subscription(subscription)
    value = capabilities.get(feature)
    enabled = bool(value)
    if minimum_tier is not None:
        enabled = value == minimum_tier
    source = "subscription_snapshot" if subscription.feature_tiers_snapshot is not None else "legacy_plan_policy"
    return CapabilityDecision(feature, value if isinstance(value, str) else None, enabled, source)


def require_feature(organization, feature: str, *, minimum_tier: str | None = None) -> CapabilityDecision:
    decision = feature_decision(organization, feature, minimum_tier=minimum_tier)
    if not decision.enabled:
        raise FeatureUnavailable(f"Feature '{feature}' is not included in the active package.")
    return decision
