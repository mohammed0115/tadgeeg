"""Regression guard for AI-usage plan phase 0 tenant isolation.

A metering record is financial data. Its owner must never be optional in a
request path that reads tenant-owned invoices or reports. These are live DRF
requests built from fresh objects; a removal of the organisation guard must
make this suite fail.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from apps.authentication.models import Organization
from apps.invoices.models import Invoice

User = get_user_model()


def _organization(name: str, vat_number: str) -> Organization:
    return Organization.objects.create(
        name=name,
        name_ar=name,
        country="SA",
        currency="SAR",
        vat_number=vat_number,
    )


def _user(email: str, organization: Organization | None = None):
    return User.objects.create_user(
        email=email,
        password="StrongPass1!",
        full_name=email,
        role=User.Role.SENIOR_AUDITOR,
        organization=organization,
    )


def _invoice(organization: Organization, user) -> Invoice:
    return Invoice.objects.create(
        organization=organization,
        uploaded_by=user,
        original_filename="tenant-guard.pdf",
        invoice_number="TENANT-GUARD-001",
        invoice_date=date(2026, 8, 19),
        vendor_name="Tenant Guard Vendor",
        vendor_vat_number="300000000000010",
        currency="SAR",
        subtotal=Decimal("1000.00"),
        vat_amount=Decimal("150.00"),
        total_amount=Decimal("1150.00"),
        status="pending",
    )


@pytest.mark.django_db
def test_phase_zero_guard_denies_anonymous_invoice_request():
    response = APIClient().get("/api/v1/invoices/")
    assert response.status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    }


@pytest.mark.django_db
def test_phase_zero_guard_denies_authenticated_user_without_organization():
    _invoice_org = _organization("Invoice Tenant", "300000000000001")
    no_org_user = _user("no-org-ai-metering@example.test")
    client = APIClient()
    client.force_authenticate(no_org_user)

    response = client.get("/api/v1/invoices/")

    assert response.status_code == status.HTTP_403_FORBIDDEN, (
        "An authenticated user without an organization must be denied, not "
        "silently receive a tenant query."
    )


@pytest.mark.django_db
def test_phase_zero_guard_denies_cross_tenant_invoice_identifier():
    owner_org = _organization("Owner Tenant", "300000000000002")
    attacker_org = _organization("Attacker Tenant", "300000000000003")
    owner = _user("owner-ai-metering@example.test", owner_org)
    attacker = _user("attacker-ai-metering@example.test", attacker_org)
    victim_invoice = _invoice(owner_org, owner)
    client = APIClient()
    client.force_authenticate(attacker)

    response = client.get(f"/api/v1/invoices/{victim_invoice.id}/")

    assert response.status_code in {
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    }
