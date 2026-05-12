"""Tests #8–#13: QuotaService can_audit / reserve / consume / release
+ race-condition coverage."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db.models.query import QuerySet
from django.test import TestCase

from apps.billing.choices import (
    PlanCode,
    SubscriptionStatus,
    UsageAction,
)
from apps.billing.models import (
    OrganizationSubscription,
    Plan,
    UsageLedger,
)
from apps.billing.services.quota_service import (
    QuotaExceeded,
    QuotaService,
)
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org


class QuotaServiceBasicsTests(TestCase):
    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org  = make_org()
        self.svc  = QuotaService()
        self.starter = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, self.starter)
        self.sub = SubscriptionService().activate_subscription(sub)

    # ---- can_audit ----

    def test_can_audit_true_when_quota_available(self):
        d = self.svc.can_audit(self.org)
        self.assertTrue(d["allowed"])
        self.assertEqual(d["remaining"], 100)

    def test_can_audit_false_when_quota_exhausted(self):
        self.sub.used_invoices = 100
        self.sub.save(update_fields=["used_invoices"])
        d = self.svc.can_audit(self.org)
        self.assertFalse(d["allowed"])
        self.assertEqual(d["reason"], "quota_exceeded")
        self.assertEqual(d["remaining"], 0)

    def test_can_audit_false_when_no_subscription(self):
        no_sub_org = make_org("No Sub Org")
        d = self.svc.can_audit(no_sub_org)
        self.assertFalse(d["allowed"])
        self.assertEqual(d["reason"], "no_subscription")

    # ---- reserve / consume / release ----

    def test_reserve_increases_reserved_invoices(self):
        self.svc.reserve_invoice_audit(self.org)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.reserved_invoices, 1)
        self.assertEqual(self.sub.used_invoices, 0)
        self.assertEqual(
            UsageLedger.objects.filter(organization=self.org, action=UsageAction.RESERVE).count(),
            1,
        )

    def test_consume_moves_reserved_into_used(self):
        self.svc.reserve_invoice_audit(self.org)
        self.svc.consume_invoice_audit(self.org)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.reserved_invoices, 0)
        self.assertEqual(self.sub.used_invoices, 1)
        self.assertEqual(
            UsageLedger.objects.filter(organization=self.org, action=UsageAction.CONSUME).count(),
            1,
        )

    def test_release_drops_reserved_without_consuming(self):
        self.svc.reserve_invoice_audit(self.org)
        self.svc.release_invoice_audit(self.org, reason="audit system error")
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.reserved_invoices, 0)
        self.assertEqual(self.sub.used_invoices, 0)
        self.assertEqual(
            UsageLedger.objects.filter(organization=self.org, action=UsageAction.RELEASE).count(),
            1,
        )

    def test_reserve_refuses_when_quota_full(self):
        self.sub.used_invoices = 100
        self.sub.save(update_fields=["used_invoices"])
        with self.assertRaises(QuotaExceeded):
            self.svc.reserve_invoice_audit(self.org)

    def test_reserve_uses_select_for_update_on_subscription(self):
        """Race-condition guard: reserve must take a row lock on the
        subscription before mutating counters. We verify by wrapping
        the QuerySet method and asserting it was called at least once
        during the reserve call."""
        original = QuerySet.select_for_update
        seen = {"called": False}

        def spy(self, *args, **kwargs):
            seen["called"] = True
            return original(self, *args, **kwargs)

        with mock.patch.object(QuerySet, "select_for_update", new=spy):
            self.svc.reserve_invoice_audit(self.org)

        self.assertTrue(
            seen["called"],
            "reserve_invoice_audit must take a row lock via select_for_update()",
        )


class QuotaIdempotencyTests(TestCase):
    """Repeated reserve/consume/release on the same document must not
    multi-count quota."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        self.svc = QuotaService()
        starter = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, starter)
        self.sub = SubscriptionService().activate_subscription(sub)

    def _make_document(self):
        """Helper — billing tests don't need a real Document, but
        UsageLedger.document FK constrains us to a real row.
        Stage 5 will hook this up properly."""
        from apps.documents.models import Document
        from django.core.files.uploadedfile import SimpleUploadedFile
        return Document.objects.create(
            organization=self.org,
            file=SimpleUploadedFile("test.pdf", b"%PDF-1.4 stub"),
            original_filename="test.pdf",
            file_size=14,
            mime_type="application/pdf",
        )

    def test_double_reserve_on_same_document_is_a_noop(self):
        doc = self._make_document()
        self.svc.reserve_invoice_audit(self.org, document=doc)
        self.svc.reserve_invoice_audit(self.org, document=doc)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.reserved_invoices, 1)  # not 2

    def test_double_consume_on_same_document_is_a_noop(self):
        doc = self._make_document()
        self.svc.reserve_invoice_audit(self.org, document=doc)
        self.svc.consume_invoice_audit(self.org, document=doc)
        self.svc.consume_invoice_audit(self.org, document=doc)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 1)  # not 2
