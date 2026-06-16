"""CRM-1F-3B-2A — manual payment wrappers (add / confirm / reject)."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.authentication.models import AuditLog
from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.payments.choices import PaymentStatus
from apps.payments.models import PaymentTransaction
from apps.platform_admin.models import CustomerActivity
from apps.platform_admin.services import crm_operations as ops

pytestmark = pytest.mark.django_db

_SECRET_KEYS = (
    "raw_request", "raw_response", "raw_webhook",
    "provider_payment_id", "checkout_url", "idempotency_key",
)


def _plan(price="50.00", currency="SAR"):
    # get_or_create so repeated calls in one test reuse the same paid plan
    # (Plan.code is unique). Per-test DB is fresh.
    plan, _ = Plan.objects.get_or_create(
        code=PlanCode.STARTER,
        defaults=dict(
            name_ar="س", name_en="Starter", invoice_limit=100,
            price=price, currency=currency, is_free=False, is_trial=False,
        ),
    )
    return plan


def _add(actor, organization, plan=None, **over):
    plan = plan or _plan()
    kwargs = dict(
        actor=actor, organization=organization, plan=plan,
        amount=plan.price, currency=plan.currency, reference="TT-1", reason="r",
    )
    kwargs.update(over)
    return ops.crm_add_manual_payment(**kwargs)


def _superuser_without_staff():
    User = get_user_model()
    u = User.objects.create_user(
        email=f"root-{uuid.uuid4().hex[:6]}@t.test", password="x", full_name="r",
        is_staff=False,
    )
    u.is_superuser = True
    u.save(update_fields=["is_superuser"])
    return u


# ══ Add ═══════════════════════════════════════════════════════════════════════
def test_add_creates_pending_subscription_and_payment(organization, finance_user):
    payment = _add(finance_user, organization)
    assert payment.provider == "manual"
    assert payment.status == PaymentStatus.PENDING
    sub = OrganizationSubscription.objects.get(id=payment.reference_id)
    assert sub.status == SubscriptionStatus.PENDING_PAYMENT  # not activated
    # audit + activity
    audit = AuditLog.objects.filter(
        resource_id=str(payment.id), details__action_type="manual_payment_added"
    ).latest("timestamp")
    assert audit.details["new_value"]["reference"] == "TT-1"
    assert CustomerActivity.objects.filter(
        organization=organization, activity_type="manual_payment_added"
    ).exists()


def test_add_owner_allowed(organization, owner_user):
    assert _add(owner_user, organization).status == PaymentStatus.PENDING


def test_add_superuser_with_staff_allowed(organization, superuser):
    assert superuser.groups.count() == 0
    assert _add(superuser, organization).provider == "manual"


@pytest.mark.parametrize("role", ["support_user", "readonly_user", "admin_user", "staff_no_group"])
def test_add_denied_roles(request, organization, role):
    actor = request.getfixturevalue(role)
    with pytest.raises(PermissionDenied):
        _add(actor, organization)


def test_add_superuser_without_staff_denied(organization):
    with pytest.raises(PermissionDenied):
        _add(_superuser_without_staff(), organization)


def test_add_customer_user_denied(organization, regular_user):
    with pytest.raises(PermissionDenied):
        _add(regular_user, organization)


def test_add_reason_required(organization, finance_user):
    with pytest.raises(ValidationError):
        _add(finance_user, organization, reason="  ")


def test_add_reference_required(organization, finance_user):
    with pytest.raises(ValidationError):
        _add(finance_user, organization, reference="  ")


def test_add_wrong_amount_rejected(organization, finance_user):
    plan = _plan(price="50.00")
    with pytest.raises(ValidationError):
        _add(finance_user, organization, plan=plan, amount="1.00")


def test_add_rejected_when_usable_subscription_exists(organization, finance_user):
    OrganizationSubscription.objects.create(
        organization=organization, plan=_plan(), status=SubscriptionStatus.ACTIVE,
        invoice_limit=100,
    )
    with pytest.raises(ValidationError):
        _add(finance_user, organization)


def test_add_duplicate_pending_rejected(organization, finance_user):
    _add(finance_user, organization)
    with pytest.raises(ValidationError):
        _add(finance_user, organization)


def test_add_no_secrets_in_audit_or_activity(organization, finance_user):
    payment = _add(finance_user, organization)
    audit = AuditLog.objects.filter(resource_id=str(payment.id)).latest("timestamp")
    activity = CustomerActivity.objects.filter(organization=organization).latest("created_at")
    for blob in (audit.details, activity.metadata):
        flat = str(blob)
        for k in _SECRET_KEYS:
            assert k not in flat


# ══ Confirm ═══════════════════════════════════════════════════════════════════
def test_confirm_activates_subscription(organization, finance_user):
    payment = _add(finance_user, organization)
    ops.crm_confirm_manual_payment(
        actor=finance_user, organization=organization, payment=payment, reason="received",
    )
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PAID
    sub = OrganizationSubscription.objects.get(id=payment.reference_id)
    assert sub.status == SubscriptionStatus.ACTIVE  # activated via signal chain
    assert AuditLog.objects.filter(
        resource_id=str(payment.id), details__action_type="manual_payment_confirmed"
    ).exists()
    assert CustomerActivity.objects.filter(
        organization=organization, activity_type="manual_payment_confirmed"
    ).exists()


def test_confirm_owner_and_superuser_staff_allowed(organization, owner_user, superuser):
    p1 = _add(owner_user, organization)
    ops.crm_confirm_manual_payment(actor=owner_user, organization=organization, payment=p1, reason="ok")
    p1.refresh_from_db()
    assert p1.status == PaymentStatus.PAID

    org2 = type(organization).objects.create(
        name="Org2", country=organization.country, currency=organization.currency,
    )
    p2 = _add(superuser, org2)
    ops.crm_confirm_manual_payment(actor=superuser, organization=org2, payment=p2, reason="ok")
    p2.refresh_from_db()
    assert p2.status == PaymentStatus.PAID


@pytest.mark.parametrize("role", ["support_user", "readonly_user"])
def test_confirm_denied_roles(request, organization, finance_user, role):
    payment = _add(finance_user, organization)
    actor = request.getfixturevalue(role)
    with pytest.raises(PermissionDenied):
        ops.crm_confirm_manual_payment(actor=actor, organization=organization, payment=payment, reason="x")


def test_confirm_superuser_without_staff_denied(organization, finance_user):
    payment = _add(finance_user, organization)
    with pytest.raises(PermissionDenied):
        ops.crm_confirm_manual_payment(
            actor=_superuser_without_staff(), organization=organization, payment=payment, reason="x",
        )


def test_confirm_wrong_organization_denied(organization, finance_user):
    payment = _add(finance_user, organization)
    other = type(organization).objects.create(
        name="Other", country=organization.country, currency=organization.currency,
    )
    with pytest.raises(ValidationError):
        ops.crm_confirm_manual_payment(actor=finance_user, organization=other, payment=payment, reason="x")


def test_confirm_non_manual_rejected(organization, finance_user):
    txn = PaymentTransaction.objects.create(
        organization=organization, provider="moyasar", purpose="subscription",
        amount="50.00", currency="SAR", status=PaymentStatus.PENDING,
    )
    with pytest.raises(ValidationError):
        ops.crm_confirm_manual_payment(actor=finance_user, organization=organization, payment=txn, reason="x")


def test_confirm_non_pending_rejected(organization, finance_user):
    payment = _add(finance_user, organization)
    ops.crm_confirm_manual_payment(actor=finance_user, organization=organization, payment=payment, reason="ok")
    payment.refresh_from_db()
    # second confirm — already paid → rejected, no duplicate confirmed-audit
    before = AuditLog.objects.filter(
        resource_id=str(payment.id), details__action_type="manual_payment_confirmed"
    ).count()
    with pytest.raises(ValidationError):
        ops.crm_confirm_manual_payment(actor=finance_user, organization=organization, payment=payment, reason="again")
    after = AuditLog.objects.filter(
        resource_id=str(payment.id), details__action_type="manual_payment_confirmed"
    ).count()
    assert before == after == 1


# ══ Reject ════════════════════════════════════════════════════════════════════
def test_reject_cancels_without_activation(organization, finance_user):
    payment = _add(finance_user, organization)
    ops.crm_reject_manual_payment(
        actor=finance_user, organization=organization, payment=payment, reason="bad ref",
    )
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.CANCELED
    sub = OrganizationSubscription.objects.get(id=payment.reference_id)
    assert sub.status == SubscriptionStatus.PENDING_PAYMENT  # NOT activated
    assert AuditLog.objects.filter(
        resource_id=str(payment.id), details__action_type="manual_payment_rejected"
    ).exists()
    assert CustomerActivity.objects.filter(
        organization=organization, activity_type="manual_payment_rejected"
    ).exists()


def test_reject_owner_and_superuser_staff_allowed(organization, owner_user):
    payment = _add(owner_user, organization)
    ops.crm_reject_manual_payment(actor=owner_user, organization=organization, payment=payment, reason="x")
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.CANCELED


def test_reject_wrong_organization_denied(organization, finance_user):
    payment = _add(finance_user, organization)
    other = type(organization).objects.create(
        name="Other2", country=organization.country, currency=organization.currency,
    )
    with pytest.raises(ValidationError):
        ops.crm_reject_manual_payment(actor=finance_user, organization=other, payment=payment, reason="x")


def test_reject_paid_payment_forbidden(organization, finance_user):
    payment = _add(finance_user, organization)
    ops.crm_confirm_manual_payment(actor=finance_user, organization=organization, payment=payment, reason="ok")
    payment.refresh_from_db()
    with pytest.raises(ValidationError):
        ops.crm_reject_manual_payment(actor=finance_user, organization=organization, payment=payment, reason="x")


@pytest.mark.parametrize("role", ["support_user", "readonly_user"])
def test_reject_denied_roles(request, organization, finance_user, role):
    payment = _add(finance_user, organization)
    actor = request.getfixturevalue(role)
    with pytest.raises(PermissionDenied):
        ops.crm_reject_manual_payment(actor=actor, organization=organization, payment=payment, reason="x")


# ══ Confirm-time double-active guard (hardening) ══════════════════════════════
def test_confirm_rejects_if_organization_gained_usable_subscription_after_manual_payment_created(
    organization, finance_user,
):
    payment = _add(finance_user, organization)  # pending sub + pending payment
    # org gains a usable (active) subscription AFTER the manual payment was added
    OrganizationSubscription.objects.create(
        organization=organization, plan=_plan(), status=SubscriptionStatus.ACTIVE,
        invoice_limit=100,
    )
    audit_before = AuditLog.objects.filter(
        details__action_type="manual_payment_confirmed"
    ).count()
    act_before = CustomerActivity.objects.filter(
        activity_type="manual_payment_confirmed"
    ).count()

    with pytest.raises(ValidationError):
        ops.crm_confirm_manual_payment(
            actor=finance_user, organization=organization, payment=payment, reason="x",
        )

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING            # not paid
    sub = OrganizationSubscription.objects.get(id=payment.reference_id)
    assert sub.status == SubscriptionStatus.PENDING_PAYMENT   # not activated
    # no success audit/activity written
    assert AuditLog.objects.filter(
        details__action_type="manual_payment_confirmed"
    ).count() == audit_before
    assert CustomerActivity.objects.filter(
        activity_type="manual_payment_confirmed"
    ).count() == act_before
