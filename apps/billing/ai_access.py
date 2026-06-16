"""Unified AI cost-access guard (PAY-HARDEN-1).

Why this exists — defense in depth
-----------------------------------
``SubscriptionRequiredMiddleware`` blocks unsubscribed / suspended org users at
the HTTP edge, but it is NOT sufficient on its own to protect paid OpenAI spend:

  * background tasks / Celery jobs / management commands have no ``request`` and
    never pass through middleware;
  * an org with an ACTIVE subscription can still have exhausted its daily AI
    token budget — middleware only checks "is there a usable subscription";
  * a deployment running with ``SUBSCRIPTION_REQUIRED=False`` (a migration
    window) drops the middleware wall entirely.

So any code path that is about to spend money on OpenAI MUST call this guard
first, regardless of whether middleware also guards the same route.

Quota vs budget — two different meters
--------------------------------------
  * **invoice quota** = per-subscription invoice-audit units, consumed by the
    audit pipeline via ``billing.quota_gate``. This guard deliberately does NOT
    consume or block on invoice quota — viewing analytics on already-ingested
    data is not an invoice audit.
  * **AI token budget** = per-org daily OpenAI token cap
    (``core.services.ai_budget``). This is the cost ceiling for *all* AI
    features, and is what this guard enforces.

Suspension and token-budget are enforced ALWAYS (independent of
``SUBSCRIPTION_REQUIRED``) so disabling the subscription wall during a migration
window can never silently open the AI cost faucet. The subscription-validity
check is gated by ``SUBSCRIPTION_REQUIRED`` to stay consistent with middleware,
and the whole guard can be disabled with ``AI_ACCESS_GUARD_ENABLED=False`` as an
explicit, separate emergency switch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from apps.billing.models import OrganizationSubscription
from apps.billing.services.quota_service import QuotaService
from core.services import ai_budget

logger = logging.getLogger("billing.ai_access")


# Decision code → suggested HTTP status. 402 Payment Required for billing,
# 403 for suspension, 429 Too Many Requests for budget exhaustion.
_CODE_HTTP = {
    "no_organization": 400,
    "organization_suspended": 403,
    "no_subscription": 402,
    "subscription_expired": 402,
    "ai_budget_exhausted": 429,
}

_CODE_MESSAGE = {
    "no_organization": "User has no organization.",
    "organization_suspended": "Your account is suspended. Please contact support.",
    "no_subscription": "An active subscription is required to use AI features.",
    "subscription_expired": "Your subscription has expired. Please renew to continue.",
    "ai_budget_exhausted": "Daily AI usage budget exhausted. Please try again later.",
}


@dataclass(frozen=True)
class AIAccessDecision:
    """Result of an access check. ``allowed`` is the only field callers must
    branch on; ``code``/``message``/``http_status`` describe a denial."""

    allowed: bool
    code: str = ""
    message: str = ""
    http_status: int = 200


class AIAccessDenied(Exception):
    """Raised by :func:`require_ai_access`. Carries the decision so service /
    task callers can log a safe reason without re-deriving it."""

    def __init__(self, decision: AIAccessDecision):
        self.decision = decision
        super().__init__(decision.message or decision.code or "ai_access_denied")


def _guard_enabled() -> bool:
    return getattr(settings, "AI_ACCESS_GUARD_ENABLED", True)


def _subscription_required() -> bool:
    return getattr(settings, "SUBSCRIPTION_REQUIRED", True)


def _deny(code: str) -> AIAccessDecision:
    return AIAccessDecision(
        allowed=False,
        code=code,
        message=_CODE_MESSAGE.get(code, code),
        http_status=_CODE_HTTP.get(code, 402),
    )


def check_ai_access(organization, *, projected_tokens: int = 0) -> AIAccessDecision:
    """Decide whether ``organization`` may trigger a paid AI call. Never raises.

    Order of checks: guard enabled → org present → not suspended →
    (subscription usable, if required) → AI token budget. The first failing
    check wins. Invoice-quota exhaustion is intentionally NOT a blocker here
    (see module docstring).
    """
    if not _guard_enabled():
        return AIAccessDecision(allowed=True)

    if organization is None:
        return _deny("no_organization")

    # Suspension — always enforced, even if the subscription wall is off.
    if not getattr(organization, "is_active", False):
        return _deny("organization_suspended")

    # Subscription validity — same source of truth middleware uses.
    if _subscription_required():
        sub = QuotaService().get_active_subscription(organization)
        if sub is None:
            has_history = OrganizationSubscription.objects.filter(
                organization=organization,
            ).exists()
            return _deny("subscription_expired" if has_history else "no_subscription")

    # AI token budget — always enforced (the real per-org cost ceiling).
    org_id = getattr(organization, "id", None)
    if ai_budget.is_over_budget(org_id, projected_tokens):
        return _deny("ai_budget_exhausted")

    return AIAccessDecision(allowed=True)


def ai_access_allowed(organization, *, projected_tokens: int = 0) -> bool:
    """Boolean convenience for loops / background tasks."""
    return check_ai_access(organization, projected_tokens=projected_tokens).allowed


def require_ai_access(organization, *, projected_tokens: int = 0) -> AIAccessDecision:
    """Raise :class:`AIAccessDenied` if access is not allowed; else return the
    (allowed) decision. For services that prefer exceptions over branching."""
    decision = check_ai_access(organization, projected_tokens=projected_tokens)
    if not decision.allowed:
        raise AIAccessDenied(decision)
    return decision


def ai_access_response_or_none(organization, *, projected_tokens: int = 0):
    """DRF helper for views: return a ``Response`` (402/403/429) when access is
    denied, or ``None`` when the caller may proceed. Keeps view edits to three
    lines and guarantees the OpenAI call is never reached on denial."""
    decision = check_ai_access(organization, projected_tokens=projected_tokens)
    if decision.allowed:
        return None
    from rest_framework.response import Response

    logger.info(
        "[ai_access] blocked org=%s code=%s",
        getattr(organization, "id", None),
        decision.code,
    )
    return Response(
        {
            "detail": decision.message,
            "code": decision.code,
            "redirect": "/billing/plans/",
        },
        status=decision.http_status,
    )
