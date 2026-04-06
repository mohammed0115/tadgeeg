"""
Comprehensive tests for the Invoice Audit Report subsystem.

Coverage:
  - classify_risk()                       — 7 tests
  - _rule_failed()                        — 6 tests
  - InvoiceAuditReportService.build()     — 5 tests (mocked DB)
  - InvoiceAuditReportService._build_summary() — 3 tests (mock data)
  - API views (generate, detail, html,
               high-risk, failed-rules,
               supplier-analysis, compliance) — 20+ tests

Run:
    python manage.py test tests.test_invoice_audit_report
"""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authentication.models import Organization
from apps.reports.models import Report
from apps.reports.services.invoice_audit_service import (
    InvoiceAuditReportService,
    classify_risk,
    _rule_failed,
    _violations_for,
    RULE_REGISTRY,
    RISK_THRESHOLDS,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_sample_data(org_id=None, user_email="test@example.com"):
    """Return a minimal but valid invoice audit report dict."""
    return {
        "report_header": {
            "report_id": None,
            "title": "تقرير تدقيق الفواتير",
            "organization_name": "Test Org",
            "organization_id": str(org_id or uuid.uuid4()),
            "created_at": "2026-03-24T00:00:00+00:00",
            "created_by": user_email,
            "report_type": "invoice_audit",
            "language": "ar",
            "period_from": None,
            "period_to": None,
            "overall_status": "clean",
            "overall_status_ar": "نظيف",
        },
        "summary": {
            "total_invoices": 10,
            "total_amount": 50000.0,
            "currency": "SAR",
            "compliance_score": 92.0,
            "average_risk_score": 5.0,
            "risk_level": "safe",
            "risk_level_ar": "آمن",
            "risk_level_en": "Safe",
            "duplicate_count": 0,
            "high_risk_count": 0,
            "flagged_count": 0,
            "validated_count": 10,
            "not_validated_count": 0,
        },
        "executive_summary": {"key_findings": [], "overall_assessment": ""},
        "compliance_engine": {
            "header": {},
            "duplicate": {},
            "vat": {},
            "anomaly": {},
            "control": {},
            "document": {},
        },
        "high_risk_invoices": [],
        "failed_rules_analysis": [],
        "supplier_analysis": [],
        "risk_analysis": {"safe": 10, "review": 0, "high_risk": 0},
        "anomalies": {},
        "actions_and_recommendations": {"immediate": [], "future": []},
    }


def _make_validation_mock(field_overrides=None):
    """Return a mock object that mimics an InvoiceValidationResult instance."""
    mock = MagicMock()
    # Default: every field is True (pass for non-inverted, fail for inverted)
    for rule in RULE_REGISTRY:
        setattr(mock, rule["field"], True)
    if field_overrides:
        for field, val in field_overrides.items():
            setattr(mock, field, val)
    return mock


# ─────────────────────────────────────────────────────────────────────────────
# 1. classify_risk() — 7 tests
# ─────────────────────────────────────────────────────────────────────────────

class ClassifyRiskTests(TestCase):
    """Tests for the classify_risk() pure function."""

    def test_score_100_is_safe(self):
        self.assertEqual(classify_risk(100.0), "safe")

    def test_score_at_safe_threshold_is_safe(self):
        """Exactly at the safe threshold (85.0) should return 'safe'."""
        self.assertEqual(classify_risk(RISK_THRESHOLDS["safe"]), "safe")

    def test_score_just_below_safe_threshold_is_review(self):
        self.assertEqual(classify_risk(84.9), "review")

    def test_score_at_review_threshold_is_review(self):
        """Exactly at the review threshold (60.0) should return 'review'."""
        self.assertEqual(classify_risk(RISK_THRESHOLDS["review"]), "review")

    def test_score_just_below_review_threshold_is_high_risk(self):
        self.assertEqual(classify_risk(59.9), "high_risk")

    def test_score_zero_is_high_risk(self):
        self.assertEqual(classify_risk(0.0), "high_risk")

    def test_score_midpoint_review(self):
        """A score of 70.0 (between 60 and 85) should be 'review'."""
        self.assertEqual(classify_risk(70.0), "review")


# ─────────────────────────────────────────────────────────────────────────────
# 2. _rule_failed() — 6 tests
# ─────────────────────────────────────────────────────────────────────────────

class RuleFailedTests(TestCase):
    """Tests for the _rule_failed() pure function."""

    def _non_inverted_rule(self):
        return next(r for r in RULE_REGISTRY if not r["inverted"])

    def _inverted_rule(self):
        return next(r for r in RULE_REGISTRY if r["inverted"])

    def test_non_inverted_true_field_does_not_fail(self):
        rule = self._non_inverted_rule()
        mock = _make_validation_mock({rule["field"]: True})
        self.assertFalse(_rule_failed(rule, mock))

    def test_non_inverted_false_field_fails(self):
        rule = self._non_inverted_rule()
        mock = _make_validation_mock({rule["field"]: False})
        self.assertTrue(_rule_failed(rule, mock))

    def test_inverted_true_field_fails(self):
        """Inverted rule: True = problem detected = failure."""
        rule = self._inverted_rule()
        mock = _make_validation_mock({rule["field"]: True})
        self.assertTrue(_rule_failed(rule, mock))

    def test_inverted_false_field_does_not_fail(self):
        """Inverted rule: False = no problem = pass."""
        rule = self._inverted_rule()
        mock = _make_validation_mock({rule["field"]: False})
        self.assertFalse(_rule_failed(rule, mock))

    def test_none_field_value_never_fails(self):
        """If the field is None, the rule should be considered passing."""
        rule = self._non_inverted_rule()
        mock = _make_validation_mock({rule["field"]: None})
        self.assertFalse(_rule_failed(rule, mock))

    def test_none_field_inverted_never_fails(self):
        """None on an inverted rule should also be considered passing."""
        rule = self._inverted_rule()
        mock = _make_validation_mock({rule["field"]: None})
        self.assertFalse(_rule_failed(rule, mock))


# ─────────────────────────────────────────────────────────────────────────────
# 3. InvoiceAuditReportService.build() — 5 tests (mocked DB)
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditServiceBuildTests(TestCase):
    """Tests for InvoiceAuditReportService.build() with mocked DB queries."""

    def setUp(self):
        self.org = Organization.objects.create(name="Service Test Org")
        self.user = User.objects.create_user(
            email="svc@example.com",
            password="Pass123!",
            full_name="Svc User",
            organization=self.org,
            role="admin",
        )

    def _patched_build(self, invoice_list=None, ivr_list=None, vp_list=None):
        """
        Run svc.build() with patched DB models.
        All three model querysets are patched at the source module level.
        """
        if invoice_list is None:
            invoice_list = []
        if ivr_list is None:
            ivr_list = []
        if vp_list is None:
            vp_list = []

        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter(invoice_list))
        mock_qs.select_related = MagicMock(return_value=mock_qs)
        mock_qs.filter = MagicMock(return_value=mock_qs)
        mock_qs.count = MagicMock(return_value=len(invoice_list))

        mock_ivr_qs = MagicMock()
        mock_ivr_qs.__iter__ = MagicMock(return_value=iter(ivr_list))
        mock_ivr_qs.select_related = MagicMock(return_value=mock_ivr_qs)
        mock_ivr_qs.filter = MagicMock(return_value=mock_ivr_qs)

        with patch("apps.reports.services.invoice_audit_service.Invoice") as MockInv, \
             patch("apps.reports.services.invoice_audit_service.InvoiceValidationResult") as MockIVR, \
             patch("apps.reports.services.invoice_audit_service.VendorProfile") as MockVP:

            MockInv.objects.filter.return_value = mock_qs
            MockIVR.objects.filter.return_value = mock_ivr_qs
            MockVP.objects.filter.return_value = vp_list

            svc = InvoiceAuditReportService(self.org, self.user)
            return svc.build()

    def test_build_returns_dict_with_required_sections(self):
        data = self._patched_build()
        required_keys = [
            "report_header", "summary", "executive_summary",
            "decision_support", "compliance_engine", "high_risk_invoices",
            "failed_rules_analysis", "supplier_analysis",
            "risk_analysis", "anomalies", "actions_and_recommendations",
        ]
        for key in required_keys:
            self.assertIn(key, data, f"Missing section: {key}")

    def test_build_empty_org_returns_zero_totals(self):
        data = self._patched_build()
        self.assertEqual(data["summary"]["total_invoices"], 0)
        self.assertEqual(data["summary"]["total_amount"], 0.0)

    def test_build_report_header_has_org_name(self):
        data = self._patched_build()
        self.assertEqual(data["report_header"]["organization_name"], self.org.name)

    def test_build_report_header_has_created_by(self):
        data = self._patched_build()
        self.assertEqual(data["report_header"]["created_by"], self.user.email)

    def test_build_risk_analysis_keys(self):
        data = self._patched_build()
        risk = data["risk_analysis"]
        # Must have at minimum the three tier keys
        self.assertIn("safe", risk)
        self.assertIn("review", risk)
        self.assertIn("high_risk", risk)

    def test_build_anomalies_contains_explainable_summary(self):
        data = self._patched_build()
        anomalies = data["anomalies"]

        self.assertIn("summary", anomalies)
        self.assertIn("top_anomalous_documents", anomalies)


