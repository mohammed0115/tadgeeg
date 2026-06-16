"""CRM-1F-2B — Customer Suspend / Reactivate (service, view, middleware, UI)."""

import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.authentication.models import AuditLog, Organization
from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.middleware import SubscriptionRequiredMiddleware
from apps.billing.models import OrganizationSubscription, Plan
from apps.payments.models import PaymentTransaction
from apps.platform_admin.models import CustomerActivity
from apps.platform_admin.services import crm_operations as ops

pytestmark = pytest.mark.django_db

_PLAN_SEQ = {"n": 0}


def _org(active=True, name="Acme"):
    return Organization.objects.create(
        name=name, country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR, is_active=active,
    )


def _org_user(org, is_staff=False, is_superuser=False):
    User = get_user_model()
    u = User.objects.create_user(
        email=f"u-{uuid.uuid4().hex[:8]}@t.test", password="x", full_name="u",
        organization=org, is_staff=is_staff,
    )
    if is_superuser:
        u.is_superuser = True
        u.save(update_fields=["is_superuser"])
    return u


def _usable_subscription(org):
    _PLAN_SEQ["n"] += 1
    plan = Plan.objects.create(
        code=PlanCode.STARTER, name_ar="س", name_en=f"Starter {_PLAN_SEQ['n']}",
        invoice_limit=100, price="50.00",
    )
    now = timezone.now()
    return OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        invoice_limit=100, used_invoices=10, reserved_invoices=5,
        starts_at=now, ends_at=now + timedelta(days=30),
    )


def _superuser_without_staff():
    User = get_user_model()
    u = User.objects.create_user(
        email=f"root-{uuid.uuid4().hex[:6]}@t.test", password="x", full_name="r",
        is_staff=False,
    )
    u.is_superuser = True
    u.save(update_fields=["is_superuser"])
    return u


# ══ Middleware enforcement ════════════════════════════════════════════════════
def _run_mw(user, path="/dashboard/"):
    mw = SubscriptionRequiredMiddleware(lambda r: HttpResponse("OK"))
    req = RequestFactory().get(path)
    req.user = user
    return mw(req)


@override_settings(SUBSCRIPTION_REQUIRED=True)
def test_mw_active_org_with_subscription_passes():
    org = _org(active=True)
    _usable_subscription(org)
    resp = _run_mw(_org_user(org))
    assert resp.status_code == 200 and resp.content == b"OK"


@override_settings(SUBSCRIPTION_REQUIRED=True)
def test_mw_inactive_org_user_blocked_ui():
    org = _org(active=False)
    _usable_subscription(org)  # even with a usable sub, suspension blocks
    resp = _run_mw(_org_user(org), path="/dashboard/")
    assert resp.status_code == 302
    assert resp["Location"] == "/billing/plans/"


@override_settings(SUBSCRIPTION_REQUIRED=True)
def test_mw_inactive_org_user_blocked_api_403():
    org = _org(active=False)
    resp = _run_mw(_org_user(org), path="/api/v1/invoices/")
    assert resp.status_code == 403
    assert b"account_suspended" in resp.content


@override_settings(SUBSCRIPTION_REQUIRED=True)
def test_mw_staff_not_blocked_by_inactive_org():
    org = _org(active=False)
    resp = _run_mw(_org_user(org, is_staff=True))
    assert resp.status_code == 200


@override_settings(SUBSCRIPTION_REQUIRED=True)
def test_mw_superuser_not_blocked_by_inactive_org():
    org = _org(active=False)
    resp = _run_mw(_org_user(org, is_superuser=True, is_staff=True))
    assert resp.status_code == 200


@override_settings(SUBSCRIPTION_REQUIRED=True)
def test_mw_whitelisted_paths_not_broken_for_inactive_org():
    org = _org(active=False)
    user = _org_user(org)
    for path in ("/logout/", "/billing/plans/", "/health/"):
        assert _run_mw(user, path=path).status_code == 200


# ══ Service tests ═════════════════════════════════════════════════════════════
def test_suspend_sets_inactive_with_audit_and_activity(organization, finance_user):
    out = ops.suspend_customer(actor=finance_user, organization=organization, reason="fraud")
    assert out.is_active is False
    audit = AuditLog.objects.filter(
        resource_id=str(organization.id), details__action_type="customer_suspended"
    ).latest("timestamp")
    assert audit.details["old_value"] == {"is_active": True}
    assert audit.details["new_value"] == {"is_active": False}
    assert audit.details["reason"] == "fraud"
    assert CustomerActivity.objects.filter(
        organization=organization, activity_type="customer_suspended"
    ).exists()


def test_reactivate_sets_active(organization, finance_user):
    organization.is_active = False
    organization.save(update_fields=["is_active"])
    out = ops.reactivate_customer(actor=finance_user, organization=organization, reason="resolved")
    assert out.is_active is True
    assert AuditLog.objects.filter(
        resource_id=str(organization.id), details__action_type="customer_reactivated"
    ).exists()


def test_reason_required(organization, finance_user):
    with pytest.raises(ValidationError):
        ops.suspend_customer(actor=finance_user, organization=organization, reason="  ")


def test_double_suspend_rejected(organization, finance_user):
    ops.suspend_customer(actor=finance_user, organization=organization, reason="x")
    organization.refresh_from_db()
    with pytest.raises(ValidationError):
        ops.suspend_customer(actor=finance_user, organization=organization, reason="x")


def test_double_reactivate_rejected(organization, finance_user):
    # organization starts active → reactivate should reject
    with pytest.raises(ValidationError):
        ops.reactivate_customer(actor=finance_user, organization=organization, reason="x")


