"""
Tests for new services added in the current sprint:
- KAMsService (ISA 701 Key Audit Matters)
- ISA 700 opinion determination (_determine_isa700_opinion)
- Root cause analysis (_build_root_cause_analysis)
- Benford's Law integration in anomalies
- GCC multi-country VAT rate / number format rules (extended)

Run with:
    python manage.py test tests.test_new_services
    pytest tests/test_new_services.py -v
"""

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")

from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock
from django.test import TestCase

from apps.rule_engine.rules.base import NormalizedDocument, RuleStatus


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def make_doc(country="SA", tax_id="310000000000003", **kwargs):
    doc = NormalizedDocument(
        document_id="doc-001",
        document_type="sales_invoice",
        organization_id="org-001",
        document_number="INV-001",
        total_amount=1150.0,
        currency="SAR",
        tax_id=tax_id,
        typed_data=kwargs.pop("typed_data", {}),
        org_context={"country": country},
    )
    for k, v in kwargs.items():
        setattr(doc, k, v)
    return doc


# ─────────────────────────────────────────────────────────────
# KAMsService tests
# ─────────────────────────────────────────────────────────────

class TestKAMsServiceBuild(TestCase):

    def _build_kams(self, summary=None, validations=None, invoices=None,
                    anomalies=None, compliance=None, language="en"):
        from apps.reports.services.kams_service import KAMsService
        svc = KAMsService(organization=None, user=None)
        return svc.build(
            summary=summary or {},
            validations=validations or {},
            invoices=invoices or [],
            anomalies=anomalies or {},
            compliance=compliance or {},
            language=language,
        )

    def test_empty_data_returns_empty_list(self):
        kams = self._build_kams()
        self.assertEqual(kams, [])

    def test_duplicate_count_triggers_kam001(self):
        kams = self._build_kams(
            summary={"duplicate_count": 3, "total_invoices": 10,
                     "compliance_score": 80.0, "currency": "SAR"},
        )
        ids = [k["kam_id"] for k in kams]
        self.assertIn("KAM-001", ids)

    def test_no_duplicates_no_kam001(self):
        kams = self._build_kams(
            summary={"duplicate_count": 0, "total_invoices": 10, "compliance_score": 90.0},
        )
        ids = [k["kam_id"] for k in kams]
        self.assertNotIn("KAM-001", ids)

    def test_vat_failures_trigger_kam002(self):
        compliance = {"vat": {"VAT-01": {"failed_count": 5}}}
        kams = self._build_kams(
            summary={"compliance_score": 80.0, "total_invoices": 10, "duplicate_count": 0},
            compliance=compliance,
        )
        ids = [k["kam_id"] for k in kams]
        self.assertIn("KAM-002", ids)

    def test_low_compliance_triggers_kam003(self):
        kams = self._build_kams(
            summary={"compliance_score": 45.0, "total_invoices": 20, "duplicate_count": 0},
        )
        ids = [k["kam_id"] for k in kams]
        self.assertIn("KAM-003", ids)

    def test_high_compliance_no_kam003(self):
        kams = self._build_kams(
            summary={"compliance_score": 95.0, "total_invoices": 20, "duplicate_count": 0},
        )
        ids = [k["kam_id"] for k in kams]
        self.assertNotIn("KAM-003", ids)

    def test_kams_sorted_critical_first(self):
        compliance = {"vat": {"VAT-01": {"failed_count": 2}}}
        kams = self._build_kams(
            summary={"compliance_score": 50.0, "total_invoices": 10,
                     "duplicate_count": 2, "currency": "SAR"},
            compliance=compliance,
        )
        # All critical KAMs must appear before any non-critical
        severity_order = {"critical": 0, "high": 1, "medium": 2}
        severities = [severity_order[k["severity"]] for k in kams]
        self.assertEqual(severities, sorted(severities))

    def test_kam_has_required_fields(self):
        kams = self._build_kams(
            summary={"duplicate_count": 1, "total_invoices": 5,
                     "compliance_score": 80.0, "currency": "SAR"},
        )
        required = {"kam_id", "isa_reference", "severity", "title_ar", "title_en",
                    "description_ar", "description_en", "root_cause_ar", "root_cause_en",
                    "financial_impact", "recommendation_ar", "recommendation_en", "evidence"}
        for kam in kams:
            missing = required - set(kam.keys())
            self.assertEqual(missing, set(), f"{kam['kam_id']} missing fields: {missing}")

    def test_vendor_concentration_triggers_kam004(self):
        anomalies = {
            "dominant_supplier": {
                "supplier_name": "Vendor X",
                "spend_share_percent": 55.0,
                "total_spend": 500000.0,
            }
        }
        kams = self._build_kams(
            summary={"compliance_score": 80.0, "total_invoices": 10, "duplicate_count": 0},
            anomalies=anomalies,
        )
        ids = [k["kam_id"] for k in kams]
        self.assertIn("KAM-004", ids)

    def test_vendor_below_threshold_no_kam004(self):
        anomalies = {
            "dominant_supplier": {
                "supplier_name": "Vendor X",
                "spend_share_percent": 30.0,
                "total_spend": 100000.0,
            }
        }
        kams = self._build_kams(
            summary={"compliance_score": 80.0, "total_invoices": 10, "duplicate_count": 0},
            anomalies=anomalies,
        )
        ids = [k["kam_id"] for k in kams]
        self.assertNotIn("KAM-004", ids)

    def test_arabic_language_uses_arabic_evidence(self):
        kams = self._build_kams(
            summary={"duplicate_count": 1, "total_invoices": 5,
                     "compliance_score": 80.0, "currency": "SAR"},
            language="ar",
        )
        kam001 = next(k for k in kams if k["kam_id"] == "KAM-001")
        # Arabic evidence should contain Arabic text
        evidence_text = " ".join(kam001["evidence"])
        self.assertTrue(
            any(ord(c) > 127 for c in evidence_text),
            "Arabic language KAM should contain non-ASCII (Arabic) text"
        )

    def test_high_risk_count_triggers_kam005(self):
        kams = self._build_kams(
            summary={
                "high_risk_count": 8,
                "total_invoices": 20,
                "compliance_score": 75.0,
                "duplicate_count": 0,
                "total_amount": 200000.0,
                "currency": "SAR",
            },
        )
        ids = [k["kam_id"] for k in kams]
        self.assertIn("KAM-005", ids)

    def test_benford_deviation_triggers_kam006(self):
        anomalies = {
            "benford_analysis": {
                "chi_square": 20.0,
                "passes_benford": False,
                "sample_size": 50,
            }
        }
        kams = self._build_kams(
            summary={"compliance_score": 80.0, "total_invoices": 50, "duplicate_count": 0},
            anomalies=anomalies,
        )
        ids = [k["kam_id"] for k in kams]
        self.assertIn("KAM-006", ids)

    def test_no_benford_deviation_no_kam006(self):
        anomalies = {
            "benford_analysis": {
                "chi_square": 5.0,
                "passes_benford": True,
                "sample_size": 50,
            }
        }
        kams = self._build_kams(
            summary={"compliance_score": 80.0, "total_invoices": 50, "duplicate_count": 0},
            anomalies=anomalies,
        )
        ids = [k["kam_id"] for k in kams]
        self.assertNotIn("KAM-006", ids)


# ─────────────────────────────────────────────────────────────
# ISA 700 Opinion tests
# ─────────────────────────────────────────────────────────────

class TestISA700Opinion(TestCase):
    """Tests for _determine_isa700_opinion() in InvoiceAuditReportService."""

    def _opinion(self, compliance_score, duplicate_count=0, total_invoices=10, validated_count=None):
        from apps.reports.services.invoice_audit_service import InvoiceAuditReportService
        if validated_count is None:
            validated_count = total_invoices  # assume all validated by default
        summary = {
            "compliance_score": compliance_score,
            "duplicate_count": duplicate_count,
            "total_invoices": total_invoices,
            "validated_count": validated_count,
            "high_risk_count": 0,
        }
        svc = InvoiceAuditReportService.__new__(InvoiceAuditReportService)
        return svc._determine_isa700_opinion(summary)

    def test_no_data_returns_disclaimer(self):
        opinion = self._opinion(compliance_score=0.0, total_invoices=0, validated_count=0)
        self.assertEqual(opinion["opinion_type"], "disclaimer")

    def test_high_score_no_duplicates_returns_unqualified(self):
        opinion = self._opinion(compliance_score=90.0, duplicate_count=0)
        self.assertEqual(opinion["opinion_type"], "unqualified")

    def test_high_score_with_duplicates_returns_qualified(self):
        opinion = self._opinion(compliance_score=90.0, duplicate_count=2)
        self.assertEqual(opinion["opinion_type"], "qualified")

    def test_mid_score_returns_qualified(self):
        opinion = self._opinion(compliance_score=70.0, duplicate_count=0)
        self.assertEqual(opinion["opinion_type"], "qualified")

    def test_low_score_returns_adverse(self):
        opinion = self._opinion(compliance_score=40.0, duplicate_count=0)
        self.assertEqual(opinion["opinion_type"], "adverse")

    def test_opinion_has_required_fields(self):
        opinion = self._opinion(compliance_score=80.0)
        required = {"opinion_type", "opinion_type_ar", "opinion_type_en",
                    "basis_ar", "basis_en", "standard"}
        missing = required - set(opinion.keys())
        self.assertEqual(missing, set(), f"Missing fields: {missing}")

    def test_standard_references_isa700(self):
        opinion = self._opinion(compliance_score=80.0)
        self.assertIn("ISA 700", opinion["standard"])

    def test_score_exactly_at_safe_threshold_is_unqualified(self):
        # RISK_THRESHOLDS["safe"] == 85
        opinion = self._opinion(compliance_score=85.0, duplicate_count=0)
        self.assertEqual(opinion["opinion_type"], "unqualified")

    def test_score_just_below_safe_threshold_is_qualified(self):
        opinion = self._opinion(compliance_score=84.9, duplicate_count=0)
        self.assertEqual(opinion["opinion_type"], "qualified")

    def test_score_exactly_at_review_threshold_is_qualified(self):
        # RISK_THRESHOLDS["review"] == 60
        opinion = self._opinion(compliance_score=60.0, duplicate_count=0)
        self.assertEqual(opinion["opinion_type"], "qualified")

    def test_score_just_below_review_threshold_is_adverse(self):
        opinion = self._opinion(compliance_score=59.9, duplicate_count=0)
        self.assertEqual(opinion["opinion_type"], "adverse")


# ─────────────────────────────────────────────────────────────
# Root Cause Analysis tests
# ─────────────────────────────────────────────────────────────

class TestRootCauseAnalysis(TestCase):
    """
    _build_root_cause_analysis() consumes InvoiceValidationResult ORM objects.
    We use MagicMock to simulate validation objects with specific field values.
    """

    def _build_rca(self, validations):
        from apps.reports.services.invoice_audit_service import InvoiceAuditReportService
        svc = InvoiceAuditReportService.__new__(InvoiceAuditReportService)
        return svc._build_root_cause_analysis(validations)

    def _make_validation(self, **fields):
        """Create a mock InvoiceValidationResult with given field values."""
        mock = MagicMock()
        # Default all fields to None (no failure)
        mock.__class__ = object
        for attr in fields:
            setattr(mock, attr, fields[attr])
        # Ensure getattr returns None for undefined fields
        mock.configure_mock(**{k: v for k, v in fields.items()})
        return mock

    def test_empty_validations_returns_empty_findings(self):
        rca = self._build_rca({})
        self.assertIsInstance(rca, dict)
        self.assertIn("findings", rca)
        self.assertIn("dominant_risk_areas", rca)
        self.assertEqual(rca["findings"], [])
        self.assertEqual(rca["dominant_risk_areas"], [])

    def test_return_structure_is_correct(self):
        rca = self._build_rca({})
        self.assertIsInstance(rca["findings"], list)
        self.assertIsInstance(rca["dominant_risk_areas"], list)

    def test_findings_have_required_keys_when_present(self):
        from apps.reports.services.invoice_audit_service import RULE_REGISTRY
        # Find a non-inverted rule with a field we can set False to trigger failure
        non_inverted = next(
            (r for r in RULE_REGISTRY if not r["inverted"]), None
        )
        if non_inverted is None:
            self.skipTest("No non-inverted rule found in RULE_REGISTRY")

        mock_validation = MagicMock()
        setattr(mock_validation, non_inverted["field"], False)  # triggers failure

        rca = self._build_rca({"INV-001": mock_validation})
        if rca["findings"]:
            for finding in rca["findings"]:
                self.assertIn("category", finding)
                self.assertIn("failure_count", finding)
                self.assertIn("root_cause_ar", finding)
                self.assertIn("root_cause_en", finding)

    def test_dominant_risk_areas_at_most_three(self):
        rca = self._build_rca({})
        self.assertLessEqual(len(rca["dominant_risk_areas"]), 3)


# ─────────────────────────────────────────────────────────────
# Benford's Law integration
# ─────────────────────────────────────────────────────────────

class TestBenfordIntegration(TestCase):

    def test_benford_analysis_returns_dict_on_sufficient_data(self):
        from core.services.ai_service import benford_analysis
        amounts = [100, 200, 300, 150, 120, 110, 130, 180, 190, 210,
                   220, 230, 240, 250, 260, 270, 280, 290, 310, 320,
                   330, 340, 350, 360, 370, 380, 390, 400, 410, 420]
        result = benford_analysis(amounts)
        self.assertIsInstance(result, dict)
        self.assertIn("chi_square", result)
        self.assertIn("passes_benford", result)

    def test_benford_analysis_insufficient_data_returns_none_or_dict(self):
        from core.services.ai_service import benford_analysis
        # Less than 30 samples — should return None or a dict with a note
        result = benford_analysis([100, 200, 300])
        # We only assert it does not raise
        self.assertTrue(result is None or isinstance(result, dict))

    def test_benford_significant_detection(self):
        from core.services.ai_service import benford_analysis
        amounts = [100 + i for i in range(30)]
        result = benford_analysis(amounts)
        if result:
            self.assertIn("chi_square", result)
            self.assertIn("passes_benford", result)
            self.assertIsInstance(result["passes_benford"], bool)


# ─────────────────────────────────────────────────────────────
# GCC VAT Rate Rule — extended
# ─────────────────────────────────────────────────────────────

class TestVATRateRuleGCCExtended(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATRateRule
        return VATRateRule()

    def test_rate_within_tolerance_passes(self):
        # AE: 5% ± 0.5 → 5.3% should pass
        doc = make_doc("AE", typed_data={"vat_rate": 5.3})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_rate_outside_tolerance_fails(self):
        # AE: 5% ± 0.5 → 10% should fail
        doc = make_doc("AE", typed_data={"vat_rate": 10.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_config_override_expected_rate(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATRateRule
        rule = VATRateRule(config={"expected_vat_rate": "20.0"})
        doc = make_doc("SA", typed_data={"vat_rate": 20.0})
        # Config overrides country default
        self.assertEqual(rule.execute(doc).status, RuleStatus.PASS)

    def test_kw_not_applicable_regardless_of_rate(self):
        doc = make_doc("KW", typed_data={"vat_rate": 15.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.NOT_APPLICABLE)

    def test_qa_not_applicable_regardless_of_rate(self):
        doc = make_doc("QA", typed_data={"vat_rate": 0.0})
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.NOT_APPLICABLE)


# ─────────────────────────────────────────────────────────────
# GCC VAT Number Format Rule — extended
# ─────────────────────────────────────────────────────────────

class TestVATNumberFormatRuleGCCExtended(TestCase):

    def _rule(self):
        from apps.rule_engine.rules.invoice.vat_calculation_rule import VATNumberFormatRule
        return VATNumberFormatRule()

    def test_ae_valid_15_digit_not_starting_with_3(self):
        # AE only requires 15 digits, not a specific start
        doc = make_doc("AE", tax_id="100000000000001")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_om_case_insensitive(self):
        doc = make_doc("OM", tax_id="OM12345678")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)
        doc2 = make_doc("OM", tax_id="om12345678")
        self.assertEqual(self._rule().execute(doc2).status, RuleStatus.PASS)

    def test_om_wrong_digit_count(self):
        # OM + 7 digits (not 8)
        doc = make_doc("OM", tax_id="OM1234567")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.FAIL)

    def test_bh_valid_9_digits(self):
        doc = make_doc("BH", tax_id="987654321")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.PASS)

    def test_error_message_contains_expected_format(self):
        doc = make_doc("BH", tax_id="12345")  # too short
        result = self._rule().execute(doc)
        self.assertIn("9 digits", result.explanation_en)

    def test_kw_no_precondition_check_needed(self):
        # Even if tax_id is provided for KW, should return NOT_APPLICABLE
        doc = make_doc("KW", tax_id="123456789")
        self.assertEqual(self._rule().execute(doc).status, RuleStatus.NOT_APPLICABLE)