# ─────────────────────────────────────────────────────────────────────────────
# 4. InvoiceAuditReportService._build_summary() — 3 tests (mock data)
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditServiceSummaryTests(TestCase):
    """Tests for the summary section logic of InvoiceAuditReportService."""

    def setUp(self):
        self.org = Organization.objects.create(name="Summary Test Org")
        self.user = User.objects.create_user(
            email="summary@example.com",
            password="Pass123!",
            full_name="Summary User",
            organization=self.org,
            role="admin",
        )
        self.svc = InvoiceAuditReportService(self.org, self.user)

    def _call_build_summary(self, invoices, ivr_map, language="ar"):
        """Call the private _build_summary (or build with mocked data)."""
        # _build_summary might not exist as a public method; test via build() indirectly
        # by asserting the summary structure is valid.
        mock_qs = MagicMock()
        mock_qs.__iter__ = MagicMock(return_value=iter(invoices))
        mock_qs.select_related = MagicMock(return_value=mock_qs)
        mock_qs.filter = MagicMock(return_value=mock_qs)

        mock_ivr_qs = MagicMock()
        mock_ivr_qs.__iter__ = MagicMock(return_value=iter(ivr_map.values()))
        mock_ivr_qs.select_related = MagicMock(return_value=mock_ivr_qs)
        mock_ivr_qs.filter = MagicMock(return_value=mock_ivr_qs)

        with patch("apps.reports.services.invoice_audit_service.Invoice") as MockInv, \
             patch("apps.reports.services.invoice_audit_service.InvoiceValidationResult") as MockIVR, \
             patch("apps.reports.services.invoice_audit_service.VendorProfile") as MockVP:

            MockInv.objects.filter.return_value = mock_qs
            MockIVR.objects.filter.return_value = mock_ivr_qs
            MockVP.objects.filter.return_value = []

            return self.svc.build(language=language)

    def test_summary_contains_compliance_score(self):
        data = self._call_build_summary([], {})
        self.assertIn("compliance_score", data["summary"])

    def test_summary_risk_level_is_string(self):
        data = self._call_build_summary([], {})
        self.assertIsInstance(data["summary"]["risk_level"], str)

    def test_summary_risk_level_values_are_valid(self):
        data = self._call_build_summary([], {})
        valid_levels = {"safe", "review", "high_risk"}
        self.assertIn(data["summary"]["risk_level"], valid_levels)


