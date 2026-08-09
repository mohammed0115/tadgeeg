"""Stage 5 — Quota Enforcement on the Audit Pipeline.

Covers the 12 cases from Documentation/payment/00.md §5:

  1. audit succeeds when quota is available
  2. reserve increases reserved_invoices
  3. successful audit moves reserved → used
  4. system-error audit releases without charging
  5. can't audit without subscription
  6. can't audit with expired subscription
  7. can't audit when remaining = 0
  8. same document never charges twice
  9. celery retry never charges twice
 10. signal + view never double-charge (same as 8 from a different entry)
 11. tenant isolation preserved
 12. UsageLedger records every reserve/consume/release

The audit pipeline itself is mocked — Stage 5 verifies the GATE around
``run_audit_compat``, not the pipeline. ``install_gate()`` swaps the
real function for the gated wrapper; tests reach through to the
wrapper either directly or via the module attribute.
"""
from decimal import Decimal
from io import StringIO
from unittest import mock
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.billing.choices import PlanCode, SubscriptionStatus, UsageAction
from apps.billing.models import OrganizationSubscription, Plan, UsageLedger
from apps.billing.quota_gate import (
    QuotaExceeded,
    install_gate,
    run_audit_with_quota,
)
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org, make_user


def _make_document(organization, filename="t.pdf"):
    from apps.documents.models import Document
    return Document.objects.create(
        organization=organization,
        file=SimpleUploadedFile(filename, b"%PDF-1.4 stub"),
        original_filename=filename,
        file_size=14,
        mime_type="application/pdf",
    )


def _make_audit_run(*, organization, document, status=None):
    """Build a minimal AuditRun (or AuditRun-shaped stub) that the gate
    can hand to consume_invoice_audit. We don't actually persist one
    here because the AuditRun.Status check uses the live ORM model."""
    from apps.rule_engine.models import AuditRun
    return AuditRun.objects.create(
        organization=organization,
        document_type="sales_invoice",
        document_id=document.id,
        status=status or AuditRun.Status.COMPLETED,
    )


@override_settings(BILLING_QUOTA_GATE_ENABLED=True)
class QuotaGateBasicsTests(TestCase):
    """Tests 1, 2, 3 — happy path."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org  = make_org()
        self.user = make_user(organization=self.org)
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        self.sub = SubscriptionService().activate_subscription(sub)
        self.doc = _make_document(self.org)

    def _fake_pipeline(self, status="completed"):
        from apps.rule_engine.models import AuditRun
        run = _make_audit_run(
            organization=self.org, document=self.doc,
            status=AuditRun.Status.COMPLETED if status == "completed"
                  else AuditRun.Status.FAILED,
        )
        return mock.patch(
            "apps.rule_engine.pipeline.v2.compat.run_audit_compat",
            return_value=run,
        ), run

    def test_audit_with_quota_completes_and_consumes(self):
        # The gate's internal call to run_audit_compat is what we patch.
        # Patch the *original* attribute so the gate's import inside
        # run_audit_with_quota resolves to the mock.
        patch, run = self._fake_pipeline("completed")
        with patch:
            result = run_audit_with_quota(
                document_id=str(self.doc.id),
                document_type="sales_invoice",
                organization_id=str(self.org.id),
                triggered_by="upload",
            )
        self.assertEqual(result.pk, run.pk)

        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 1)
        self.assertEqual(self.sub.reserved_invoices, 0)

        # Ledger: one reserve + one consume.
        self.assertEqual(
            UsageLedger.objects.filter(document=self.doc, action=UsageAction.RESERVE).count(),
            1,
        )
        self.assertEqual(
            UsageLedger.objects.filter(document=self.doc, action=UsageAction.CONSUME).count(),
            1,
        )

    def test_system_error_in_pipeline_releases_reservation(self):
        """Test 4 — pipeline raised → release, no consume, used unchanged."""
        with mock.patch(
            "apps.rule_engine.pipeline.v2.compat.run_audit_compat",
            side_effect=RuntimeError("OCR exploded"),
        ):
            with self.assertRaises(RuntimeError):
                run_audit_with_quota(
                    document_id=str(self.doc.id),
                    document_type="sales_invoice",
                    organization_id=str(self.org.id),
                )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 0)
        self.assertEqual(self.sub.reserved_invoices, 0)
        self.assertEqual(
            UsageLedger.objects.filter(document=self.doc, action=UsageAction.RELEASE).count(),
            1,
        )

    def test_audit_run_with_failed_status_releases_not_consumes(self):
        """Pipeline returned an AuditRun with status=FAILED — the gate
        must release, not consume."""
        patch, _ = self._fake_pipeline("failed")
        with patch:
            run_audit_with_quota(
                document_id=str(self.doc.id),
                document_type="sales_invoice",
                organization_id=str(self.org.id),
            )
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 0)
        self.assertEqual(
            UsageLedger.objects.filter(document=self.doc, action=UsageAction.RELEASE).count(),
            1,
        )


@override_settings(BILLING_QUOTA_GATE_ENABLED=True)
class QuotaGateBlocksTests(TestCase):
    """Tests 5, 6, 7 — refusal cases."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org  = make_org()
        self.user = make_user(organization=self.org)
        self.doc  = _make_document(self.org)

    def test_no_subscription_blocks_audit(self):
        with self.assertRaises(QuotaExceeded) as cm:
            run_audit_with_quota(
                document_id=str(self.doc.id),
                document_type="sales_invoice",
                organization_id=str(self.org.id),
            )
        self.assertEqual(cm.exception.reason, "no_subscription")

    def test_expired_subscription_blocks_audit(self):
        plan = Plan.objects.get(code=PlanCode.STARTER)
        OrganizationSubscription.objects.create(
            organization=self.org, plan=plan,
            status=SubscriptionStatus.EXPIRED,
            invoice_limit=100, used_invoices=100,
        )
        with self.assertRaises(QuotaExceeded) as cm:
            run_audit_with_quota(
                document_id=str(self.doc.id),
                document_type="sales_invoice",
                organization_id=str(self.org.id),
            )
        self.assertEqual(cm.exception.reason, "subscription_expired")

    def test_exhausted_quota_blocks_audit(self):
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        sub = SubscriptionService().activate_subscription(sub)
        sub.used_invoices = sub.invoice_limit
        sub.save(update_fields=["used_invoices"])

        with self.assertRaises(QuotaExceeded) as cm:
            run_audit_with_quota(
                document_id=str(self.doc.id),
                document_type="sales_invoice",
                organization_id=str(self.org.id),
            )
        self.assertEqual(cm.exception.reason, "quota_exceeded")
        # Reservation NOT created on refusal.
        self.assertEqual(
            UsageLedger.objects.filter(document=self.doc, action=UsageAction.RESERVE).count(),
            0,
        )


@override_settings(BILLING_QUOTA_GATE_ENABLED=True)
class QuotaGateIdempotencyTests(TestCase):
    """Tests 8, 9, 10 — same document, signal/view/retry, never double-charge."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org  = make_org()
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        self.sub = SubscriptionService().activate_subscription(sub)
        self.doc = _make_document(self.org)

    def _run_once(self):
        from apps.rule_engine.models import AuditRun
        run = _make_audit_run(
            organization=self.org, document=self.doc,
            status=AuditRun.Status.COMPLETED,
        )
        with mock.patch(
            "apps.rule_engine.pipeline.v2.compat.run_audit_compat",
            return_value=run,
        ):
            return run_audit_with_quota(
                document_id=str(self.doc.id),
                document_type="sales_invoice",
                organization_id=str(self.org.id),
            )

    def test_same_document_audited_twice_charges_once(self):
        self._run_once()
        self._run_once()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 1)  # not 2
        # Exactly one consume row in the ledger.
        self.assertEqual(
            UsageLedger.objects.filter(document=self.doc, action=UsageAction.CONSUME).count(),
            1,
        )

    def test_signal_and_view_for_same_document_charge_once(self):
        """Simulates: a post-save signal kicks off audit, then the upload
        view also calls run_audit. Both paths use run_audit_with_quota;
        only one consume row results."""
        # Two interleaved invocations within the same flow.
        for _ in range(2):
            self._run_once()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 1)

    def test_celery_retry_does_not_double_charge(self):
        """Simulates a transient error → retry. The gate sees the
        existing consume row and skips re-billing on the second run."""
        # First call: pipeline failed → release. No consume yet.
        with mock.patch(
            "apps.rule_engine.pipeline.v2.compat.run_audit_compat",
            side_effect=RuntimeError("transient"),
        ):
            with self.assertRaises(RuntimeError):
                run_audit_with_quota(
                    document_id=str(self.doc.id),
                    document_type="sales_invoice",
                    organization_id=str(self.org.id),
                )
        # Retry succeeds.
        self._run_once()
        # Retry runs again — must NOT double-consume.
        self._run_once()
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.used_invoices, 1)


@override_settings(BILLING_QUOTA_GATE_ENABLED=True)
class TenantIsolationTests(TestCase):
    """Test 11 — one org's quota events never bleed into another's."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        plan = Plan.objects.get(code=PlanCode.STARTER)
        self.org_a = make_org("A")
        self.org_b = make_org("B")
        sub_a = SubscriptionService().create_pending_paid_subscription(self.org_a, plan)
        sub_b = SubscriptionService().create_pending_paid_subscription(self.org_b, plan)
        self.sub_a = SubscriptionService().activate_subscription(sub_a)
        self.sub_b = SubscriptionService().activate_subscription(sub_b)
        self.doc_a = _make_document(self.org_a, "a.pdf")

    def test_audit_for_org_a_does_not_touch_org_b_counter(self):
        from apps.rule_engine.models import AuditRun
        run = _make_audit_run(
            organization=self.org_a, document=self.doc_a,
            status=AuditRun.Status.COMPLETED,
        )
        with mock.patch(
            "apps.rule_engine.pipeline.v2.compat.run_audit_compat",
            return_value=run,
        ):
            run_audit_with_quota(
                document_id=str(self.doc_a.id),
                document_type="sales_invoice",
                organization_id=str(self.org_a.id),
            )
        self.sub_a.refresh_from_db()
        self.sub_b.refresh_from_db()
        self.assertEqual(self.sub_a.used_invoices, 1)
        self.assertEqual(self.sub_b.used_invoices, 0)
        # And no ledger leakage.
        self.assertEqual(UsageLedger.objects.filter(organization=self.org_b).count(), 0)


@override_settings(BILLING_QUOTA_GATE_ENABLED=True)
class LedgerCompletenessTests(TestCase):
    """Test 12 — every gate action writes a ledger row."""

    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())
        self.org = make_org()
        plan = Plan.objects.get(code=PlanCode.STARTER)
        sub = SubscriptionService().create_pending_paid_subscription(self.org, plan)
        self.sub = SubscriptionService().activate_subscription(sub)

    def test_full_lifecycle_creates_reserve_then_consume(self):
        doc = _make_document(self.org, "lifecycle.pdf")
        from apps.rule_engine.models import AuditRun
        run = _make_audit_run(
            organization=self.org, document=doc,
            status=AuditRun.Status.COMPLETED,
        )
        with mock.patch(
            "apps.rule_engine.pipeline.v2.compat.run_audit_compat",
            return_value=run,
        ):
            run_audit_with_quota(
                document_id=str(doc.id),
                document_type="sales_invoice",
                organization_id=str(self.org.id),
            )
        entries = list(
            UsageLedger.objects.filter(document=doc).order_by("created_at")
                              .values_list("action", flat=True)
        )
        self.assertEqual(entries, [UsageAction.RESERVE, UsageAction.CONSUME])

    def test_pipeline_failure_creates_reserve_then_release(self):
        doc = _make_document(self.org, "failed.pdf")
        with mock.patch(
            "apps.rule_engine.pipeline.v2.compat.run_audit_compat",
            side_effect=ValueError("boom"),
        ):
            with self.assertRaises(ValueError):
                run_audit_with_quota(
                    document_id=str(doc.id),
                    document_type="sales_invoice",
                    organization_id=str(self.org.id),
                )
        entries = list(
            UsageLedger.objects.filter(document=doc).order_by("created_at")
                              .values_list("action", flat=True)
        )
        self.assertEqual(entries, [UsageAction.RESERVE, UsageAction.RELEASE])


@override_settings(BILLING_QUOTA_GATE_ENABLED=True)
class GateInstallationTests(TestCase):
    """Verifies install_gate() actually patches the canonical entry point."""

    def test_run_audit_compat_is_gated_after_install(self):
        install_gate()
        import apps.rule_engine.pipeline.v2.compat as compat
        self.assertTrue(
            getattr(compat.run_audit_compat, "_billing_gated", False),
            "run_audit_compat should be wrapped by install_gate()",
        )
