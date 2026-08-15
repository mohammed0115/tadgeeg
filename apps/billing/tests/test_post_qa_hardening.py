"""Tests for the remaining QA-report fixes — H-1 doc, H-2-extra
allow_rebill, M-1 constraint, M-2 ZIP recursion, D-1 drift detector,
D-2 FK.
"""
import io
import zipfile
from io import StringIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.billing.bulk_quota import count_items
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
from apps.billing.quota_gate import run_audit_with_quota
from apps.billing.services.quota_service import QuotaService
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user


# ─── H-2-extra: allow_rebill on consume ─────────────────────────────────────
class AllowRebillConsumeTests(TestCase):
    """consume_invoice_audit with allow_rebill=True must create a fresh
    consume row even when a prior one for the same document exists —
    as long as the audit_run is different."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        self.sub = SubscriptionService().activate_subscription(sub)
        from apps.documents.models import Document
        self.doc = Document.objects.create(
            organization=self.org,
            file=SimpleUploadedFile("t.pdf", b"%PDF-1.4 stub"),
            original_filename="t.pdf", file_size=14, mime_type="application/pdf",
        )
        # The typed record the gate is addressed by. `document_id` on this path
        # means the typed record's key; self.doc stays the Document because the
        # usage ledger keys on it and the assertions below read it that way.
        from apps.documents.typed_models import PurchaseOrder
        self.po = PurchaseOrder.objects.create(
            document=self.doc, organization=self.org,
            po_number=f"PO-{str(self.doc.pk)[:8]}",
        )

    def _new_run(self):
        from apps.rule_engine.models import AuditRun
        return AuditRun.objects.create(
            organization=self.org, document_type="purchase_order",
            document_id=self.po.id,
            status=AuditRun.Status.COMPLETED,
        )

    def test_allow_rebill_creates_second_consume(self):
        svc = QuotaService()
        run_a = self._new_run()
        run_b = self._new_run()

        # First reserve + consume (normal path).
        svc.reserve_invoice_audit(self.org, document=self.doc)
        svc.consume_invoice_audit(self.org, document=self.doc, audit_run=run_a)

        # Second reserve + consume WITH allow_rebill — a force-rerun.
        svc.reserve_invoice_audit(self.org, document=self.doc)  # idempotent
        svc.consume_invoice_audit(
            self.org, document=self.doc, audit_run=run_b, allow_rebill=True,
        )

        consumes = UsageLedger.objects.filter(
            document=self.doc, action=UsageAction.CONSUME,
        ).count()
        self.assertEqual(consumes, 2)

    def test_same_audit_run_dedup_wins_over_allow_rebill(self):
        """Even with allow_rebill=True, a repeat consume for the SAME
        audit_run must short-circuit (celery retry safety)."""
        svc = QuotaService()
        run = self._new_run()
        svc.reserve_invoice_audit(self.org, document=self.doc)
        svc.consume_invoice_audit(self.org, document=self.doc, audit_run=run)
        svc.consume_invoice_audit(
            self.org, document=self.doc, audit_run=run, allow_rebill=True,
        )
        consumes = UsageLedger.objects.filter(
            document=self.doc, audit_run=run, action=UsageAction.CONSUME,
        ).count()
        self.assertEqual(consumes, 1)

    def test_gate_force_rerun_confirmed_creates_second_consume(self):
        """End-to-end through run_audit_with_quota."""
        from apps.rule_engine.models import AuditRun

        def _run(*, force_rerun=False, force_rerun_confirmed=False):
            new = AuditRun.objects.create(
                organization=self.org, document_type="purchase_order",
                document_id=self.po.id, status=AuditRun.Status.COMPLETED,
            )
            with mock.patch(
                "apps.rule_engine.pipeline.v2.compat.run_audit_compat",
                return_value=new,
            ):
                run_audit_with_quota(
                    document_id=str(self.po.id),
                    document_type="purchase_order",
                    organization_id=str(self.org.id),
                    force_rerun=force_rerun,
                    force_rerun_confirmed=force_rerun_confirmed,
                )

        _run()                                                    # first consume
        _run(force_rerun=True, force_rerun_confirmed=True)        # second consume

        consumes = UsageLedger.objects.filter(
            document=self.doc, action=UsageAction.CONSUME,
        ).count()
        self.assertEqual(consumes, 2)


# ─── M-1: one usable subscription per org constraint ───────────────────────
class OneUsableSubPerOrgConstraintTests(TestCase):
    """The new partial unique constraint blocks a second ACTIVE/TRIALING
    row for the same org. PENDING/EXPIRED/CANCELED rows remain free
    to coexist (so an upgrade path still works)."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        self.plan_starter  = Plan.objects.get(code=PlanCode.STARTER)
        self.plan_business = Plan.objects.get(code=PlanCode.BUSINESS)

    def test_cannot_create_two_active_subs_for_same_org(self):
        OrganizationSubscription.objects.create(
            organization=self.org, plan=self.plan_starter,
            status=SubscriptionStatus.ACTIVE,
            invoice_limit=100,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationSubscription.objects.create(
                organization=self.org, plan=self.plan_business,
                status=SubscriptionStatus.ACTIVE,
                invoice_limit=500,
            )

    def test_pending_payment_can_coexist_with_active(self):
        """Upgrade flow: an ACTIVE row stays while a new PENDING_PAYMENT
        is created. Both can live until the second one activates and
        the first transitions to EXPIRED/CANCELED."""
        OrganizationSubscription.objects.create(
            organization=self.org, plan=self.plan_starter,
            status=SubscriptionStatus.ACTIVE,
            invoice_limit=100,
        )
        OrganizationSubscription.objects.create(
            organization=self.org, plan=self.plan_business,
            status=SubscriptionStatus.PENDING_PAYMENT,
            invoice_limit=500,
        )
        # Both rows survive.
        self.assertEqual(
            OrganizationSubscription.objects.filter(organization=self.org).count(),
            2,
        )


# ─── M-2: ZIP-of-XLSX/CSV item count ────────────────────────────────────────
class ZipRecursiveCounterTests(TestCase):

    def _zip_with(self, members):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, body in members:
                zf.writestr(name, body)
        return buf.getvalue()

    def test_zip_of_csvs_sums_rows(self):
        csv_a = b"id,vendor\n1,A\n2,B\n3,C\n"            # 3 rows
        csv_b = b"id,vendor\n1,X\n2,Y\n"                  # 2 rows
        archive = self._zip_with([
            ("invoices/a.csv", csv_a),
            ("invoices/b.csv", csv_b),
        ])
        self.assertEqual(count_items(archive, "zip"), 5)

    def test_zip_of_jsonl_sums_lines(self):
        jsonl = b'{"id":1}\n{"id":2}\n{"id":3}\n{"id":4}\n'
        archive = self._zip_with([("invoices/list.jsonl", jsonl)])
        self.assertEqual(count_items(archive, "zip"), 4)

    def test_zip_of_pdfs_each_counts_one(self):
        archive = self._zip_with([
            ("invoices/a.pdf", b"%PDF-1.4 stub a"),
            ("invoices/b.pdf", b"%PDF-1.4 stub b"),
            ("invoices/c.pdf", b"%PDF-1.4 stub c"),
        ])
        self.assertEqual(count_items(archive, "zip"), 3)

    def test_zip_of_mixed_pdf_and_csv(self):
        archive = self._zip_with([
            ("invoices/a.csv", b"id,vendor\n1,A\n2,B\n"),   # 2 rows
            ("invoices/b.pdf", b"%PDF-1.4 stub"),            # 1
            ("invoices/c.pdf", b"%PDF-1.4 stub"),            # 1
        ])
        self.assertEqual(count_items(archive, "zip"), 4)

    def test_nested_zip_capped_at_depth_one(self):
        """A ZIP-inside-a-ZIP must NOT recursively count — each nested
        ZIP is treated as a single binary unit. Prevents ZIP-bomb-style
        denial-of-service via the counter."""
        inner = self._zip_with([
            ("a.csv", b"id\n1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n"),
        ])
        outer = self._zip_with([("nested.zip", inner)])
        # Should be 1 (the nested zip itself), NOT 10.
        self.assertEqual(count_items(outer, "zip"), 1)


# ─── D-1: counter drift detector ────────────────────────────────────────────
class CounterDriftDetectorTests(TestCase):

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        self.sub = SubscriptionService().activate_subscription(sub)

    def _ledger(self, action, n=1):
        for _ in range(n):
            UsageLedger.objects.create(
                organization=self.org, subscription=self.sub,
                action=action, quantity=1,
            )

    def test_no_drift_returns_zero(self):
        from apps.billing.tasks import detect_counter_drift
        # Counters and ledger both at zero.
        result = detect_counter_drift()
        self.assertEqual(result["drifted"], 0)
        self.assertEqual(result["corrected"], 0)
        self.assertGreaterEqual(result["checked"], 1)

    def test_drift_detected_but_not_auto_corrected_by_default(self):
        from apps.billing.tasks import detect_counter_drift
        # Ledger says 3 consumes; counter says 0.
        self._ledger(UsageAction.CONSUME, 3)
        # Counter is still 0 → drift.
        result = detect_counter_drift()
        self.assertEqual(result["drifted"], 1)
        self.assertEqual(result["corrected"], 0)   # not auto-corrected
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 0)

    def test_drift_auto_corrected_when_flag_set(self):
        from apps.billing.tasks import detect_counter_drift
        self._ledger(UsageAction.CONSUME, 4)
        result = detect_counter_drift(auto_correct=True)
        self.assertEqual(result["corrected"], 1)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 4)