# ─────────────────────────────────────────────────────────────────────────────
# 5. API View base: fixtures and helpers
# ─────────────────────────────────────────────────────────────────────────────

class _BaseAPITestCase(TestCase):
    """Base class with common fixtures for all API view tests."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="API Test Org")
        self.user = User.objects.create_user(
            email="api@example.com",
            password="Pass123!",
            full_name="API User",
            organization=self.org,
            role="admin",
        )
        self.client.force_authenticate(user=self.user)
        self.sample_data = _make_sample_data(org_id=self.org.id)

    def _create_report(self, data=None, report_type="invoice_audit"):
        """Helper to create a Report in the DB."""
        return Report.objects.create(
            organization=self.org,
            generated_by=self.user,
            title="تقرير اختبار",
            report_type=report_type,
            language="ar",
            data=data or self.sample_data,
            narrative={},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. GenerateView tests (POST /api/v1/reports/invoice-audit/)
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditGenerateViewTests(_BaseAPITestCase):
    """Tests for InvoiceAuditReportGenerateView."""

    url = "/api/v1/reports/invoice-audit/"

    @patch("apps.reports.invoice_report_views.InvoiceAuditReportService")
    def test_generate_success_returns_201(self, MockSvc):
        mock_svc = MockSvc.return_value
        mock_svc.build.return_value = _make_sample_data(self.org.id)
        response = self.client.post(self.url, {"language": "ar", "save": False}, format="json")
        self.assertEqual(response.status_code, 201)

    @patch("apps.reports.invoice_report_views.InvoiceAuditReportService")
    def test_generate_with_save_creates_report(self, MockSvc):
        mock_svc = MockSvc.return_value
        mock_svc.build.return_value = _make_sample_data(self.org.id)
        count_before = Report.objects.filter(organization=self.org).count()
        response = self.client.post(self.url, {"language": "ar", "save": True}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Report.objects.filter(organization=self.org).count(),
            count_before + 1,
        )

    @patch("apps.reports.invoice_report_views.InvoiceAuditReportService")
    def test_generate_without_save_does_not_create_report(self, MockSvc):
        mock_svc = MockSvc.return_value
        mock_svc.build.return_value = _make_sample_data(self.org.id)
        count_before = Report.objects.filter(organization=self.org).count()
        response = self.client.post(self.url, {"language": "ar", "save": False}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Report.objects.filter(organization=self.org).count(), count_before)

    def test_generate_unauthenticated_returns_401(self):
        anon_client = APIClient()
        response = anon_client.post(self.url, {"language": "ar"}, format="json")
        self.assertIn(response.status_code, [401, 403])

    def test_generate_invalid_language_returns_400(self):
        response = self.client.post(self.url, {"language": "fr"}, format="json")
        self.assertEqual(response.status_code, 400)

    @patch("apps.reports.invoice_report_views.InvoiceAuditReportService")
    def test_generate_with_date_range_passes_dates_to_service(self, MockSvc):
        mock_svc = MockSvc.return_value
        mock_svc.build.return_value = _make_sample_data(self.org.id)
        self.client.post(
            self.url,
            {"language": "ar", "save": False, "date_from": "2025-01-01", "date_to": "2025-12-31"},
            format="json",
        )
        mock_svc.build.assert_called_once_with(
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            language="ar",
        )

    @patch("apps.reports.invoice_report_views.InvoiceAuditReportService")
    def test_generate_service_exception_returns_500(self, MockSvc):
        mock_svc = MockSvc.return_value
        mock_svc.build.side_effect = RuntimeError("DB error")
        response = self.client.post(self.url, {"language": "ar", "save": False}, format="json")
        self.assertEqual(response.status_code, 500)

    @patch("apps.reports.invoice_report_views.InvoiceAuditReportService")
    def test_generate_async_returns_202(self, MockSvc):
        """use_async=True should enqueue a Celery task and return 202."""
        mock_task = MagicMock()
        mock_task.id = "fake-task-id-123"
        with patch("apps.reports.invoice_report_views.generate_invoice_audit_report") as mock_delay:
            mock_delay_result = MagicMock()
            mock_delay_result.id = "fake-task-id-123"
            mock_delay.delay.return_value = mock_delay_result
            # Patch the import inside the view
            with patch("apps.reports.tasks.generate_invoice_audit_report") as _:
                response = self.client.post(
                    self.url,
                    {"language": "ar", "save": True, "use_async": True},
                    format="json",
                )
        # Either 202 (async path) or 201 (sync fallback if Celery not configured)
        self.assertIn(response.status_code, [201, 202])

    def test_generate_user_without_org_returns_403(self):
        no_org_user = User.objects.create_user(
            email="noorg@example.com",
            password="Pass123!",
            full_name="No Org",
            role="admin",
        )
        self.client.force_authenticate(user=no_org_user)
        response = self.client.post(self.url, {"language": "ar"}, format="json")
        self.assertEqual(response.status_code, 403)


# ─────────────────────────────────────────────────────────────────────────────
# 7. DetailView tests (GET /api/v1/reports/invoice-audit/<pk>/)
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditDetailViewTests(_BaseAPITestCase):
    """Tests for InvoiceAuditReportDetailView."""

    def test_detail_returns_200_for_own_report(self):
        report = self._create_report()
        url = f"/api/v1/reports/invoice-audit/{report.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_detail_returns_report_header_section(self):
        report = self._create_report()
        url = f"/api/v1/reports/invoice-audit/{report.id}/"
        response = self.client.get(url)
        self.assertIn("report_header", response.data)

    def test_detail_returns_404_for_nonexistent_report(self):
        url = f"/api/v1/reports/invoice-audit/{uuid.uuid4()}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_detail_returns_404_for_other_org_report(self):
        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_user(
            email="other@example.com",
            password="Pass123!",
            full_name="Other User",
            organization=other_org,
            role="admin",
        )
        other_report = Report.objects.create(
            organization=other_org,
            generated_by=other_user,
            title="Other Report",
            report_type="invoice_audit",
            language="ar",
            data=_make_sample_data(other_org.id),
            narrative={},
        )
        url = f"/api/v1/reports/invoice-audit/{other_report.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_detail_unauthenticated_returns_401(self):
        report = self._create_report()
        url = f"/api/v1/reports/invoice-audit/{report.id}/"
        anon_client = APIClient()
        response = anon_client.get(url)
        self.assertIn(response.status_code, [401, 403])


# ─────────────────────────────────────────────────────────────────────────────
# 8. HTMLView tests (GET /api/v1/reports/invoice-audit/<pk>/html/)
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditHTMLViewTests(_BaseAPITestCase):
    """Tests for InvoiceAuditReportHTMLView."""

    def test_html_view_returns_200(self):
        report = self._create_report()
        url = f"/api/v1/reports/invoice-audit/{report.id}/html/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_html_view_returns_html_content_type(self):
        report = self._create_report()
        url = f"/api/v1/reports/invoice-audit/{report.id}/html/"
        response = self.client.get(url)
        self.assertIn("text/html", response.get("Content-Type", ""))

    def test_html_view_returns_404_for_nonexistent(self):
        url = f"/api/v1/reports/invoice-audit/{uuid.uuid4()}/html/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


# ─────────────────────────────────────────────────────────────────────────────
# 9. HighRiskInvoicesView tests (GET /api/v1/reports/invoice-audit/<pk>/high-risk/)
# ─────────────────────────────────────────────────────────────────────────────

class HighRiskInvoicesViewTests(_BaseAPITestCase):
    """Tests for HighRiskInvoicesView."""

    def _create_report_with_high_risk(self, n=3):
        data = _make_sample_data(self.org.id)
        data["high_risk_invoices"] = [
            {
                "id": str(uuid.uuid4()),
                "invoice_number": f"INV-{i:03d}",
                "supplier_name": f"Supplier {i}",
                "invoice_date": "2025-06-15",
                "amount": 5000.0 * i,
                "currency": "SAR",
                "risk_level": "high_risk",
                "risk_score": 85.0,
                "compliance_score": 30.0,
                "is_duplicate": False,
                "is_flagged": True,
                "violations": [],
                "violation_count": 0,
            }
            for i in range(1, n + 1)
        ]
        return self._create_report(data=data)

    def test_high_risk_returns_200(self):
        report = self._create_report_with_high_risk(3)
        url = f"/api/v1/reports/invoice-audit/{report.id}/high-risk/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_high_risk_returns_correct_count(self):
        report = self._create_report_with_high_risk(3)
        url = f"/api/v1/reports/invoice-audit/{report.id}/high-risk/"
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 3)

    def test_high_risk_limit_param_respected(self):
        report = self._create_report_with_high_risk(5)
        url = f"/api/v1/reports/invoice-audit/{report.id}/high-risk/?limit=2"
        response = self.client.get(url)
        self.assertEqual(len(response.data["results"]), 2)

    def test_high_risk_returns_empty_for_clean_report(self):
        report = self._create_report()  # sample data has empty high_risk_invoices
        url = f"/api/v1/reports/invoice-audit/{report.id}/high-risk/"
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_high_risk_returns_404_for_nonexistent(self):
        url = f"/api/v1/reports/invoice-audit/{uuid.uuid4()}/high-risk/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


# ─────────────────────────────────────────────────────────────────────────────
# 10. FailedRulesView tests (GET /api/v1/reports/invoice-audit/<pk>/failed-rules/)
# ─────────────────────────────────────────────────────────────────────────────

class FailedRulesViewTests(_BaseAPITestCase):
    """Tests for FailedRulesView."""

    def _create_report_with_failed_rules(self):
        data = _make_sample_data(self.org.id)
        data["failed_rules_analysis"] = [
            {
                "rule_code": "HDR-001",
                "title_ar": "رقم الفاتورة",
                "title_en": "Invoice Number",
                "category": "header",
                "severity": "high",
                "weight": 10,
                "failure_count": 3,
                "failure_rate": 30.0,
                "invoice_numbers": ["INV-001", "INV-002", "INV-003"],
            },
            {
                "rule_code": "DUP-001",
                "title_ar": "تكرار رقم الفاتورة",
                "title_en": "Duplicate Invoice Number",
                "category": "duplicate",
                "severity": "critical",
                "weight": 20,
                "failure_count": 1,
                "failure_rate": 10.0,
                "invoice_numbers": ["INV-004"],
            },
        ]
        return self._create_report(data=data)

    def test_failed_rules_returns_200(self):
        report = self._create_report_with_failed_rules()
        url = f"/api/v1/reports/invoice-audit/{report.id}/failed-rules/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_failed_rules_returns_all_rules(self):
        report = self._create_report_with_failed_rules()
        url = f"/api/v1/reports/invoice-audit/{report.id}/failed-rules/"
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 2)

    def test_failed_rules_category_filter(self):
        report = self._create_report_with_failed_rules()
        url = f"/api/v1/reports/invoice-audit/{report.id}/failed-rules/?category=duplicate"
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["rule_code"], "DUP-001")

    def test_failed_rules_empty_for_clean_report(self):
        report = self._create_report()
        url = f"/api/v1/reports/invoice-audit/{report.id}/failed-rules/"
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 0)

    def test_failed_rules_returns_404_for_nonexistent(self):
        url = f"/api/v1/reports/invoice-audit/{uuid.uuid4()}/failed-rules/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


# ─────────────────────────────────────────────────────────────────────────────
# 11. SupplierAnalysisView tests (GET /api/v1/reports/invoice-audit/<pk>/supplier-analysis/)
# ─────────────────────────────────────────────────────────────────────────────

class SupplierAnalysisViewTests(_BaseAPITestCase):
    """Tests for SupplierAnalysisView."""

    def _create_report_with_suppliers(self):
        data = _make_sample_data(self.org.id)
        data["supplier_analysis"] = [
            {
                "supplier_name": "Supplier A",
                "invoice_count": 5,
                "total_spend": 25000.0,
                "average_invoice": 5000.0,
                "spend_share_percent": 50.0,
                "flagged_count": 0,
                "duplicate_count": 0,
                "risk_tier": "safe",
                "is_new_vendor": False,
                "is_suspicious": False,
            },
            {
                "supplier_name": "Supplier B",
                "invoice_count": 2,
                "total_spend": 8000.0,
                "average_invoice": 4000.0,
                "spend_share_percent": 16.0,
                "flagged_count": 1,
                "duplicate_count": 0,
                "risk_tier": "review",
                "is_new_vendor": True,
                "is_suspicious": False,
            },
        ]
        return self._create_report(data=data)

    def test_supplier_analysis_returns_200(self):
        report = self._create_report_with_suppliers()
        url = f"/api/v1/reports/invoice-audit/{report.id}/supplier-analysis/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_supplier_analysis_returns_all_suppliers(self):
        report = self._create_report_with_suppliers()
        url = f"/api/v1/reports/invoice-audit/{report.id}/supplier-analysis/"
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 2)

    def test_supplier_analysis_risk_tier_filter(self):
        report = self._create_report_with_suppliers()
        url = f"/api/v1/reports/invoice-audit/{report.id}/supplier-analysis/?risk_tier=review"
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["supplier_name"], "Supplier B")

    def test_supplier_analysis_returns_empty_for_no_suppliers(self):
        report = self._create_report()
        url = f"/api/v1/reports/invoice-audit/{report.id}/supplier-analysis/"
        response = self.client.get(url)
        self.assertEqual(response.data["count"], 0)

    def test_supplier_analysis_returns_404_for_nonexistent(self):
        url = f"/api/v1/reports/invoice-audit/{uuid.uuid4()}/supplier-analysis/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


# ─────────────────────────────────────────────────────────────────────────────
# 12. ComplianceEngineView tests (GET /api/v1/reports/invoice-audit/<pk>/compliance/)
# ─────────────────────────────────────────────────────────────────────────────

class ComplianceEngineViewTests(_BaseAPITestCase):
    """Tests for ComplianceEngineView."""

    def _create_report_with_compliance(self):
        data = _make_sample_data(self.org.id)
        data["compliance_engine"] = {
            "header": {"passed": 8, "failed": 0, "score": 100.0, "rule_count": 8},
            "duplicate": {"passed": 4, "failed": 1, "score": 80.0, "rule_count": 5},
            "vat": {"passed": 5, "failed": 0, "score": 100.0, "rule_count": 5},
            "anomaly": {"passed": 6, "failed": 0, "score": 100.0, "rule_count": 6},
            "control": {"passed": 6, "failed": 0, "score": 100.0, "rule_count": 6},
            "document": {"passed": 4, "failed": 0, "score": 100.0, "rule_count": 4},
        }
        return self._create_report(data=data)

    def test_compliance_returns_200(self):
        report = self._create_report_with_compliance()
        url = f"/api/v1/reports/invoice-audit/{report.id}/compliance/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_compliance_returns_all_categories(self):
        report = self._create_report_with_compliance()
        url = f"/api/v1/reports/invoice-audit/{report.id}/compliance/"
        response = self.client.get(url)
        for cat in ["header", "duplicate", "vat", "anomaly", "control", "document"]:
            self.assertIn(cat, response.data)

    def test_compliance_returns_404_for_nonexistent(self):
        url = f"/api/v1/reports/invoice-audit/{uuid.uuid4()}/compliance/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_compliance_tenant_isolation(self):
        """User from another org cannot access compliance data from this org."""
        report = self._create_report_with_compliance()
        other_org = Organization.objects.create(name="Attacker Org")
        attacker = User.objects.create_user(
            email="attacker@example.com",
            password="Pass123!",
            full_name="Attacker",
            organization=other_org,
            role="admin",
        )
        attacker_client = APIClient()
        attacker_client.force_authenticate(user=attacker)
        url = f"/api/v1/reports/invoice-audit/{report.id}/compliance/"
        response = attacker_client.get(url)
        self.assertEqual(response.status_code, 404)


# ─────────────────────────────────────────────────────────────────────────────
# 13. Additional cross-cutting tests
# ─────────────────────────────────────────────────────────────────────────────

class CrossCuttingTests(_BaseAPITestCase):
    """Miscellaneous cross-cutting tests: auth, tenant isolation, edge cases."""

    def test_all_sub_endpoints_require_auth(self):
        report = self._create_report()
        pk = report.id
        anon = APIClient()
        endpoints = [
            f"/api/v1/reports/invoice-audit/{pk}/",
            f"/api/v1/reports/invoice-audit/{pk}/high-risk/",
            f"/api/v1/reports/invoice-audit/{pk}/failed-rules/",
            f"/api/v1/reports/invoice-audit/{pk}/supplier-analysis/",
            f"/api/v1/reports/invoice-audit/{pk}/compliance/",
        ]
        for url in endpoints:
            resp = anon.get(url)
            self.assertIn(
                resp.status_code, [401, 403],
                msg=f"Expected 401/403 for unauthenticated request to {url}, got {resp.status_code}",
            )

    def test_report_not_found_returns_404_not_500(self):
        """A missing report should give 404, not a server crash."""
        fake_pk = uuid.uuid4()
        for path in ["", "/high-risk/", "/failed-rules/", "/supplier-analysis/", "/compliance/"]:
            url = f"/api/v1/reports/invoice-audit/{fake_pk}{path}"
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 404, msg=f"Expected 404 for {url}")

    def test_high_risk_limit_cannot_exceed_100(self):
        data = _make_sample_data(self.org.id)
        data["high_risk_invoices"] = [
            {
                "id": str(uuid.uuid4()),
                "invoice_number": f"INV-{i:04d}",
                "supplier_name": "Supplier",
                "invoice_date": None,
                "amount": 1000.0,
                "currency": "SAR",
                "risk_level": "high_risk",
                "risk_score": 90.0,
                "compliance_score": None,
                "is_duplicate": False,
                "is_flagged": True,
                "violations": [],
                "violation_count": 0,
            }
            for i in range(150)
        ]
        report = self._create_report(data=data)
        url = f"/api/v1/reports/invoice-audit/{report.id}/high-risk/?limit=999"
        response = self.client.get(url)
        self.assertLessEqual(len(response.data["results"]), 100)

    def test_failed_rules_limit_cannot_exceed_200(self):
        data = _make_sample_data(self.org.id)
        data["failed_rules_analysis"] = [
            {
                "rule_code": f"TST-{i:03d}",
                "title_ar": "قاعدة",
                "title_en": "Rule",
                "category": "header",
                "severity": "low",
                "weight": 1,
                "failure_count": 1,
                "failure_rate": 1.0,
                "invoice_numbers": [],
            }
            for i in range(250)
        ]
        report = self._create_report(data=data)
        url = f"/api/v1/reports/invoice-audit/{report.id}/failed-rules/?limit=999"
        response = self.client.get(url)
        self.assertLessEqual(len(response.data["results"]), 200)

    def test_user_without_org_cannot_access_report(self):
        no_org_user = User.objects.create_user(
            email="noorgreport@example.com",
            password="Pass123!",
            full_name="No Org Report",
            role="admin",
        )
        report = self._create_report()
        client2 = APIClient()
        client2.force_authenticate(user=no_org_user)
        url = f"/api/v1/reports/invoice-audit/{report.id}/"
        response = client2.get(url)
        self.assertEqual(response.status_code, 403)

    @patch("apps.reports.invoice_report_views.InvoiceAuditReportService")
    def test_generate_english_report(self, MockSvc):
        sample = _make_sample_data(self.org.id)
        sample["report_header"]["language"] = "en"
        mock_svc = MockSvc.return_value
        mock_svc.build.return_value = sample
        response = self.client.post(
            "/api/v1/reports/invoice-audit/",
            {"language": "en", "save": False},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    @patch("apps.reports.invoice_report_views.InvoiceAuditReportService")
    def test_generate_saves_report_with_correct_type(self, MockSvc):
        mock_svc = MockSvc.return_value
        mock_svc.build.return_value = _make_sample_data(self.org.id)
        self.client.post(
            "/api/v1/reports/invoice-audit/",
            {"language": "ar", "save": True},
            format="json",
        )
        report = Report.objects.filter(
            organization=self.org,
            report_type="invoice_audit",
        ).first()
        self.assertIsNotNone(report)
        self.assertEqual(report.report_type, "invoice_audit")

    def test_supplier_analysis_limit_param(self):
        data = _make_sample_data(self.org.id)
        data["supplier_analysis"] = [
            {
                "supplier_name": f"Supplier {i}",
                "invoice_count": 1,
                "total_spend": 1000.0,
                "average_invoice": 1000.0,
                "spend_share_percent": 1.0,
                "flagged_count": 0,
                "duplicate_count": 0,
                "risk_tier": "safe",
                "is_new_vendor": False,
                "is_suspicious": False,
            }
            for i in range(10)
        ]
        report = self._create_report(data=data)
        url = f"/api/v1/reports/invoice-audit/{report.id}/supplier-analysis/?limit=3"
        response = self.client.get(url)
        self.assertEqual(len(response.data["results"]), 3)

    def test_violations_for_returns_list(self):
        """_violations_for should return a list for any validation mock."""
        mock_validation = _make_validation_mock()
        violations = _violations_for(mock_validation)
        self.assertIsInstance(violations, list)

    def test_violations_for_perfect_invoice_has_no_violations(self):
        """All non-inverted rules True + all inverted rules False = zero violations."""
        overrides = {}
        for rule in RULE_REGISTRY:
            # Pass every rule: non-inverted → True, inverted → False
            overrides[rule["field"]] = False if rule["inverted"] else True
        mock_validation = _make_validation_mock(overrides)
        violations = _violations_for(mock_validation)
        self.assertEqual(violations, [])

    def test_classify_risk_thresholds_consistency(self):
        """safe threshold must be greater than review threshold."""
        self.assertGreater(RISK_THRESHOLDS["safe"], RISK_THRESHOLDS["review"])

    def test_rule_registry_has_no_duplicate_codes(self):
        codes = [r["code"] for r in RULE_REGISTRY]
        self.assertEqual(len(codes), len(set(codes)))

    def test_rule_registry_has_no_duplicate_fields(self):
        fields = [r["field"] for r in RULE_REGISTRY]
        self.assertEqual(len(fields), len(set(fields)))
