"""Read-only aggregation for the Trial Users Dashboard (spec §B).

Two rules shape everything here.

**No new source of truth.** Trial state is derived from
``OrganizationSubscription`` on every read (ADR 0002). Nothing in this module
writes, and no status is stored anywhere.

**Aggregate in the database.** Every metric is a ``GROUP BY`` or a ``COUNT``.
Nothing pulls a queryset into Python to bucket it, because the trial table is
the one guaranteed to grow with marketing spend.

The dashboard population is *trial-lead registrants* — one row per
``TrialLeadProfile`` — not "rows that currently have a trialing subscription".
Selecting a plan is a separate, later step (``/billing/plans/``), so a large
share of registrants have no subscription at all. Excluding them would hide
exactly the drop-off the dashboard exists to show.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import (
    Case,
    Count,
    Exists,
    OuterRef,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.billing.choices import SubscriptionStatus
from apps.billing.models import OrganizationSubscription

from .models import TrialLeadProfile


# ── activity thresholds (decision D3) ────────────────────────────────────────
ACTIVE_LOGIN_DAYS = 7
IDLE_LOGIN_DAYS = 14


class TrialStatus:
    """Derived, reporting-only labels. Deliberately NOT a models.TextChoices —
    these are not stored anywhere and must not look like they could be."""

    TRIALING = "trialing"
    EXPIRED = "expired"
    PAID = "paid"
    NO_SUBSCRIPTION = "no_subscription"

    CHOICES = (TRIALING, EXPIRED, PAID, NO_SUBSCRIPTION)


class ActivityBucket:
    ACTIVE = "active"
    IDLE = "idle"
    NEVER_STARTED = "never_started"

    CHOICES = (ACTIVE, IDLE, NEVER_STARTED)


def _subscription_exists(**filters):
    return Exists(
        OrganizationSubscription.objects.filter(
            organization_id=OuterRef("user__organization_id"), **filters
        )
    )


def base_queryset():
    """All trial-lead registrants, annotated with derived state.

    Annotations, all computed in SQL:

    ``has_trialing`` / ``has_expired_trial`` / ``has_paid``
        Presence of the corresponding subscription for the registrant's
        organisation. ``paid`` is an ACTIVE subscription on a non-trial plan,
        per ADR 0002.

    ``invoices_used``
        Summed across the organisation's subscriptions. A converted trial is
        superseded (set to CANCELED) rather than deleted, so looking only at
        the current subscription would report zero usage for exactly the
        customers who used the product most.
    """
    return (
        TrialLeadProfile.objects.select_related("user", "user__organization")
        .annotate(
            has_trialing=_subscription_exists(status=SubscriptionStatus.TRIALING),
            has_expired_trial=_subscription_exists(
                status=SubscriptionStatus.EXPIRED, plan__is_trial=True
            ),
            has_paid=_subscription_exists(
                status=SubscriptionStatus.ACTIVE, plan__is_trial=False
            ),
            invoices_used=Coalesce(
                Sum("user__organization__subscriptions__used_invoices"), Value(0)
            ),
        )
        .annotate(
            trial_status=Case(
                # Order matters: a converted customer is "paid" even though the
                # superseded trial row still exists.
                When(has_paid=True, then=Value(TrialStatus.PAID)),
                When(has_trialing=True, then=Value(TrialStatus.TRIALING)),
                When(has_expired_trial=True, then=Value(TrialStatus.EXPIRED)),
                default=Value(TrialStatus.NO_SUBSCRIPTION),
            )
        )
    )


def annotate_activity(queryset, *, now=None):
    """Bucket registrants by engagement (decision D3).

    ``now`` is injected rather than read from the clock inside the query so
    tests can pin it. Two tests in this repo already flake for want of that.

    | bucket | rule |
    |---|---|
    | ``active`` | logged in within 7 days AND processed ≥1 invoice |
    | ``idle`` | logged in at some point, but no invoices or no login in 14 days |
    | ``never_started`` | never logged in |

    Note on ``never_started``: D3 phrases it as "verified but never logged in".
    Verification without a login is indistinguishable here from registering and
    never verifying — both have ``last_login IS NULL`` — so the bucket holds
    both. That is the honest reading: neither has started using the product.
    """
    now = now or timezone.now()
    active_since = now - timedelta(days=ACTIVE_LOGIN_DAYS)
    idle_since = now - timedelta(days=IDLE_LOGIN_DAYS)

    return queryset.annotate(
        activity=Case(
            When(user__last_login__isnull=True, then=Value(ActivityBucket.NEVER_STARTED)),
            When(
                Q(user__last_login__gte=active_since) & Q(invoices_used__gt=0),
                then=Value(ActivityBucket.ACTIVE),
            ),
            When(user__last_login__lt=idle_since, then=Value(ActivityBucket.IDLE)),
            # Logged in recently but never processed an invoice.
            default=Value(ActivityBucket.IDLE),
        )
    )


def apply_filters(queryset, *, country=None, primary_benefit=None,
                  trial_status=None, activity=None,
                  registered_from=None, registered_to=None):
    """Apply dashboard filters. Every value is validated against a known set —
    an unrecognised value is ignored rather than passed to the ORM.

    Exports call this with the same arguments as the dashboard, which is what
    makes "the export respects the active filters" true by construction rather
    than by remembering to keep two code paths in step.
    """
    if country and country in dict(_country_choices()):
        queryset = queryset.filter(country=country)
    if primary_benefit and primary_benefit in TrialLeadProfile.PrimaryBenefit.values:
        queryset = queryset.filter(primary_benefit=primary_benefit)
    if trial_status and trial_status in TrialStatus.CHOICES:
        queryset = queryset.filter(trial_status=trial_status)
    if activity and activity in ActivityBucket.CHOICES:
        queryset = queryset.filter(activity=activity)
    if registered_from:
        queryset = queryset.filter(created_at__date__gte=registered_from)
    if registered_to:
        queryset = queryset.filter(created_at__date__lte=registered_to)
    return queryset


def _country_choices():
    from apps.authentication.models import Organization

    return Organization.Country.choices


def _group_count(queryset, field):
    """``[{"value": ..., "count": n}]``, ordered biggest first, in one query."""
    return [
        {"value": row[field] or "", "count": row["count"]}
        for row in queryset.values(field).annotate(count=Count("id")).order_by("-count")
    ]


def build_summary(queryset):
    """The six dashboard cards (§B.1). One query per card, none of them O(rows)
    in Python."""
    by_date = [
        {"value": row["day"].isoformat() if row["day"] else "", "count": row["count"]}
        for row in queryset.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("-day")[:30]
    ]

    return {
        "total": queryset.count(),
        "by_country": _group_count(queryset, "country"),
        "by_client_type": _group_count(queryset, "primary_benefit"),
        "by_activity": _group_count(queryset, "activity"),
        "by_registration_date": by_date,
        "by_trial_status": _group_count(queryset, "trial_status"),
        "expired_trials": queryset.filter(trial_status=TrialStatus.EXPIRED).count(),
        "converted": queryset.filter(trial_status=TrialStatus.PAID).count(),
    }


def get_dashboard_queryset(*, now=None, **filters):
    """Base + activity + filters, in the order the annotations require."""
    qs = annotate_activity(base_queryset(), now=now)
    return apply_filters(qs, **filters)


def row_values(profile):
    """Flatten one annotated row for list/export rendering.

    ``registered_ip`` is deliberately absent — ADR 0004 §2 keeps it out of
    every dashboard and export payload. It is reachable only through Django
    admin, by staff, one record at a time.
    """
    user = profile.user
    org = getattr(user, "organization", None)
    return {
        "id": str(profile.id),
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "organization": getattr(org, "name", ""),
        # str() because CountryField returns a Country object, which neither
        # openpyxl nor the JSON encoder can serialise. Coerced once here, at the
        # single boundary every consumer (API, Excel, PDF) already passes
        # through, rather than in each of them.
        "country": str(profile.country or ""),
        "city": profile.city,
        "company_name": profile.company_name,
        "primary_benefit": profile.primary_benefit,
        "employee_count": profile.employee_count,
        "sector": profile.sector,
        "heard_about": profile.heard_about,
        "trial_status": getattr(profile, "trial_status", ""),
        "activity": getattr(profile, "activity", ""),
        "invoices_used": getattr(profile, "invoices_used", 0),
        "registered_at": profile.created_at.isoformat() if profile.created_at else "",
        "last_login": user.last_login.isoformat() if user.last_login else "",
    }
