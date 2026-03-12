import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import Client, TestCase
from django.test.utils import override_settings
from rest_framework.test import APIClient

from apps.analytics.models import NLQueryHistory
from apps.audit.models import AuditCase
from apps.authentication.models import Organization, OrganizationSettings
from apps.compliance.models import ComplianceViolation
from apps.invoices.models import Invoice, InvoiceBatch, InvoiceValidationResult
from apps.transactions.models import Transaction

User = get_user_model()


class BaseFinAITestCase(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="FinAI Test Org",
            name_ar="مؤسسة فناي",
            country=Organization.Country.SAUDI_ARABIA,
            currency=Organization.Currency.SAR,
            vat_number="300000000000003",
        )
        self.admin = User.objects.create_user(
            email="admin@finai.sa",
            password="StrongPass123!",
            full_name="Admin User",
            role=User.Role.ADMIN,
            organization=self.organization,
            is_staff=True,
        )
        self.compliance_user = User.objects.create_user(
            email="compliance@finai.sa",
            password="StrongPass123!",
            full_name="Compliance User",
            role=User.Role.COMPLIANCE_OFFICER,
            organization=self.organization,
        )
        self.api_client = APIClient()
        self.web_client = Client()

    def create_invoice(self, **overrides):
        defaults = {
            "organization": self.organization,
            "uploaded_by": self.admin,
            "original_filename": "invoice-1001.pdf",
            "invoice_number": "INV-1001",
            "invoice_date": date(2026, 3, 1),
            "vendor_name": "Acme Supplies",
            "vendor_vat_number": "300000000000010",
            "currency": Invoice.Currency.SAR,
            "subtotal": Decimal("100.00"),
            "vat_amount": Decimal("15.00"),
            "total_amount": Decimal("115.00"),
        }
        defaults.update(overrides)
        return Invoice.objects.create(**defaults)

    def create_transaction(self, **overrides):
        defaults = {
            "organization": self.organization,
            "transaction_type": Transaction.TransactionType.EXPENSE,
            "amount": Decimal("115.00"),
            "currency": self.organization.currency,
            "vat_amount": Decimal("15.00"),
            "vendor_name": "Acme Supplies",
            "invoice_number": "INV-1001",
            "transaction_date": date(2026, 3, 1),
            "description": "Invoice payment",
        }
        defaults.update(overrides)
        return Transaction.objects.create(**defaults)


class TemplateCompilationTests(TestCase):
    def test_all_templates_compile(self):
        template_root = Path(settings.BASE_DIR) / "templates"
        failures = []

        for path in template_root.rglob("*.html"):
            template_name = path.relative_to(template_root).as_posix()
            try:
                get_template(template_name)
            except Exception as exc:
                failures.append(f"{template_name}: {exc}")

        self.assertFalse(failures, "\n".join(failures))


