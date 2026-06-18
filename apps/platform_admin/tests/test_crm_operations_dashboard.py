"""CRM-OPERATIONS-UX-A — the CRM dashboard is a customer-operations console:
KPI cards, work queues, quick actions, and a professional empty state. Reads
real Organization / subscription / payment data; never exposes raw provider JSON.
"""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.authentication.models import Organization

pytestmark = pytest.mark.django_db

_DASH = reverse("platform_admin:crm:dashboard")


def _login(user):
    c = Client()
    c.force_login(user)
    return c


def _get(user, url):
    # Force English rendering so label assertions are locale-safe.
    return _login(user).get(url, HTTP_ACCEPT_LANGUAGE="en")


def test_dashboard_kpis_present(owner_user, organization):
    html = _get(owner_user, _DASH).content.decode("utf-8")
    assert "Organizations" in html
    assert "Active subscriptions" in html
    assert "Pending payments" in html
    assert "Open tickets" in html
    assert "Suspended" in html
    assert "Quick actions" in html


def test_dashboard_empty_state_when_no_customers(owner_user):
    Organization.objects.all().delete()
    html = _get(owner_user, _DASH).content.decode("utf-8")
    assert "No customers yet." in html


def test_pending_payment_appears_in_attention_queue(owner_user, organization):
    from apps.payments.choices import PaymentStatus
    from apps.payments.models import PaymentTransaction
    PaymentTransaction.objects.create(
        organization=organization, provider="moyasar", purpose="subscription",
        amount=Decimal("75.00"), currency="SAR", status=PaymentStatus.PENDING,
        provider_reference="QUEUE_REF",
        raw_response={"secret": "must-never-render"},
    )
    html = _get(owner_user, _DASH).content.decode("utf-8")
    assert "Payments needing attention" in html
    assert organization.name in html
    # No raw provider JSON / secrets leak into the console.
    assert "must-never-render" not in html
    assert "raw_response" not in html


def test_customer_directory_reads_real_organization(owner_user, organization):
    html = _get(owner_user, reverse("platform_admin:crm:customers")).content.decode("utf-8")
    assert organization.name in html


def test_staff_without_crm_group_denied(staff_no_group):
    resp = _login(staff_no_group).get(_DASH)
    assert resp.status_code == 403


def test_regular_user_denied(regular_user):
    resp = _login(regular_user).get(_DASH)
    assert resp.status_code in (403, 302)
