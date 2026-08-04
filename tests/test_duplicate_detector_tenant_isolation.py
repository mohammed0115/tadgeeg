"""
Regression test — DuplicateDetector must NEVER return matches across tenants.

The pre-fix bug: if the detector was instantiated without an `organization_id`,
the org filter was silently skipped, returning duplicates from every tenant
in the database. This violated the org-isolation contract and showed users
duplicates that belonged to other organizations.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.invoices.models import Invoice
from core.services.detection.duplicate_detector import DuplicateDetector


@pytest.fixture
def two_orgs(db, organization):
    """Caller's org plus a second isolated org."""
    from apps.authentication.models import Organization
    other = Organization.objects.create(
        name="Other Co",
        country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR,
        vat_number="300000000000777",
    )
    return organization, other


@pytest.fixture
def cross_org_invoices(two_orgs):
    """Same invoice number + vendor in BOTH orgs to make leakage easy to detect."""
    org_a, org_b = two_orgs
    inv_a = Invoice.objects.create(
        organization=org_a, invoice_number="DUPE-X-1",
        vendor_name="VendorOne", invoice_date=date(2026, 4, 1),
        total_amount=Decimal("1000"), currency="SAR",
    )
    inv_b = Invoice.objects.create(
        organization=org_b, invoice_number="DUPE-X-1",
        vendor_name="VendorOne", invoice_date=date(2026, 4, 1),
        total_amount=Decimal("1000"), currency="SAR",
    )
    return org_a, org_b, inv_a, inv_b


@pytest.mark.django_db
class TestDuplicateDetectorTenantIsolation:

    def test_org_a_does_not_see_org_b_duplicate(self, cross_org_invoices):
        """The same invoice number exists in two orgs; detector for org_a must NOT match org_b's row."""
        org_a, org_b, inv_a, inv_b = cross_org_invoices
        detector = DuplicateDetector(organization_id=org_a.id)
        result = detector.detect({
            "invoice_number": "DUPE-X-1",
            "vendor_name": "VendorOne",
            "total_amount": "1000",
            "invoice_date": "2026-04-01",
        })
        # No prior invoice exists in org_a (other than what the detector
        # would self-match if it didn't exclude). The only same-number row
        # belongs to org_b — must NOT appear.
        assert inv_b.id not in result["matched_document_ids"], (
            f"Cross-tenant leak: org_b's invoice {inv_b.id} appeared in org_a's matches"
        )

    def test_org_b_does_not_see_org_a_duplicate(self, cross_org_invoices):
        """Symmetric check from the opposite org."""
        org_a, org_b, inv_a, inv_b = cross_org_invoices
        detector = DuplicateDetector(organization_id=org_b.id)
        result = detector.detect({
            "invoice_number": "DUPE-X-1",
            "vendor_name": "VendorOne",
            "total_amount": "1000",
            "invoice_date": "2026-04-01",
        })
        assert inv_a.id not in result["matched_document_ids"]

    def test_no_org_id_returns_no_matches(self, cross_org_invoices):
        """Fail-safe: missing organization_id must NOT return cross-tenant matches."""
        detector = DuplicateDetector(organization_id=None)
        result = detector.detect({
            "invoice_number": "DUPE-X-1",
            "vendor_name": "VendorOne",
            "total_amount": "1000",
            "invoice_date": "2026-04-01",
        })
        assert result["is_duplicate"] is False
        assert result["matched_document_ids"] == []
        assert result.get("skipped") == "missing_organization_id"

    def test_same_org_dup_still_detected(self, two_orgs):
        """Sanity: within the same org, real duplicates are still flagged."""
        org_a, _ = two_orgs
        Invoice.objects.create(
            organization=org_a, invoice_number="LEGIT-DUPE",
            vendor_name="VendorTwo", invoice_date=date(2026, 4, 1),
            total_amount=Decimal("500"), currency="SAR",
        )
        detector = DuplicateDetector(organization_id=org_a.id)
        result = detector.detect({
            "invoice_number": "LEGIT-DUPE",
            "vendor_name": "VendorTwo",
            "total_amount": "500",
            "invoice_date": "2026-04-01",
        })
        assert result["is_duplicate"] is True, "Same-org duplicates must still be detected"

    def test_zero_org_id_treated_as_missing(self, cross_org_invoices):
        """Defensive: organization_id=0 (truthy-False) must NOT skip the filter."""
        detector = DuplicateDetector(organization_id=0)
        result = detector.detect({
            "invoice_number": "DUPE-X-1",
            "vendor_name": "VendorOne",
            "total_amount": "1000",
            "invoice_date": "2026-04-01",
        })
        assert result["matched_document_ids"] == []


@pytest.mark.django_db
class TestInvoiceListTenantIsolation:
    """The /invoices/ list page must never show another tenant's invoices."""

    def test_user_without_org_sees_no_invoices(self, two_orgs):
        """User with organization=None must NOT see any invoices at all."""
        from django.contrib.auth import get_user_model
        from django.test import Client
        org_a, org_b = two_orgs
        Invoice.objects.create(
            organization=org_a, invoice_number="LIST-LEAK-1",
            vendor_name="V", invoice_date=date(2026, 4, 1),
            total_amount=Decimal("100"), currency="SAR",
        )
        # Create an org-less user
        U = get_user_model()
        orphan = U.objects.create_user(email="orphan@x.local", password="x", is_active=True)
        orphan.organization = None
        orphan.save()

        c = Client(); c.force_login(orphan)
        r = c.get('/invoices/')
        assert r.status_code in (200, 302), f"unexpected status {r.status_code}"
        if r.status_code == 200:
            assert b"LIST-LEAK-1" not in r.content, (
                "Orphan user (no org) is seeing another tenant's invoice — TENANT LEAK"
            )

    def test_org_a_user_does_not_see_org_b_invoice(self, two_orgs):
        """Standard isolation: org_a's user must not see org_b invoices in the list."""
        from django.contrib.auth import get_user_model
        from django.test import Client
        org_a, org_b = two_orgs
        Invoice.objects.create(
            organization=org_b, invoice_number="LIST-CROSS-1",
            vendor_name="V", invoice_date=date(2026, 4, 1),
            total_amount=Decimal("100"), currency="SAR",
        )
        # /invoices/ redirects an org with no subscription to /billing/plans/,
        # so without this the test measured the billing gate instead of tenant
        # isolation. Created through the real service, not an inserted row.
        from io import StringIO

        from django.core.management import call_command

        from apps.billing.services.subscription_service import SubscriptionService

        call_command("seed_billing_plans", stdout=StringIO())
        SubscriptionService().create_free_trial(org_a)

        U = get_user_model()
        u = U.objects.create_user(email="user-a@x.local", password="x",
                                  is_active=True, organization=org_a)
        c = Client(); c.force_login(u)
        r = c.get('/invoices/')
        assert r.status_code == 200
        assert b"LIST-CROSS-1" not in r.content, (
            "Cross-tenant leak in /invoices/ list page"
        )