class OrganizationSettingsApiTests(BaseFinAITestCase):
    def test_get_and_patch_current_organization_settings(self):
        self.api_client.force_authenticate(user=self.admin)

        response = self.api_client.get("/api/v1/auth/organization/settings/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            OrganizationSettings.objects.filter(organization=self.organization).exists()
        )

        patch_response = self.api_client.patch(
            "/api/v1/auth/organization/settings/",
            {
                "financial": {"vat_rate": 10, "monthly_budget_limit": 50000},
                "notifications": {"weekly_summary": True},
            },
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)

        self.organization.refresh_from_db()
        self.assertEqual(float(self.organization.vat_rate), 10.0)

    def test_post_current_organization_settings_merges_keys(self):
        self.api_client.force_authenticate(user=self.admin)

        first_response = self.api_client.post(
            "/api/v1/auth/organization/settings/",
            {
                "financial": {"vat_rate": 12, "monthly_budget_limit": 25000},
            },
            format="json",
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.api_client.post(
            "/api/v1/auth/organization/settings/",
            {
                "notifications": {"email_weekly_summary": False},
            },
            format="json",
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data["financial"]["monthly_budget_limit"], 25000)
        self.assertFalse(second_response.data["notifications"]["email_weekly_summary"])


class AuthenticationFlowTests(BaseFinAITestCase):
    def test_set_password_allows_same_user(self):
        self.api_client.force_authenticate(user=self.compliance_user)

        response = self.api_client.post(
            f"/api/v1/auth/users/{self.compliance_user.id}/set-password/",
            {"new_password": "ChangedPass123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["detail"], "تم تغيير كلمة المرور بنجاح.")

        self.compliance_user.refresh_from_db()
        self.assertTrue(self.compliance_user.check_password("ChangedPass123!"))

    def test_current_organization_patch_is_admin_only(self):
        self.api_client.force_authenticate(user=self.compliance_user)
        forbidden_response = self.api_client.patch(
            "/api/v1/auth/organization/",
            {"name": "Blocked Update"},
            format="json",
        )
        self.assertEqual(forbidden_response.status_code, 403)

        self.api_client.force_authenticate(user=self.admin)
        allowed_response = self.api_client.patch(
            "/api/v1/auth/organization/",
            {"name": "Updated FinAI Org"},
            format="json",
        )
        self.assertEqual(allowed_response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Updated FinAI Org")

    @override_settings(GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com")
    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_google_login_creates_user_and_session(self, mock_verify):
        mock_verify.return_value = {
            "email": "google.user@finai.sa",
            "name": "Google User",
            "email_verified": True,
        }

        response = self.web_client.post(
            "/api/v1/auth/google/",
            data=json.dumps({"id_token": "dummy-token"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertTrue(payload["is_new"])
        self.assertTrue(payload["needs_org"])
        self.assertIn("access", payload)

        created_user = User.objects.get(email="google.user@finai.sa")
        self.assertEqual(self.web_client.session.get("_auth_user_id"), str(created_user.id))
        self.assertTrue(created_user.has_usable_password() is False)

    def test_google_pending_renders_for_user_without_organization(self):
        pending_user = User.objects.create_user(
            email="pending@finai.sa",
            password="PendingPass123!",
            full_name="Pending User",
            role=User.Role.JUNIOR_AUDITOR,
            organization=None,
        )
        self.web_client.force_login(pending_user)

        response = self.web_client.get("/google-pending/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pending@finai.sa")


class TraceabilityWorkflowTests(BaseFinAITestCase):
    @patch("apps.compliance.views.check_compliance_ai")
    @patch("apps.analytics.views.detect_anomalies_ai")
    def test_compliance_and_audit_cases_link_back_to_invoice(
        self,
        mock_detect_anomalies_ai,
        mock_check_compliance_ai,
    ):
        invoice = self.create_invoice()
        transaction = self.create_transaction(invoice_number=invoice.invoice_number)

        mock_check_compliance_ai.return_value = {
            "violations": [
                {
                    "transaction_id": str(transaction.id),
                    "rule_violated": "VAT-001",
                    "standard": "VAT",
                    "severity": "high",
                    "description": "VAT amount mismatch",
                    "corrective_action": "Review the source invoice",
                }
            ]
        }
        mock_detect_anomalies_ai.return_value = {
            "anomalies": [
                {
                    "transaction_id": str(transaction.id),
                    "anomaly_type": "duplicate-pattern",
                    "severity": "high",
                    "risk_score": 86,
                    "description": "Unusual duplicate-like transaction pattern",
                }
            ]
        }

        self.api_client.force_authenticate(user=self.compliance_user)
        compliance_response = self.api_client.post(
            "/api/v1/compliance/check/",
            {},
            format="json",
        )
        self.assertEqual(compliance_response.status_code, 200)

        violation = ComplianceViolation.objects.get()
        self.assertEqual(violation.transaction_id, transaction.id)
        self.assertEqual(violation.invoice_id, invoice.id)

        self.api_client.force_authenticate(user=self.admin)
        anomaly_response = self.api_client.post(
            "/api/v1/analytics/anomalies/detect/",
            {"auto_create_cases": True},
            format="json",
        )
        self.assertEqual(anomaly_response.status_code, 200)

        case = AuditCase.objects.get()
        self.assertEqual(case.transaction_id, transaction.id)
        self.assertEqual(case.invoice_id, invoice.id)

        assign_response = self.api_client.post(
            f"/api/v1/audit/cases/{case.id}/assign/",
            {"user_id": str(self.compliance_user.id)},
            format="json",
        )
        self.assertEqual(assign_response.status_code, 200)
        self.assertEqual(assign_response.data["assigned_to_id"], str(self.compliance_user.id))

        case.refresh_from_db()
        self.assertEqual(case.assigned_to_id, self.compliance_user.id)


class AnalyticsHistoryTests(BaseFinAITestCase):
    @patch("apps.analytics.views.nl_to_django_filter")
    def test_nl_query_saves_history_and_exports_csv(self, mock_nl_to_django_filter):
        self.create_transaction()
        self.api_client.force_authenticate(user=self.admin)

        mock_nl_to_django_filter.return_value = {
            "filters": {"vendor_name__icontains": "Acme"},
            "exclude": {},
            "order_by": ["-transaction_date"],
            "limit": 25,
            "explanation": "Filter transactions by vendor name.",
        }

        response = self.api_client.post(
            "/api/v1/analytics/query/",
            {"query": "Show Acme transactions"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(NLQueryHistory.objects.count(), 1)
        self.assertEqual(response.data["count"], 1)

        history_response = self.api_client.get("/api/v1/analytics/query/history/?mine=true")
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(len(history_response.data), 1)

        export_response = self.api_client.get("/api/v1/analytics/query/export/")
        self.assertEqual(export_response.status_code, 200)
        self.assertIn("text/csv", export_response["Content-Type"])
        self.assertIn("Show Acme transactions", export_response.content.decode("utf-8"))


class FrontendRouteTests(BaseFinAITestCase):
    def test_public_landing_and_auth_pages_render_for_anonymous_users(self):
        for path in ["/", "/login/", "/register/"]:
            with self.subTest(path=path):
                response = self.web_client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_register_page_creates_user_and_redirects_to_pending_review(self):
        response = self.web_client.post(
            "/register/",
            {
                "full_name": "New Auditor",
                "email": "new-auditor@finai.sa",
                "password": "StrongPass123!",
                "password_confirm": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertTrue(payload["success"])
        self.assertEqual(payload["redirect"], "/google-pending/")

        user = User.objects.get(email="new-auditor@finai.sa")
        self.assertIsNone(user.organization_id)
        self.assertEqual(str(user.id), self.web_client.session.get("_auth_user_id"))

    def test_new_frontend_pages_render_for_authenticated_users(self):
        invoice = self.create_invoice()
        batch = InvoiceBatch.objects.create(
            organization=self.organization,
            uploaded_by=self.admin,
            batch_name="March Upload",
            status=InvoiceBatch.BatchStatus.COMPLETED,
            total_files=1,
            processed_files=1,
        )
        invoice.batch = batch
        invoice.save(update_fields=["batch"])

        case = AuditCase.objects.create(
            organization=self.organization,
            case_number="CASE-2026-0001",
            title="Investigate invoice",
            description="Check flagged invoice",
            case_type=AuditCase.CaseType.COMPLIANCE,
            created_by=self.admin,
            assigned_to=self.admin,
            invoice=invoice,
        )

        self.web_client.force_login(self.admin)

        for path in [
            "/dashboard/",
            "/documents/upload/",
            "/transactions/",
            "/users/",
            "/settings/",
            f"/invoices/batches/{batch.id}/",
            f"/audit/{case.id}/",
        ]:
            with self.subTest(path=path):
                response = self.web_client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_invoice_detail_uses_text_fallback_and_effective_flagged_status(self):
        invoice = self.create_invoice(
            invoice_number="",
            invoice_date=None,
            due_date=None,
            vendor_name="",
            vendor_name_ar="",
            subtotal=Decimal("0.00"),
            vat_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            risk_score=82,
            risk_level="low",
            status=Invoice.Status.VALIDATED,
            raw_text=(
                "Acme Trading Co\n"
                "Invoice No: INV-7788\n"
                "Invoice Date: 2026-03-07\n"
                "Due Date: 2026-03-14\n"
                "VAT Amount: 45.00\n"
                "Grand Total: 345.00 SAR\n"
            ),
            extracted_data={},
        )
        InvoiceValidationResult.objects.create(
            invoice=invoice,
            rules_passed=24,
            rules_failed=6,
            validation_score=62,
            failed_rule_codes=["ANO-001", "INV-003"],
            validation_details={
                "INV-003": {
                    "description": "Vendor name present",
                    "message": "Missing vendor on primary extraction",
                    "passed": False,
                    "severity": "high",
                }
            },
        )

        self.web_client.force_login(self.admin)
        response = self.web_client.get(f"/invoices/{invoice.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Acme Trading Co")
        self.assertContains(response, "INV-7788")
        self.assertContains(response, "345.00 SAR")
        self.assertContains(response, "تحتاج مراجعة")
        self.assertNotContains(response, "OpenAI unavailable")


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class InvoiceRiskLogicTests(BaseFinAITestCase):
    def test_revalidate_sets_high_risk_invoices_to_flagged(self):
        invoice = self.create_invoice(status=Invoice.Status.VALIDATED, risk_score=0, risk_level="low")
        InvoiceValidationResult.objects.create(
            invoice=invoice,
            rules_passed=28,
            rules_failed=2,
            validation_score=90,
            failed_rule_codes=[],
            validation_details={},
        )

        self.api_client.force_authenticate(user=self.admin)
        with patch(
            "apps.invoices.views.run_all_rules",
            return_value={
                "rules_passed": 18,
                "rules_failed": 12,
                "validation_score": 35,
                "failed_rule_codes": ["DUP-001", "ANO-001", "VAT-001"],
                "rule_details": {
                    "DUP-001": {
                        "description": "Duplicate invoice number",
                        "message": "Potential duplicate detected",
                        "passed": False,
                        "severity": "high",
                    }
                },
                "risk_level": "high",
            },
        ), patch("apps.invoices.views.analyze_invoice_risk", return_value={}):
            response = self.api_client.post(f"/api/v1/invoices/{invoice.id}/revalidate/", format="json")

        self.assertEqual(response.status_code, 200)

        invoice.refresh_from_db()
        self.assertEqual(invoice.risk_level, "high")
        self.assertEqual(invoice.status, Invoice.Status.FLAGGED)
        self.assertGreaterEqual(invoice.risk_score, 70)
