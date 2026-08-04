"""A billing fault must not render as a missing feature.

On production, unapplied migrations made `get_active_subscription` raise. The
context processor answered every exception with the same empty namespace it
uses for logged-out visitors — and that namespace carries
`show_billing_nav=False`. The «الفوترة والاشتراك» menu simply vanished: no
error page, no banner, nothing in the UI to suggest a fault. Hours went into
looking for a permissions bug in the navigation code.

The tests below pin the distinction that was missing: whether the menu may be
shown is a question about the user's *role*, and it must survive a query that
fails. The first test fails against the old implementation — that is the point
of it.
"""

from types import SimpleNamespace
from unittest import mock

import pytest
from django.db import DatabaseError
from django.test import override_settings

from apps.billing import context_processors


def _request(user):
    return SimpleNamespace(user=user)


@pytest.fixture
def broken_quota_service():
    """QuotaService that fails the way unapplied migrations fail."""
    with mock.patch(
        "apps.billing.services.quota_service.QuotaService.get_active_subscription",
        side_effect=DatabaseError("(1054, \"Unknown column 'user_limit' in 'field list'\")"),
    ) as patched:
        yield patched


# ── The regression itself ─────────────────────────────────────────────────────

@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_billing_menu_survives_a_database_fault(admin_user, broken_quota_service):
    """THE regression. Old code returned show_billing_nav=False here."""
    context = context_processors.billing(_request(admin_user))
    assert context["billing"].show_billing_nav is True


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_a_fault_is_marked_degraded_so_the_page_can_say_so(admin_user, broken_quota_service):
    assert context_processors.billing(_request(admin_user))["billing"].degraded is True


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_a_fault_is_logged_with_a_traceback_and_the_organisation(admin_user, broken_quota_service, caplog):
    with caplog.at_level("ERROR", logger="billing.context"):
        context_processors.billing(_request(admin_user))
    records = [r for r in caplog.records if r.name == "billing.context"]
    assert records, "a billing fault produced no ERROR log"
    assert records[0].exc_info is not None, "logged without a traceback — undiagnosable"
    assert "NOT real" in records[0].getMessage()


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_the_same_fault_is_raised_in_development(admin_user, broken_quota_service):
    """Degrading is a production concession. A developer must see the crash."""
    with pytest.raises(DatabaseError):
        context_processors.billing(_request(admin_user))


# ── The degraded figures must not be mistaken for real ones ──────────────────

@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_degraded_context_claims_no_subscription_and_no_quota(admin_user, broken_quota_service):
    billing = context_processors.billing(_request(admin_user))["billing"]
    assert billing.has_subscription is False
    assert billing.usage_percent == 0
    assert billing.plan_name == ""


# ── The states that are NOT faults keep their old behaviour ──────────────────

@pytest.mark.django_db
def test_anonymous_visitors_get_no_billing_nav_and_are_not_degraded():
    from django.contrib.auth.models import AnonymousUser

    billing = context_processors.billing(_request(AnonymousUser()))["billing"]
    assert billing.show_billing_nav is False
    assert billing.degraded is False


@pytest.mark.django_db
def test_a_user_without_an_organisation_is_not_a_fault(admin_user):
    admin_user.organization = None
    billing = context_processors.billing(_request(admin_user))["billing"]
    assert billing.show_billing_nav is False
    assert billing.degraded is False


@pytest.mark.django_db
def test_an_auditor_without_billing_rights_still_sees_no_menu(auditor_user):
    """Role gating is unchanged — the fix must not hand the menu to everyone."""
    billing = context_processors.billing(_request(auditor_user))["billing"]
    assert billing.show_billing_nav is False


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_role_gating_still_applies_when_the_query_fails(auditor_user, broken_quota_service):
    """Degrading must not become a privilege-escalation path."""
    billing = context_processors.billing(_request(auditor_user))["billing"]
    assert billing.show_billing_nav is False
    assert billing.degraded is True


@pytest.mark.django_db
def test_healthy_path_is_not_degraded(admin_user):
    billing = context_processors.billing(_request(admin_user))["billing"]
    assert billing.degraded is False


# ── The context processor is a returned-shape contract ───────────────────────

@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_every_path_returns_the_same_attributes(admin_user, auditor_user):
    """A template reading billing.X must not hit AttributeError on some paths.

    The refactor split the builder out of the entry point; a field added to one
    branch and forgotten in another would only surface as a broken page.
    """
    from django.contrib.auth.models import AnonymousUser

    shapes = []
    shapes.append(set(vars(context_processors.billing(_request(AnonymousUser()))["billing"])))
    shapes.append(set(vars(context_processors.billing(_request(admin_user))["billing"])))
    with mock.patch(
        "apps.billing.services.quota_service.QuotaService.get_active_subscription",
        side_effect=DatabaseError("boom"),
    ):
        shapes.append(set(vars(context_processors.billing(_request(admin_user))["billing"])))

    assert shapes[0] == shapes[1] == shapes[2], (
        "billing context shape differs between paths: "
        f"{shapes[0] ^ shapes[1] ^ shapes[2]}"
    )
