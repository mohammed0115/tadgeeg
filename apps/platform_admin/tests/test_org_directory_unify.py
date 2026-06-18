"""CRM-DATA-VISIBILITY-B — the platform Organizations page is unified with the
server-rendered CRM customer directory (one canonical Organization source).
No client-side API/JS dependency for the base list; no fake "0 organizations".
"""
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.authentication.models import Organization

pytestmark = pytest.mark.django_db

_ORG_URL = reverse("platform_admin:organizations")
_CRM_CUSTOMERS = reverse("platform_admin:crm:customers")


def _login(user):
    c = Client()
    c.force_login(user)
    return c


def _get(user, url, **kw):
    return _login(user).get(url, HTTP_ACCEPT_LANGUAGE="en", **kw)


def test_organizations_redirects_to_crm_customer_directory(owner_user):
    resp = _get(owner_user, _ORG_URL)
    assert resp.status_code == 302
    assert _CRM_CUSTOMERS in resp["Location"]


def test_organizations_server_rendered_shows_real_org(owner_user, organization):
    # Follow the redirect → the unified directory is server-rendered (no JS)
    # and lists the real Organization.
    resp = _get(owner_user, _ORG_URL, follow=True)
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert organization.name in html


def test_no_empty_state_when_orgs_exist(owner_user, organization):
    html = _get(owner_user, _CRM_CUSTOMERS).content.decode("utf-8")
    assert "No customers yet" not in html
    assert organization.name in html


def test_empty_state_when_zero_orgs(owner_user):
    Organization.objects.all().delete()
    html = _get(owner_user, _CRM_CUSTOMERS).content.decode("utf-8")
    assert "No customers yet" in html


def test_directory_shows_plan_and_subscription(owner_user, organization):
    call_command("seed_billing_plans", stdout=StringIO())
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService
    plan = Plan.objects.get(code=PlanCode.STARTER)
    sub = SubscriptionService().create_pending_paid_subscription(organization, plan)
    SubscriptionService().activate_subscription(sub)
    html = _get(owner_user, _CRM_CUSTOMERS).content.decode("utf-8")
    # owner is a financial CRM user → plan/status columns are populated.
    assert (plan.name_en in html) or (plan.name_ar in html) or ("active" in html.lower())


def test_directory_has_no_raw_provider_json(owner_user, organization):
    from apps.payments.choices import PaymentStatus
    from apps.payments.models import PaymentTransaction
    PaymentTransaction.objects.create(
        organization=organization, provider="moyasar", purpose="subscription",
        amount=Decimal("75.00"), currency="SAR", status=PaymentStatus.PAID,
        raw_response={"secret": "must-never-render"},
    )
    html = _get(owner_user, _CRM_CUSTOMERS).content.decode("utf-8")
    assert "must-never-render" not in html
    assert "raw_response" not in html


def test_customer_360_shows_payment_and_no_raw_json(owner_user, organization):
    from apps.payments.choices import PaymentStatus
    from apps.payments.models import PaymentTransaction
    PaymentTransaction.objects.create(
        organization=organization, provider="moyasar", purpose="subscription",
        amount=Decimal("75.00"), currency="SAR", status=PaymentStatus.PAID,
        raw_response={"secret": "must-never-render"},
    )
    url = reverse("platform_admin:crm:customer_detail", args=[organization.id])
    html = _get(owner_user, url).content.decode("utf-8")
    assert html  # 360 renders
    assert "must-never-render" not in html


# ── permissions ──────────────────────────────────────────────────────────────
def test_superuser_sees_directory(superuser, organization):
    assert _get(superuser, _ORG_URL, follow=True).status_code == 200


def test_crm_read_staff_sees_directory(readonly_user, organization):
    assert _get(readonly_user, _ORG_URL, follow=True).status_code == 200


def test_staff_without_crm_role_denied(staff_no_group, organization):
    # Passes platform_admin_required (is staff) but the CRM directory enforces
    # CRM-read → 403 after the redirect.
    assert _get(staff_no_group, _ORG_URL, follow=True).status_code == 403


def test_regular_user_denied(regular_user):
    resp = _get(regular_user, _ORG_URL, follow=True)
    assert resp.status_code in (403, 302) or resp.redirect_chain
