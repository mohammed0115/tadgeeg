"""CRM-1F-3B-2B — manual payment UI / views (add / confirm / reject)."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.payments.choices import PaymentStatus
from apps.payments.models import PaymentTransaction
from apps.platform_admin.services import crm_operations as ops

pytestmark = pytest.mark.django_db


def _plan(price="50.00", currency="SAR"):
    plan, _ = Plan.objects.get_or_create(
        code=PlanCode.STARTER,
        defaults=dict(
            name_ar="س", name_en="Starter", invoice_limit=100,
            price=price, currency=currency, is_free=False, is_trial=False,
            is_active=True,
        ),
    )
    return plan


def _pending_manual(actor, organization, plan=None):
    plan = plan or _plan()
    return ops.crm_add_manual_payment(
        actor=actor, organization=organization, plan=plan,
        amount=plan.price, currency=plan.currency, reference="TT-9", reason="r",
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


def _add_url(org):
    return reverse("platform_admin:crm:manual_payment_add", args=[org.id])


def _confirm_url(org, pay):
    return reverse("platform_admin:crm:manual_payment_confirm", args=[org.id, pay.id])


def _reject_url(org, pay):
    return reverse("platform_admin:crm:manual_payment_reject", args=[org.id, pay.id])


def _profile(client, user, org):
    client.force_login(user)
    return client.get(reverse("platform_admin:crm:customer_detail", args=[org.id])).content.decode()


# ══ Visibility ════════════════════════════════════════════════════════════════
def test_add_form_visible_for_owner_and_finance(client, owner_user, finance_user, organization):
    _plan()
    assert _add_url(organization) in _profile(client, owner_user, organization)
    assert _add_url(organization) in _profile(client, finance_user, organization)


def test_add_form_visible_for_superuser_staff(client, superuser, organization):
    _plan()
    assert _add_url(organization) in _profile(client, superuser, organization)


@pytest.mark.parametrize("role", ["support_user", "readonly_user", "admin_user"])
def test_add_form_hidden_for_non_financial(client, request, organization, role):
    _plan()
    user = request.getfixturevalue(role)
    assert _add_url(organization) not in _profile(client, user, organization)


def test_confirm_reject_buttons_only_for_pending_manual(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    body = _profile(client, finance_user, organization)
    assert _confirm_url(organization, payment) in body
    assert _reject_url(organization, payment) in body


def test_confirm_reject_hidden_for_hosted_or_terminal(client, finance_user, organization):
    hosted = PaymentTransaction.objects.create(
        organization=organization, provider="moyasar", purpose="subscription",
        amount="50.00", currency="SAR", status=PaymentStatus.PENDING,
    )
    body = _profile(client, finance_user, organization)
    assert _confirm_url(organization, hosted) not in body  # not manual


def test_no_raw_secrets_in_payments_html(client, finance_user, organization):
    _pending_manual(finance_user, organization)
    body = _profile(client, finance_user, organization)
    for secret in ("raw_request", "raw_response", "raw_webhook",
                   "provider_payment_id", "checkout_url", "idempotency_key"):
        assert secret not in body


# ══ Add view ══════════════════════════════════════════════════════════════════
def _add_post(client, org, plan, **over):
    data = dict(plan=str(plan.id), amount=str(plan.price), currency=plan.currency,
                reference="TT-1", reason="bank transfer")
    data.update(over)
    return client.post(_add_url(org), data)


def test_add_post_finance_creates_pending(client, finance_user, organization):
    plan = _plan()
    client.force_login(finance_user)
    resp = _add_post(client, organization, plan)
    assert resp.status_code == 302
    txn = PaymentTransaction.objects.get(organization=organization, provider="manual")
    assert txn.status == PaymentStatus.PENDING


def test_add_post_owner_and_superuser_staff(client, owner_user, superuser, organization):
    plan = _plan()
    client.force_login(owner_user)
    assert _add_post(client, organization, plan).status_code == 302
    # superuser on a second org
    org2 = type(organization).objects.create(
        name="Org2", country=organization.country, currency=organization.currency)
    client.force_login(superuser)
    assert _add_post(client, org2, plan).status_code == 302


@pytest.mark.parametrize("role", ["support_user", "readonly_user", "admin_user", "regular_user"])
def test_add_post_denied_roles(client, request, organization, role):
    plan = _plan()
    user = request.getfixturevalue(role)
    client.force_login(user)
    before = PaymentTransaction.objects.count()
    assert _add_post(client, organization, plan).status_code == 403
    assert PaymentTransaction.objects.count() == before


def test_add_post_superuser_without_staff_denied(client, organization):
    plan = _plan()
    client.force_login(_superuser_without_staff())
    assert _add_post(client, organization, plan).status_code == 403


def test_add_anonymous_redirected(client, organization):
    plan = _plan()
    resp = _add_post(client, organization, plan)
    assert resp.status_code == 302 and "/login/" in resp["Location"]


def test_add_get_is_405(client, finance_user, organization):
    client.force_login(finance_user)
    assert client.get(_add_url(organization)).status_code == 405


def test_add_invalid_form_no_write(client, finance_user, organization):
    plan = _plan()
    client.force_login(finance_user)
    before = PaymentTransaction.objects.count()
    resp = _add_post(client, organization, plan, reference="")  # missing reference
    assert resp.status_code == 302
    assert PaymentTransaction.objects.count() == before


def test_add_amount_mismatch_no_write(client, finance_user, organization):
    plan = _plan()
    client.force_login(finance_user)
    before = PaymentTransaction.objects.count()
    resp = _add_post(client, organization, plan, amount="1.00")
    assert resp.status_code == 302
    assert PaymentTransaction.objects.count() == before


def test_add_with_usable_subscription_no_write(client, finance_user, organization):
    OrganizationSubscription.objects.create(
        organization=organization, plan=_plan(), status=SubscriptionStatus.ACTIVE,
        invoice_limit=100,
    )
    client.force_login(finance_user)
    before = PaymentTransaction.objects.count()
    resp = _add_post(client, organization, _plan())
    assert resp.status_code == 302
    assert PaymentTransaction.objects.count() == before


# ══ Confirm view ══════════════════════════════════════════════════════════════
def test_confirm_marks_paid_and_activates(client, finance_user, organization, django_capture_on_commit_callbacks):
    payment = _pending_manual(finance_user, organization)
    client.force_login(finance_user)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(_confirm_url(organization, payment), {"reason": "received"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PAID
    sub = OrganizationSubscription.objects.get(id=payment.reference_id)
    assert sub.status == SubscriptionStatus.ACTIVE


def test_confirm_superuser_staff_allowed(client, superuser, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    client.force_login(superuser)
    assert client.post(_confirm_url(organization, payment), {"reason": "x"}).status_code == 302


@pytest.mark.parametrize("role", ["support_user", "readonly_user"])
def test_confirm_denied_roles(client, request, finance_user, organization, role):
    payment = _pending_manual(finance_user, organization)
    user = request.getfixturevalue(role)
    client.force_login(user)
    assert client.post(_confirm_url(organization, payment), {"reason": "x"}).status_code == 403
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING


def test_confirm_wrong_org_404(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    other = type(organization).objects.create(
        name="Other", country=organization.country, currency=organization.currency)
    client.force_login(finance_user)
    url = reverse("platform_admin:crm:manual_payment_confirm", args=[other.id, payment.id])
    assert client.post(url, {"reason": "x"}).status_code == 404


def test_confirm_get_is_405(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    client.force_login(finance_user)
    assert client.get(_confirm_url(organization, payment)).status_code == 405


def test_confirm_reason_missing_no_write(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    client.force_login(finance_user)
    resp = client.post(_confirm_url(organization, payment), {"reason": ""})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING


def test_confirm_double_active_guard_keeps_pending(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    OrganizationSubscription.objects.create(
        organization=organization, plan=_plan(), status=SubscriptionStatus.ACTIVE,
        invoice_limit=100,
    )
    client.force_login(finance_user)
    resp = client.post(_confirm_url(organization, payment), {"reason": "x"})
    assert resp.status_code == 302  # redirect with error message, no crash
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING


def test_double_confirm_rejected(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    client.force_login(finance_user)
    client.post(_confirm_url(organization, payment), {"reason": "ok"})
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PAID
    # second confirm — payment no longer pending → safe error, still paid (idempotent)
    client.post(_confirm_url(organization, payment), {"reason": "again"})
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PAID


# ══ Reject view ═══════════════════════════════════════════════════════════════
def test_reject_cancels_without_activation(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    client.force_login(finance_user)
    resp = client.post(_reject_url(organization, payment), {"reason": "bad ref"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.CANCELED
    sub = OrganizationSubscription.objects.get(id=payment.reference_id)
    assert sub.status == SubscriptionStatus.PENDING_PAYMENT


def test_reject_paid_payment_rejected(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    client.force_login(finance_user)
    client.post(_confirm_url(organization, payment), {"reason": "ok"})  # → paid
    resp = client.post(_reject_url(organization, payment), {"reason": "x"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PAID  # unchanged


def test_reject_wrong_org_404(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    other = type(organization).objects.create(
        name="Other2", country=organization.country, currency=organization.currency)
    client.force_login(finance_user)
    url = reverse("platform_admin:crm:manual_payment_reject", args=[other.id, payment.id])
    assert client.post(url, {"reason": "x"}).status_code == 404


def test_reject_get_is_405(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    client.force_login(finance_user)
    assert client.get(_reject_url(organization, payment)).status_code == 405


def test_reject_reason_missing_no_write(client, finance_user, organization):
    payment = _pending_manual(finance_user, organization)
    client.force_login(finance_user)
    resp = client.post(_reject_url(organization, payment), {"reason": ""})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING
