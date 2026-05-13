"""Tests for the Enterprise-Audit-Review uplift (F-1 through F-10
+ ISA 540 + ISA 570 + risk matrix).

Each test maps to one Finding number from
``Docs/ENTERPRISE_AUDIT_REVIEW.md§15``.
"""
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.authentication.models import Organization


User = get_user_model()


def _user(*, organization, email="x@e.com", role=None):
    return User.objects.create_user(
        email=email, password="StrongPass123!",
        full_name="X",
        role=role or User.Role.ADMIN,
        organization=organization,
    )


# ─── F-4: file-extension allow-list ─────────────────────────────────────────
class FileExtensionAllowListTests(TestCase):
    def test_pdf_allowed_for_invoice(self):
        from core.security.upload_guard import assert_extension_allowed
        assert_extension_allowed("invoice.pdf", kind="invoice")

    def test_html_rejected_for_invoice(self):
        from core.security.upload_guard import (
            assert_extension_allowed, DisallowedExtensionError,
        )
        with self.assertRaises(DisallowedExtensionError) as cm:
            assert_extension_allowed("evil.html", kind="invoice")
        self.assertEqual(cm.exception.extension, ".html")

    def test_svg_rejected_for_invoice(self):
        from core.security.upload_guard import (
            assert_extension_allowed, DisallowedExtensionError,
        )
        with self.assertRaises(DisallowedExtensionError):
            assert_extension_allowed("logo.svg", kind="invoice")

    def test_csv_allowed_for_bank_statement(self):
        from core.security.upload_guard import is_extension_allowed
        self.assertTrue(is_extension_allowed("statement.csv", kind="bank_statement"))

    def test_ofx_allowed_for_bank_statement_not_invoice(self):
        from core.security.upload_guard import is_extension_allowed
        self.assertTrue(is_extension_allowed("statement.ofx", kind="bank_statement"))
        self.assertFalse(is_extension_allowed("statement.ofx", kind="invoice"))


# ─── F-10: SSRF outbound allow-list ─────────────────────────────────────────
class OutboundAllowListTests(TestCase):
    @override_settings(OUTBOUND_HTTP_ALLOWLIST=["api.moyasar.com", ".tap.company"])
    def test_exact_match_allowed(self):
        from core.security.outbound_guard import assert_outbound_allowed
        assert_outbound_allowed("https://api.moyasar.com/v1/payments")

    @override_settings(OUTBOUND_HTTP_ALLOWLIST=["api.moyasar.com", ".tap.company"])
    def test_subdomain_wildcard_allowed(self):
        from core.security.outbound_guard import assert_outbound_allowed
        assert_outbound_allowed("https://secure.tap.company/charges")

    @override_settings(OUTBOUND_HTTP_ALLOWLIST=["api.moyasar.com"])
    def test_off_allowlist_rejected(self):
        from core.security.outbound_guard import (
            assert_outbound_allowed, OutboundNotAllowedError,
        )
        with self.assertRaises(OutboundNotAllowedError):
            assert_outbound_allowed("https://attacker.example.com/exfil")

    @override_settings(OUTBOUND_HTTP_ALLOWLIST=["api.moyasar.com"])
    def test_private_ip_rejected(self):
        from core.security.outbound_guard import (
            assert_outbound_allowed, OutboundNotAllowedError,
        )
        with self.assertRaises(OutboundNotAllowedError):
            assert_outbound_allowed("http://127.0.0.1:8080/admin")
        with self.assertRaises(OutboundNotAllowedError):
            assert_outbound_allowed("http://10.0.0.1/")

    @override_settings(OUTBOUND_HTTP_ALLOWLIST=["api.moyasar.com"])
    def test_unsupported_scheme_rejected(self):
        from core.security.outbound_guard import (
            assert_outbound_allowed, OutboundNotAllowedError,
        )
        with self.assertRaises(OutboundNotAllowedError):
            assert_outbound_allowed("file:///etc/passwd")
        with self.assertRaises(OutboundNotAllowedError):
            assert_outbound_allowed("gopher://attacker.example.com/x")

    @override_settings(OUTBOUND_HTTP_ALLOWLIST=["*"])
    def test_star_bypasses_check(self):
        from core.security.outbound_guard import assert_outbound_allowed
        assert_outbound_allowed("https://anywhere.example.com/")


# ─── F-8: Document SHA-256 integrity ───────────────────────────────────────
class DocumentIntegrityTests(TestCase):
    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.documents.models import Document
        self.org = Organization.objects.create(name="Doc Co")
        self.doc = Document.objects.create(
            organization=self.org,
            file=SimpleUploadedFile("a.pdf", b"%PDF-1.4 contents A"),
            original_filename="a.pdf",
            file_size=19,
            mime_type="application/pdf",
        )

    def test_capture_and_verify_clean(self):
        from apps.documents.services.integrity import (
            capture_file_hash, verify_document_integrity,
        )
        h = capture_file_hash(self.doc.file)
        self.assertEqual(len(h), 64)
        self.doc.file_sha256 = h
        self.doc.save(update_fields=["file_sha256"])
        result = verify_document_integrity(self.doc)
        self.assertFalse(result.tampered)
        self.assertEqual(result.stored_hash, h)

    def test_tampered_file_is_detected(self):
        from apps.documents.services.integrity import (
            capture_file_hash, verify_document_integrity,
        )
        self.doc.file_sha256 = capture_file_hash(self.doc.file)
        self.doc.save(update_fields=["file_sha256"])
        # Tamper with the file on disk.
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.doc.file = SimpleUploadedFile("a.pdf", b"%PDF-1.4 ALTERED")
        self.doc.save(update_fields=["file"])
        # Don't update file_sha256 — that's the attacker scenario.
        result = verify_document_integrity(self.doc)
        self.assertTrue(result.tampered)

    def test_legacy_row_without_hash_backfills_on_first_verify(self):
        from apps.documents.services.integrity import verify_document_integrity
        # file_sha256 starts empty.
        result = verify_document_integrity(self.doc)
        self.assertFalse(result.tampered)
        self.doc.refresh_from_db()
        self.assertEqual(len(self.doc.file_sha256), 64)


# ─── F-3: Unified Fraud Detection Engine ───────────────────────────────────
class FraudEngineTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Fraud Co")
        from apps.invoices.models import Invoice
        self.inv = Invoice.objects.create(
            organization=self.org,
            invoice_number="INV-FE-1",
            vendor_name="Test Vendor",
            total_amount=Decimal("100"),
            risk_score=0,
        )

    def test_clean_invoice_low_score(self):
        from apps.audit.services.fraud_engine import assess_invoice
        a = assess_invoice(self.inv)
        self.assertLess(a.total_score, 50)

    def test_duplicate_invoice_drives_critical_score(self):
        from apps.audit.services.fraud_engine import assess_invoice
        original = self.inv
        from apps.invoices.models import Invoice
        dupe = Invoice.objects.create(
            organization=self.org,
            invoice_number="INV-FE-DUP",
            vendor_name="Test Vendor",
            total_amount=Decimal("100"),
            is_duplicate=True,
            duplicate_of=original,
        )
        a = assess_invoice(dupe)
        # Duplicate signal is critical (100 × 0.30 weight = 30+).
        self.assertGreater(a.total_score, 25)
        top = [s.name for s in a.top_contributors]
        self.assertIn("duplicate", top)

    def test_alterations_drive_structural_signal(self):
        from apps.audit.services.fraud_engine import assess_invoice
        from apps.invoices.models import Invoice
        bad = Invoice.objects.create(
            organization=self.org,
            invoice_number="INV-FE-STR",
            vendor_name="Test Vendor",
            total_amount=Decimal("100"),
            has_alterations=True,
            is_handwritten=True,
            ocr_confidence=30,
        )
        a = assess_invoice(bad)
        structural = next(s for s in a.signals if s.name == "structural")
        self.assertGreater(structural.score, 30)


# ─── F-1: Generic SoD ──────────────────────────────────────────────────────
class GenericSoDTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="SoD Co")
        self.maker = _user(organization=self.org, email="m@e.com")
        self.other = _user(organization=self.org, email="o@e.com")

    def test_actor_equals_maker_raises(self):
        from core.audit.sod import enforce_sod, SoDViolation
        # Mock object with created_by_id matching the actor.
        class FakeTxn: pass
        ft = FakeTxn()
        ft.created_by_id = self.maker.pk
        ft.pk = 1
        with self.assertRaises(SoDViolation) as cm:
            enforce_sod(actor=self.maker, object_=ft, stage="approve")
        self.assertEqual(cm.exception.conflicts_with, "maker")

    def test_different_actor_passes(self):
        from core.audit.sod import enforce_sod
        class FakeTxn: pass
        ft = FakeTxn()
        ft.created_by_id = self.maker.pk
        ft.pk = 1
        # Should not raise.
        enforce_sod(actor=self.other, object_=ft, stage="approve")

    def test_anonymous_actor_raises(self):
        from core.audit.sod import enforce_sod, SoDViolation
        class Anon:
            is_authenticated = False
            pk = None
        class FakeTxn:
            pk = 1
            created_by_id = None
        with self.assertRaises(SoDViolation):
            enforce_sod(actor=Anon(), object_=FakeTxn(), stage="approve")


# ─── F-2: Multi-approver threshold ─────────────────────────────────────────
class MultiApproverTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="MA Co")
        self.admin_a = _user(organization=self.org, email="a@e.com")
        self.admin_b = _user(organization=self.org, email="b@e.com")
        from apps.invoices.models import Invoice
        self.big = Invoice.objects.create(
            organization=self.org, vendor_name="Big Vendor",
            total_amount=Decimal("250000"), invoice_number="INV-MA-BIG",
        )
        self.small = Invoice.objects.create(
            organization=self.org, vendor_name="Small Vendor",
            total_amount=Decimal("500"), invoice_number="INV-MA-SMALL",
        )

    @override_settings(APPROVAL_OVERRIDE_THRESHOLD_SAR="100000")
    def test_requires_countersign_above_threshold(self):
        from apps.invoices.services.multi_approver import requires_countersign
        self.assertTrue(requires_countersign(self.big))
        self.assertFalse(requires_countersign(self.small))

    @override_settings(APPROVAL_OVERRIDE_THRESHOLD_SAR="100000")
    def test_open_and_countersign_happy_path(self):
        from apps.invoices.services.multi_approver import (
            open_override_request, countersign,
        )
        ovr = open_override_request(
            self.big, requested_by=self.admin_a, reason="ZATCA reconciliation",
        )
        self.assertEqual(ovr.status, "pending")
        signed = countersign(ovr.id, actor=self.admin_b)
        self.assertEqual(signed.status, "countersigned")
        self.assertEqual(signed.countersigned_by_id, self.admin_b.id)

    @override_settings(APPROVAL_OVERRIDE_THRESHOLD_SAR="100000")
    def test_same_admin_cannot_countersign_own_request(self):
        from apps.invoices.services.multi_approver import (
            open_override_request, countersign,
        )
        ovr = open_override_request(
            self.big, requested_by=self.admin_a, reason="x",
        )
        with self.assertRaises(PermissionError):
            countersign(ovr.id, actor=self.admin_a)

    @override_settings(APPROVAL_OVERRIDE_THRESHOLD_SAR="100000")
    def test_below_threshold_refuses_to_open_request(self):
        from apps.invoices.services.multi_approver import open_override_request
        with self.assertRaises(ValueError):
            open_override_request(
                self.small, requested_by=self.admin_a, reason="x",
            )


# ─── ISA 540: Accounting Estimates ─────────────────────────────────────────
class ISA540EstimatesTests(TestCase):
    def test_low_risk_estimate_score_below_25(self):
        from apps.audit.services.estimates import (
            EstimateProfile, assess_estimation_uncertainty,
        )
        p = EstimateProfile(
            name="Useful life of office printers",
            category="depreciation",
            management_estimate=Decimal("10000"),
            estimation_method="point",
            complexity=1, subjectivity=1, estimation_uncertainty=1,
            relies_on_external_data=False,
            prior_period_misstatement=False,
            disclosure_quality=5,
        )
        a = assess_estimation_uncertainty(p)
        self.assertLess(a.uncertainty_score, 25)
        self.assertEqual(a.severity, "low")

    def test_complex_estimate_triggers_significant_risk(self):
        from apps.audit.services.estimates import (
            EstimateProfile, assess_estimation_uncertainty,
        )
        p = EstimateProfile(
            name="Expected credit losses (IFRS 9)",
            category="ecl",
            management_estimate=Decimal("5000000"),
            estimation_method="model_based",
            complexity=5, subjectivity=5, estimation_uncertainty=5,
            relies_on_external_data=True,
            prior_period_misstatement=True,
            disclosure_quality=2,
        )
        a = assess_estimation_uncertainty(p)
        self.assertGreaterEqual(a.uncertainty_score, 75)
        self.assertEqual(a.severity, "significant_risk")
        # ISA 540 R.20 — extended audit procedures required
        self.assertTrue(any("model" in d for d in a.drivers))

    def test_auditor_range_widens_to_materiality(self):
        from apps.audit.services.estimates import (
            EstimateProfile, flag_estimates,
        )
        p = EstimateProfile(
            name="Inventory obsolescence",
            category="provision",
            management_estimate=Decimal("1000000"),
            estimation_method="point",
            complexity=3, subjectivity=3, estimation_uncertainty=3,
            relies_on_external_data=False,
            prior_period_misstatement=False,
            disclosure_quality=4,
        )
        results = flag_estimates(
            [p],
            performance_materiality=Decimal("50000"),
            sensitivity_pct=Decimal("0.10"),
        )
        self.assertTrue(results[0].exceeds_materiality)
        # ± 10% of 1m = 100k width > 50k materiality


# ─── ISA 570: Going Concern ────────────────────────────────────────────────
class ISA570GoingConcernTests(TestCase):
    def test_no_indicators_yields_no_doubt(self):
        from apps.audit.services.going_concern import (
            GoingConcernIndicators, assess_going_concern,
        )
        a = assess_going_concern(GoingConcernIndicators())
        self.assertEqual(a.severity, "no_doubt")
        self.assertEqual(a.recommended_opinion_modification, "Unmodified opinion.")

    def test_intention_to_liquidate_makes_gc_inappropriate(self):
        from apps.audit.services.going_concern import (
            GoingConcernIndicators, assess_going_concern,
        )
        a = assess_going_concern(GoingConcernIndicators(intention_to_liquidate=True))
        self.assertEqual(a.severity, "going_concern_inappropriate")
        self.assertIn("Adverse opinion", a.recommended_opinion_modification)

    def test_heavy_indicator_without_mitigant_is_material_uncertainty(self):
        from apps.audit.services.going_concern import (
            GoingConcernIndicators, assess_going_concern,
        )
        a = assess_going_concern(GoingConcernIndicators(
            net_liability_position=True,
            inability_to_pay_creditors=True,
        ))
        self.assertEqual(a.severity, "material_uncertainty")
        self.assertIn("Material Uncertainty", a.recommended_opinion_modification)

    def test_heavy_indicator_with_credible_plan_and_mitigant_doubt_mitigated(self):
        from apps.audit.services.going_concern import (
            GoingConcernIndicators, assess_going_concern,
        )
        a = assess_going_concern(GoingConcernIndicators(
            net_liability_position=True,
            mgmt_has_credible_recovery_plan=True,
            refinancing_secured=True,
        ))
        self.assertEqual(a.severity, "doubt_mitigated")
        self.assertIn("emphasis-of-matter", a.recommended_opinion_modification.lower())


# ─── Risk matrix builder ──────────────────────────────────────────────────
class RiskMatrixTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="RM Co")

    def test_low_risk_low_amount_lands_low_low(self):
        from apps.invoices.models import Invoice
        from apps.audit.services.risk_matrix import build_invoice_risk_matrix
        inv = Invoice.objects.create(
            organization=self.org, invoice_number="INV-RM-1",
            vendor_name="V", total_amount=Decimal("100"),
            risk_score=5,
        )
        m = build_invoice_risk_matrix([inv], materiality=Decimal("50000"))
        # Should land in rare × insignificant cell.
        cell = next(c for c in m["cells"]
                    if c["likelihood"] == "rare" and c["impact"] == "insignificant")
        self.assertEqual(cell["count"], 1)
        self.assertEqual(cell["severity"], "low")

    def test_high_risk_high_amount_lands_critical(self):
        from apps.invoices.models import Invoice
        from apps.audit.services.risk_matrix import build_invoice_risk_matrix
        inv = Invoice.objects.create(
            organization=self.org, invoice_number="INV-RM-2",
            vendor_name="V", total_amount=Decimal("2000000"),
            risk_score=90,
        )
        m = build_invoice_risk_matrix([inv], materiality=Decimal("50000"))
        cell = next(c for c in m["cells"]
                    if c["likelihood"] == "almost_certain" and c["impact"] == "severe")
        self.assertEqual(cell["count"], 1)
        self.assertEqual(cell["severity"], "critical")
        self.assertEqual(m["totals"]["by_severity"]["critical"], 1)


# ─── F-5: Nightly chain verify ────────────────────────────────────────────
class ChainVerifyNightlyTests(TestCase):
    def test_task_returns_summary_dict(self):
        from apps.audit.tasks_chain_verify import verify_chains_nightly
        # No orgs / no chained rows → should complete with checked=0.
        result = verify_chains_nightly()
        self.assertIn("checked", result)
        self.assertIn("intact", result)
        self.assertIn("broken", result)
        self.assertEqual(result["broken"], 0)
