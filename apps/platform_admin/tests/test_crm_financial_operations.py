"""CRM-1F-1B — Extend Subscription wrapper + form + view (financial ops)."""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.authentication.models import AuditLog, Organization
from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.payments.models import PaymentTransaction
from apps.platform_admin import forms as crm_forms
from apps.platform_admin.models import CustomerActivity
from apps.platform_admin.services import crm_operations as ops

pytestmark = pytest.mark.django_db


_PLAN_SEQ = {"n": 0}


def _subscription(organization, status=SubscriptionStatus.ACTIVE, ends_at=None):
    _PLAN_SEQ["n"] += 1
    plan = Plan.objects.create(
        code=PlanCode.STARTER, name_ar="ستارتر", name_en=f"Starter {_PLAN_SEQ['n']}",
        invoice_limit=100, price="50.00",
    )
    now = timezone.now()
    return OrganizationSubscription.objects.create(
        organization=organization, plan=plan, status=status,
        invoice_limit=100, used_invoices=10, reserved_invoices=5,
        starts_at=now, ends_at=ends_at or (now + timedelta(days=30)),
    )


# ══ Service wrapper tests ═════════════════════════════════════════════════════
def test_owner_can_extend(organization, owner_user):
    sub = _subscription(organization)
    before = sub.ends_at
    out = ops.crm_extend_subscription(
        actor=owner_user, organization=organization, subscription=sub,
        days=15, reason="goodwill",
    )
    assert out.ends_at == before + timedelta(days=15)


def test_finance_can_extend_and_writes_audit_and_activity(organization, finance_user):
    sub = _subscription(organization)
    before = sub.ends_at
    ops.crm_extend_subscription(
        actor=finance_user, organization=organization, subscription=sub,
        days=10, reason="paid offline",
    )
    audit = AuditLog.objects.filter(
        resource_id=str(sub.id), details__action_type="subscription_extended"
    ).latest("timestamp")
    assert audit.details["reason"] == "paid offline"
    assert audit.details["old_value"]["ends_at"] == before.isoformat()
    assert audit.details["new_value"]["days"] == 10
    assert CustomerActivity.objects.filter(
        organization=organization, activity_type="subscription_extended"
    ).exists()


@pytest.mark.parametrize("role", ["support_user", "readonly_user", "admin_user", "staff_no_group"])
def test_non_financial_managers_cannot_extend(request, organization, role):
    actor = request.getfixturevalue(role)
    sub = _subscription(organization)
    with pytest.raises(PermissionDenied):
        ops.crm_extend_subscription(
            actor=actor, organization=organization, subscription=sub,
            days=5, reason="x",
        )


def test_reason_required(organization, finance_user):
    sub = _subscription(organization)
    with pytest.raises(ValidationError):
        ops.crm_extend_subscription(
            actor=finance_user, organization=organization, subscription=sub,
            days=5, reason="   ",
        )


@pytest.mark.parametrize("days", [0, -3, "10", True])
def test_invalid_days_rejected(organization, finance_user, days):
    sub = _subscription(organization)
    with pytest.raises(ValidationError):
        ops.crm_extend_subscription(
            actor=finance_user, organization=organization, subscription=sub,
            days=days, reason="x",
        )


def test_subscription_must_belong_to_organization(organization, finance_user):
    other = Organization.objects.create(
        name="Other", country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR,
    )
    sub_other = _subscription(other)
    with pytest.raises(ValidationError):
        ops.crm_extend_subscription(
            actor=finance_user, organization=organization, subscription=sub_other,
            days=5, reason="x",
        )


def test_delegates_to_official_billing_service(organization, finance_user):
    sub = _subscription(organization)
    with patch(
        "apps.billing.services.subscription_service.SubscriptionService.extend_subscription",
        autospec=True,
    ) as mock_ext:
        mock_ext.return_value = sub  # has a real ends_at for the audit payload
        ops.crm_extend_subscription(
            actor=finance_user, organization=organization, subscription=sub,
            days=12, reason="x",
        )
    assert mock_ext.called
    _, kwargs = mock_ext.call_args
    assert kwargs["days"] == 12
    assert kwargs["reason"] == "x"


