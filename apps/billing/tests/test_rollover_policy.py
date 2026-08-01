"""Rollover policy: both behaviours, and the flip that must not destroy credit.

MONEY RULE 2 — never retroactively remove quota a customer paid for — is what
makes this the most dangerous behaviour in the phase. Carry-over is the shipped
default, so a customer can accrue credit under it; switching the platform to
"expire" must apply to future cycles and must not reach back and delete what
they already hold.

That is the test this file exists for. The rest establish that both behaviours
actually work, because a switch between two options where one is unimplemented
is not a switch.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalogue(db):
    call_command("seed_billing_plans", stdout=StringIO())
    call_command("seed_addons", stdout=StringIO())


def _staff():
    from apps.authentication.models import User

    return User.objects.create_user(
        username="policyops", email="policyops@tadgeeg.test",
        password="x", is_staff=True,
    )


def _sub_with_credit(name, *, used_units=300):
    """An active subscription holding a partly-used 1,000-invoice pack."""
    from apps.authentication.models import Organization
    from apps.billing.models import Addon, Plan
    from apps.billing.services.addon_service import AddonService
    from apps.billing.services.subscription_service import SubscriptionService

    org = Organization.objects.create(name=name)
    svc = SubscriptionService()
    sub = svc.activate_subscription(
        svc.create_pending_paid_subscription(org, Plan.objects.get(code="business"))
    )
    sa = AddonService().purchase(sub, Addon.objects.get(code="invoice_pack_1000"))
    sa.used_units = used_units
    sa.save(update_fields=["used_units"])
    return sub, sa


# ── the default ──────────────────────────────────────────────────────────────

def test_carry_over_is_the_shipped_default(catalogue):
    from apps.billing.choices import RolloverPolicy
    from apps.billing.services.rollover import RolloverService

    policy = RolloverService().get_policy()
    assert policy.invoice_credit_rollover == RolloverPolicy.CARRY_OVER
    assert RolloverService().carry_over_enabled() is True


# ── behaviour A ──────────────────────────────────────────────────────────────

def test_rollover_a_unused_credit_survives_a_cycle_reset(catalogue):
    """Bought 1,000, used 300 → 700 remains."""
    from apps.billing.services.rollover import RolloverService

    sub, sa = _sub_with_credit("Carry Co", used_units=300)
    assert sa.remaining_units == 700

    RolloverService().apply_cycle_reset(sub)

    sa.refresh_from_db()
    assert sa.is_active is True, "credit was dropped under carry-over"
    assert sa.remaining_units == 700


# ── behaviour B ──────────────────────────────────────────────────────────────

def test_rollover_b_unused_credit_is_dropped_at_reset(catalogue):
    from apps.billing.choices import RolloverPolicy
    from apps.billing.services.rollover import RolloverService

    svc = RolloverService()
    svc.set_policy(value=RolloverPolicy.EXPIRE, actor=_staff())

    sub, sa = _sub_with_credit("Expire Co", used_units=300)
    assert sa.remaining_units == 700

    svc.apply_cycle_reset(sub)

    sa.refresh_from_db()
    assert sa.is_active is False, "credit survived under the expire policy"


# ── THE test ─────────────────────────────────────────────────────────────────

def test_flipping_the_policy_does_not_delete_credit_already_accrued(catalogue):
    """MONEY RULE 2, directly.

    A customer buys credit while carry-over is on and holds unused units. The
    platform then switches to expire. The switch must apply to future cycles —
    it must not reach back and remove what they already paid for and hold.
    """
    from apps.billing.choices import RolloverPolicy
    from apps.billing.services.entitlements import effective_invoice_quota
    from apps.billing.services.rollover import RolloverService

    svc = RolloverService()
    assert svc.carry_over_enabled() is True

    sub, sa = _sub_with_credit("Accrued Co", used_units=300)
    ceiling_before = effective_invoice_quota(sub).total
    assert ceiling_before == 3000                      # 2,000 plan + 1,000 pack

    # The platform changes its mind.
    svc.set_policy(value=RolloverPolicy.EXPIRE, actor=_staff(),
                   reason="switching to expiry")

    sa.refresh_from_db()
    assert sa.is_active is True, (
        "changing the policy deleted credit the customer had already paid for"
    )
    assert sa.remaining_units == 700
    assert effective_invoice_quota(sub).total == ceiling_before, (
        "the effective ceiling dropped the moment the policy changed"
    )


def test_the_new_policy_does_apply_at_the_next_reset(catalogue):
    """The other half: the switch is not a no-op, it just is not retroactive."""
    from apps.billing.choices import RolloverPolicy
    from apps.billing.services.rollover import RolloverService

    svc = RolloverService()
    sub, sa = _sub_with_credit("Future Co", used_units=300)
    svc.set_policy(value=RolloverPolicy.EXPIRE, actor=_staff())

    sa.refresh_from_db()
    assert sa.is_active is True                        # not retroactive…

    svc.apply_cycle_reset(sub)
    sa.refresh_from_db()
    assert sa.is_active is False                       # …but it does take effect


# ── the switch itself ────────────────────────────────────────────────────────

def test_a_policy_change_is_audited(catalogue):
    """Changing how paid credit behaves must be attributable.

    Written to the existing hash-chained ``authentication.AuditLog`` through
    ``log_crm_action`` — the same single writer every other privileged action
    uses, so there is one chain and not two.
    """
    from apps.authentication.models import AuditLog
    from apps.billing.choices import RolloverPolicy
    from apps.billing.services.rollover import RolloverService

    staff = _staff()
    before = AuditLog.objects.count()
    RolloverService().set_policy(
        value=RolloverPolicy.EXPIRE, actor=staff, reason="ops decision",
    )
    assert AuditLog.objects.count() > before, "no audit entry was written"

    entry = AuditLog.objects.order_by("-timestamp").first()
    assert entry.resource_type == "BillingPolicy"
    assert entry.user_id == staff.pk, "the change is not attributable to anyone"
    # The verb and both values live in `details`; the model's own Action enum
    # is deliberately not extended (see crm_audit).
    blob = str(entry.details)
    assert "billing_policy_changed" in blob
    assert "carry_over" in blob and "expire" in blob


def test_the_policy_records_who_changed_it_and_when(catalogue):
    from apps.billing.choices import RolloverPolicy
    from apps.billing.services.rollover import RolloverService

    staff = _staff()
    policy = RolloverService().set_policy(value=RolloverPolicy.EXPIRE, actor=staff)
    assert policy.updated_by_id == staff.pk
    assert policy.effective_from is not None


def test_an_unknown_policy_value_is_refused(catalogue):
    from apps.billing.services.rollover import RolloverService

    with pytest.raises(ValueError):
        RolloverService().set_policy(value="delete_everything", actor=_staff())


def test_the_policy_is_a_singleton(catalogue):
    from apps.billing.models import BillingPolicy
    from apps.billing.services.rollover import RolloverService

    RolloverService().get_policy()
    BillingPolicy(invoice_credit_rollover="expire").save()
    assert BillingPolicy.objects.count() == 1, (
        "a second policy row exists; two rows can disagree about what is in force"
    )


def test_the_policy_does_not_live_in_the_cms_settings_table():
    """ADR 0001's lesson: a billing behaviour in the CMS table is a second
    source of truth, and PlatformSetting is publicly readable by design."""
    from apps.billing.models import BillingPolicy

    assert BillingPolicy._meta.app_label == "billing"
    assert not hasattr(BillingPolicy, "is_public")


# ── the admin endpoint ───────────────────────────────────────────────────────

POLICY_URL = "/api/platform-admin/billing-policy/"


@pytest.mark.django_db
class TestBillingPolicyEndpointPermissions:
    """Rule 2: no middleware fronts /api/platform-admin/, so every endpoint
    ships with its own permission test in the same change."""

    def _org_admin(self):
        """An org admin WITH an active subscription.

        The subscription matters: without one, SubscriptionRequiredMiddleware
        answers 402 first and the request never reaches the permission class.
        That would still refuse the user, but it would not prove the endpoint
        is guarded — only that the paywall is. Giving them a live subscription
        forces the refusal to come from IsPlatformAdmin.
        """
        from apps.authentication.models import Organization, User
        from apps.billing.models import Plan
        from apps.billing.services.subscription_service import SubscriptionService

        org = Organization.objects.create(name="Tenant Co")
        svc = SubscriptionService()
        svc.activate_subscription(
            svc.create_pending_paid_subscription(org, Plan.objects.get(code="business"))
        )
        return User.objects.create_user(
            username="orgadmin", email="orgadmin@tenant.co", password="x",
            organization=org, role="admin", is_staff=False,
        )

    def test_anonymous_is_refused(self, client):
        assert client.get(POLICY_URL).status_code in (401, 403)

    def test_an_org_admin_is_refused(self, client, catalogue):
        """`role="admin"` is an organisation role every registrant holds. It is
        not platform authority, and this is the exact confusion 0-A fixed."""
        client.force_login(self._org_admin())
        assert client.get(POLICY_URL).status_code == 403
        assert client.patch(
            POLICY_URL, {"invoice_credit_rollover": "expire"},
            content_type="application/json",
        ).status_code == 403

    def test_staff_can_read_and_change(self, client, catalogue):
        from apps.billing.services.rollover import RolloverService

        client.force_login(_staff())
        assert client.get(POLICY_URL).status_code == 200

        resp = client.patch(
            POLICY_URL, {"invoice_credit_rollover": "expire", "reason": "ops"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert RolloverService().carry_over_enabled() is False

    def test_an_invalid_value_is_refused(self, client, catalogue):
        client.force_login(_staff())
        resp = client.patch(
            POLICY_URL, {"invoice_credit_rollover": "nonsense"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_the_policy_is_not_exposed_on_any_public_surface(self, client, catalogue):
        """A billing policy must never be publicly readable."""
        for url in ("/pricing/", "/billing/plans/"):
            body = client.get(url).content.decode()
            assert "invoice_credit_rollover" not in body
