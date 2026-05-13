"""Segregation-of-Duties enforcement tests.

The four-eyes principle: Maker (uploaded_by) ≠ Checker (reviewed_by)
≠ Approver (approved_by). The SoD service is the single chokepoint
for both the manual-review and the approve API paths.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import Organization
from apps.invoices.models import Invoice
from apps.invoices.services.sod_service import (
    SegregationOfDutiesError,
    SoDDecision,
    assert_can_approve,
    assert_can_review,
    can_approve,
    can_review,
    record_approval,
    record_review,
)


User = get_user_model()


def _user(*, organization, email, role=None):
    return User.objects.create_user(
        email=email, password="StrongPass123!",
        full_name=email.split("@")[0],
        role=role or User.Role.SENIOR_AUDITOR,
        organization=organization,
    )


# ─── Pure-function tests on the service ─────────────────────────────────────
class SoDServiceTests(TestCase):
    """Unit-level tests with no API surface."""

    def setUp(self):
        self.org = Organization.objects.create(name="SoD Co")
        self.maker    = _user(organization=self.org, email="maker@example.com")
        self.checker  = _user(organization=self.org, email="checker@example.com")
        self.approver = _user(organization=self.org, email="approver@example.com",
                              role=User.Role.ADMIN)
        self.inv = Invoice.objects.create(
            organization=self.org,
            uploaded_by=self.maker,
            invoice_number="INV-SOD-1",
            vendor_name="Vendor",
            total_amount=Decimal("1000.00"),
        )

    def test_can_review_returns_decision_object(self):
        d = can_review(self.inv, self.checker)
        self.assertIsInstance(d, SoDDecision)
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, "sod_ok")

    def test_maker_cannot_review_own_upload(self):
        d = can_review(self.inv, self.maker)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "self_review")
        with self.assertRaises(SegregationOfDutiesError) as cm:
            assert_can_review(self.inv, self.maker)
        self.assertEqual(cm.exception.conflicting_with, "maker")

    def test_maker_cannot_approve_own_upload(self):
        d = can_approve(self.inv, self.maker)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "self_approve")
        with self.assertRaises(SegregationOfDutiesError):
            assert_can_approve(self.inv, self.maker)

    def test_checker_cannot_approve_after_their_own_review(self):
        record_review(self.inv, self.checker)
        self.inv.refresh_from_db()
        d = can_approve(self.inv, self.checker)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, "reviewer_is_approver")
        with self.assertRaises(SegregationOfDutiesError) as cm:
            assert_can_approve(self.inv, self.checker)
        self.assertEqual(cm.exception.conflicting_with, "checker")

    def test_third_distinct_user_can_approve(self):
        record_review(self.inv, self.checker)
        self.inv.refresh_from_db()
        d = can_approve(self.inv, self.approver)
        self.assertTrue(d.allowed)
        # And the assertion-style call doesn't raise.
        assert_can_approve(self.inv, self.approver)

    def test_record_review_stamps_and_writes_audit_event(self):
        from apps.invoices.models import InvoiceAuditEvent
        before = InvoiceAuditEvent.objects.filter(invoice=self.inv).count()
        record_review(self.inv, self.checker, note="data corrected")
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.reviewed_by_id, self.checker.id)
        self.assertIsNotNone(self.inv.reviewed_at)
        # Audit event appended.
        after = InvoiceAuditEvent.objects.filter(invoice=self.inv).count()
        self.assertEqual(after, before + 1)

    def test_record_approval_stamps_user_and_timestamp(self):
        record_approval(self.inv, self.approver)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.approved_by_id, self.approver.id)
        self.assertIsNotNone(self.inv.approved_at)


# ─── API integration tests ──────────────────────────────────────────────────
class SoDAPIIntegrationTests(TestCase):
    """The review + approve API endpoints must refuse SoD violations
    with 403 + sod_violation code."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="API SoD Co")
        self.maker    = _user(organization=self.org, email="m@e.com")
        self.checker  = _user(organization=self.org, email="c@e.com")
        self.approver = _user(organization=self.org, email="a@e.com",
                              role=User.Role.ADMIN)
        self.inv = Invoice.objects.create(
            organization=self.org,
            uploaded_by=self.maker,
            invoice_number="INV-API-SOD",
            vendor_name="V",
            total_amount=Decimal("500.00"),
            status=Invoice.Status.VALIDATED,
        )

    # ─── Review endpoint ───────────────────────────────────────────────────
    def test_maker_cannot_review_via_api(self):
        # Promote maker to a reviewer-capable role for this test so the
        # permission check passes; the SoD check should fail FIRST.
        self.maker.role = User.Role.SENIOR_AUDITOR
        self.maker.save(update_fields=["role"])
        self.client.force_authenticate(self.maker)
        r = self.client.post(
            f"/api/v1/invoices/{self.inv.pk}/review/",
            data={"corrections": {}, "note": "trying"},
            format="json",
        )
        self.assertEqual(r.status_code, 403, r.content)
        body = r.json()
        self.assertEqual(body["code"], "sod_violation")
        self.assertEqual(body["conflicting_with"], "maker")

    def test_checker_can_review_via_api(self):
        self.client.force_authenticate(self.checker)
        r = self.client.post(
            f"/api/v1/invoices/{self.inv.pk}/review/",
            data={"corrections": {}, "note": "looks good"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.reviewed_by_id, self.checker.id)

    # ─── Approve endpoint ─────────────────────────────────────────────────
    def test_maker_cannot_approve_via_api(self):
        self.maker.role = User.Role.ADMIN
        self.maker.save(update_fields=["role"])
        self.client.force_authenticate(self.maker)
        r = self.client.post(
            f"/api/v1/invoices/{self.inv.pk}/approve/",
            data={"action": "approve"}, format="json",
        )
        self.assertEqual(r.status_code, 403, r.content)
        body = r.json()
        self.assertEqual(body["code"], "sod_violation")

    def test_checker_cannot_approve_after_reviewing(self):
        record_review(self.inv, self.checker)
        self.checker.role = User.Role.ADMIN
        self.checker.save(update_fields=["role"])
        self.client.force_authenticate(self.checker)
        r = self.client.post(
            f"/api/v1/invoices/{self.inv.pk}/approve/",
            data={"action": "approve"}, format="json",
        )
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(r.json()["conflicting_with"], "checker")

    def test_third_user_can_approve(self):
        """The standard four-eyes happy path: Maker uploaded, Checker
        reviewed, a THIRD user approves. The approve view's risk gate
        still applies, so we don't assert HTTP 200 here — only that the
        SoD layer let the request through (i.e. we did NOT get the
        sod_violation 403)."""
        record_review(self.inv, self.checker)
        self.client.force_authenticate(self.approver)
        r = self.client.post(
            f"/api/v1/invoices/{self.inv.pk}/approve/",
            data={"action": "approve"}, format="json",
        )
        if r.status_code == 403:
            # Could be the approval-gate blocking (no audit run) — must
            # NOT be the SoD layer.
            body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
            self.assertNotEqual(body.get("code"), "sod_violation")