def test_no_payment_transaction_created(organization, finance_user):
    sub = _subscription(organization)
    before = PaymentTransaction.objects.count()
    ops.crm_extend_subscription(
        actor=finance_user, organization=organization, subscription=sub,
        days=5, reason="x",
    )
    assert PaymentTransaction.objects.count() == before


def test_only_ends_at_changes(organization, finance_user):
    sub = _subscription(organization)
    snap = (sub.plan_id, sub.status, sub.invoice_limit, sub.used_invoices,
            sub.reserved_invoices, sub.payment_transaction_id, sub.starts_at)
    ops.crm_extend_subscription(
        actor=finance_user, organization=organization, subscription=sub,
        days=20, reason="x",
    )
    fresh = OrganizationSubscription.objects.get(pk=sub.pk)
    assert (fresh.plan_id, fresh.status, fresh.invoice_limit, fresh.used_invoices,
            fresh.reserved_invoices, fresh.payment_transaction_id, fresh.starts_at) == snap


# ══ Form tests ════════════════════════════════════════════════════════════════
def test_form_valid():
    assert crm_forms.ExtendSubscriptionForm(data={"days": 30, "reason": "ok"}).is_valid()


@pytest.mark.parametrize("days", [0, -1, 731])
def test_form_invalid_days(days):
    f = crm_forms.ExtendSubscriptionForm(data={"days": days, "reason": "ok"})
    assert not f.is_valid()
    assert "days" in f.errors


def test_form_blank_reason_invalid():
    f = crm_forms.ExtendSubscriptionForm(data={"days": 30, "reason": "  "})
    assert not f.is_valid()
    assert "reason" in f.errors


# ══ View tests ════════════════════════════════════════════════════════════════
def _extend_url(org, sub):
    return reverse("platform_admin:crm:subscription_extend", args=[org.id, sub.id])


def test_view_finance_extends_and_redirects(client, finance_user, organization):
    sub = _subscription(organization)
    before = sub.ends_at
    client.force_login(finance_user)
    resp = client.post(_extend_url(organization, sub), {"days": 14, "reason": "ok"})
    assert resp.status_code == 302
    assert resp["Location"] == reverse(
        "platform_admin:crm:customer_detail", args=[organization.id]
    )
    sub.refresh_from_db()
    assert sub.ends_at == before + timedelta(days=14)


def test_view_owner_can_extend(client, owner_user, organization):
    sub = _subscription(organization)
    client.force_login(owner_user)
    assert client.post(_extend_url(organization, sub), {"days": 5, "reason": "ok"}).status_code == 302


@pytest.mark.parametrize("role", ["support_user", "readonly_user", "admin_user"])
def test_view_forbidden_roles(client, request, organization, role):
    actor = request.getfixturevalue(role)
    sub = _subscription(organization)
    before = sub.ends_at
    client.force_login(actor)
    assert client.post(_extend_url(organization, sub), {"days": 5, "reason": "x"}).status_code == 403
    sub.refresh_from_db()
    assert sub.ends_at == before  # no write


def test_view_anonymous_redirected(client, organization):
    sub = _subscription(organization)
    resp = client.post(_extend_url(organization, sub), {"days": 5, "reason": "x"})
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


def test_view_non_staff_forbidden(client, regular_user, organization):
    sub = _subscription(organization)
    client.force_login(regular_user)
    assert client.post(_extend_url(organization, sub), {"days": 5, "reason": "x"}).status_code == 403


def test_view_get_is_405(client, finance_user, organization):
    sub = _subscription(organization)
    client.force_login(finance_user)
    assert client.get(_extend_url(organization, sub)).status_code == 405


def test_view_cross_tenant_subscription_404(client, finance_user, organization):
    other = Organization.objects.create(
        name="Other2", country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR,
    )
    sub_other = _subscription(other)
    client.force_login(finance_user)
    # org_id=organization but subscription belongs to `other` → 404
    url = reverse("platform_admin:crm:subscription_extend", args=[organization.id, sub_other.id])
    assert client.post(url, {"days": 5, "reason": "x"}).status_code == 404