def test_suspend_does_not_touch_subscription_or_quota(organization, finance_user):
    sub = _usable_subscription(organization)
    snap = (sub.status, sub.invoice_limit, sub.used_invoices, sub.reserved_invoices)
    ops.suspend_customer(actor=finance_user, organization=organization, reason="x")
    sub.refresh_from_db()
    assert (sub.status, sub.invoice_limit, sub.used_invoices, sub.reserved_invoices) == snap


def test_no_payment_transaction(organization, finance_user):
    before = PaymentTransaction.objects.count()
    ops.suspend_customer(actor=finance_user, organization=organization, reason="x")
    assert PaymentTransaction.objects.count() == before


def test_owner_can_suspend(organization, owner_user):
    ops.suspend_customer(actor=owner_user, organization=organization, reason="x")
    organization.refresh_from_db()
    assert organization.is_active is False


@pytest.mark.parametrize("role", ["support_user", "readonly_user", "admin_user", "staff_no_group"])
def test_unauthorized_roles_denied(request, organization, role):
    actor = request.getfixturevalue(role)
    with pytest.raises(PermissionDenied):
        ops.suspend_customer(actor=actor, organization=organization, reason="x")


def test_superuser_with_staff_can_suspend(organization, superuser):
    assert superuser.groups.count() == 0  # not in any CRM group
    ops.suspend_customer(actor=superuser, organization=organization, reason="x")
    organization.refresh_from_db()
    assert organization.is_active is False


def test_superuser_without_staff_denied_service(organization):
    actor = _superuser_without_staff()
    with pytest.raises(PermissionDenied):
        ops.suspend_customer(actor=actor, organization=organization, reason="x")


# ══ View tests ════════════════════════════════════════════════════════════════
def _suspend_url(org):
    return reverse("platform_admin:crm:customer_suspend", args=[org.id])


def _reactivate_url(org):
    return reverse("platform_admin:crm:customer_reactivate", args=[org.id])


def test_view_finance_suspends_and_redirects(client, finance_user, organization):
    client.force_login(finance_user)
    resp = client.post(_suspend_url(organization), {"reason": "abuse"})
    assert resp.status_code == 302
    organization.refresh_from_db()
    assert organization.is_active is False


def test_view_owner_reactivates(client, owner_user, organization):
    organization.is_active = False
    organization.save(update_fields=["is_active"])
    client.force_login(owner_user)
    resp = client.post(_reactivate_url(organization), {"reason": "ok"})
    assert resp.status_code == 302
    organization.refresh_from_db()
    assert organization.is_active is True


def test_view_get_is_405(client, finance_user, organization):
    client.force_login(finance_user)
    assert client.get(_suspend_url(organization)).status_code == 405
    assert client.get(_reactivate_url(organization)).status_code == 405


def test_view_invalid_form_no_write(client, finance_user, organization):
    client.force_login(finance_user)
    resp = client.post(_suspend_url(organization), {"reason": ""})
    assert resp.status_code == 302
    organization.refresh_from_db()
    assert organization.is_active is True  # unchanged


def test_view_anonymous_redirected(client, organization):
    resp = client.post(_suspend_url(organization), {"reason": "x"})
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


@pytest.mark.parametrize("role", ["support_user", "readonly_user", "admin_user", "staff_no_group", "regular_user"])
def test_view_forbidden_roles(client, request, organization, role):
    actor = request.getfixturevalue(role)
    client.force_login(actor)
    assert client.post(_suspend_url(organization), {"reason": "x"}).status_code == 403
    organization.refresh_from_db()
    assert organization.is_active is True


def test_view_superuser_with_staff_allowed(client, superuser, organization):
    client.force_login(superuser)
    assert client.post(_suspend_url(organization), {"reason": "x"}).status_code == 302


def test_view_superuser_without_staff_forbidden(client, organization):
    client.force_login(_superuser_without_staff())
    assert client.post(_suspend_url(organization), {"reason": "x"}).status_code == 403


def test_view_missing_org_404(client, finance_user):
    client.force_login(finance_user)
    url = reverse("platform_admin:crm:customer_suspend", args=[uuid.uuid4()])
    assert client.post(url, {"reason": "x"}).status_code == 404


# ══ UI smoke ══════════════════════════════════════════════════════════════════
def _profile(client, user, org):
    client.force_login(user)
    return client.get(reverse("platform_admin:crm:customer_detail", args=[org.id])).content.decode()


def test_suspend_button_visible_for_finance_when_active(client, finance_user, organization):
    body = _profile(client, finance_user, organization)
    assert _suspend_url(organization) in body
    assert _reactivate_url(organization) not in body


def test_reactivate_button_visible_for_finance_when_inactive(client, finance_user, organization):
    organization.is_active = False
    organization.save(update_fields=["is_active"])
    body = _profile(client, finance_user, organization)
    assert _reactivate_url(organization) in body
    assert _suspend_url(organization) not in body


def test_suspend_button_hidden_for_readonly(client, readonly_user, organization):
    body = _profile(client, readonly_user, organization)
    assert _suspend_url(organization) not in body


def test_suspend_button_hidden_for_support(client, support_user, organization):
    body = _profile(client, support_user, organization)
    assert _suspend_url(organization) not in body


def test_no_other_financial_action_routes(client, finance_user, organization):
    body = _profile(client, finance_user, organization).lower()
    for forbidden in ("/change-plan/", "/manual-payment/", "/adjust-quota/"):
        assert forbidden not in body