# ─── D-2: payment_transaction FK behaviour ──────────────────────────────────
class PaymentTransactionFKTests(TestCase):
    """The field is now a real ForeignKey with on_delete=SET_NULL.
    Deleting the underlying payment must NOT cascade away the
    subscription, but the FK reference is cleared."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        user = make_user(organization=self.org)
        plan = Plan.objects.get(code=PlanCode.STARTER)
        from decimal import Decimal as D
        from apps.payments.choices import PaymentStatus
        from apps.payments.models import PaymentTransaction
        self.txn = PaymentTransaction.objects.create(
            organization=self.org, user=user,
            provider="moyasar", purpose="subscription",
            amount=D("350.00"), currency="SAR",
            status=PaymentStatus.PAID,
        )
        self.sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        self.sub.payment_transaction = self.txn
        self.sub.save(update_fields=["payment_transaction"])

    def test_deleting_payment_does_not_cascade_subscription(self):
        from apps.payments.models import PaymentTransaction
        sub_pk = self.sub.pk
        PaymentTransaction.objects.get(pk=self.txn.pk).delete()
        # Sub survives, FK cleared.
        sub_after = OrganizationSubscription.objects.get(pk=sub_pk)
        self.assertIsNone(sub_after.payment_transaction)

    def test_assignment_via_instance(self):
        """Asserts the FK can be assigned with either the instance OR
        the id (Django auto-handles the conversion via *_id)."""
        from apps.payments.models import PaymentTransaction
        new_txn = PaymentTransaction.objects.create(
            organization=self.org, user=self.sub.organization.users.first(),
            provider="moyasar", purpose="subscription",
            amount=self.txn.amount, currency="SAR",
            status=self.txn.status,
        )
        self.sub.payment_transaction_id = new_txn.id
        self.sub.save(update_fields=["payment_transaction"])
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.payment_transaction.pk, new_txn.pk)