def test_view_missing_subscription_404(client, finance_user, organization):
    client.force_login(finance_user)
    url = reverse("platform_admin:crm:subscription_extend", args=[organization.id, uuid.uuid4()])
    assert client.post(url, {"days": 5, "reason": "x"}).status_code == 404


def test_view_invalid_form_does_not_extend(client, finance_user, organization):
    sub = _subscription(organization)
    before = sub.ends_at
    client.force_login(finance_user)
    resp = client.post(_extend_url(organization, sub), {"days": 0, "reason": ""})
    assert resp.status_code == 302  # redirects back with an error message
    sub.refresh_from_db()
    assert sub.ends_at == before


# ══ UI smoke ══════════════════════════════════════════════════════════════════
def _profile(client, user, organization):
    client.force_login(user)
    return client.get(
        reverse("platform_admin:crm:customer_detail", args=[organization.id])
    ).content.decode()


def test_extend_form_visible_for_finance(client, finance_user, organization):
    sub = _subscription(organization)
    body = _profile(client, finance_user, organization)
    assert _extend_url(organization, sub) in body


def test_extend_form_hidden_for_readonly(client, readonly_user, organization):
    sub = _subscription(organization)
    # readonly CAN view financial (sees the tab) but CANNOT manage → no form
    body = _profile(client, readonly_user, organization)
    assert _extend_url(organization, sub) not in body


def test_extend_form_hidden_for_support(client, support_user, organization):
    sub = _subscription(organization)
    body = _profile(client, support_user, organization)
    assert _extend_url(organization, sub) not in body


def test_no_other_financial_action_routes_rendered(client, finance_user, organization):
    _subscription(organization)
    body = _profile(client, finance_user, organization).lower()
    # Only extend exists in CRM-1F-1B — no suspend/reactivate/change-plan/manual-payment.
    for forbidden in ("/suspend/", "/reactivate/", "/change-plan/", "/manual-payment/"):
        assert forbidden not in body


# ══ Superadmin access rule (mandatory) ════════════════════════════════════════
def _superuser_without_staff():
    User = get_user_model()
    u = User.objects.create_user(
        email="root-nostaff@test", password="x", full_name="root", is_staff=False
    )
    u.is_superuser = True
    u.save(update_fields=["is_superuser"])
    return u


def test_superuser_with_staff_is_treated_as_owner(superuser):
    from apps.platform_admin import permissions as perms

    # superuser + is_staff, NOT in any CRM group → implicit Platform Owner.
    assert superuser.is_superuser and superuser.is_staff
    assert superuser.groups.count() == 0
    assert perms.can_manage_financial_crm_data(superuser) is True
    assert perms.can_view_financial_crm_data(superuser) is True


def test_superuser_with_staff_can_extend_service(organization, superuser):
    sub = _subscription(organization)
    before = sub.ends_at
    out = ops.crm_extend_subscription(
        actor=superuser, organization=organization, subscription=sub,
        days=7, reason="ops",
    )
    assert out.ends_at == before + timedelta(days=7)


def test_superuser_with_staff_can_extend_view(client, superuser, organization):
    sub = _subscription(organization)
    before = sub.ends_at
    client.force_login(superuser)
    resp = client.post(_extend_url(organization, sub), {"days": 5, "reason": "ops"})
    assert resp.status_code == 302
    sub.refresh_from_db()
    assert sub.ends_at == before + timedelta(days=5)


def test_superuser_without_staff_denied_service(organization):
    actor = _superuser_without_staff()
    assert actor.is_superuser and not actor.is_staff
    sub = _subscription(organization)
    with pytest.raises(PermissionDenied):
        ops.crm_extend_subscription(
            actor=actor, organization=organization, subscription=sub,
            days=5, reason="x",
        )


def test_superuser_without_staff_denied_view(client, organization):
    actor = _superuser_without_staff()
    sub = _subscription(organization)
    before = sub.ends_at
    client.force_login(actor)
    assert client.post(_extend_url(organization, sub), {"days": 5, "reason": "x"}).status_code == 403
    sub.refresh_from_db()
    assert sub.ends_at == before
