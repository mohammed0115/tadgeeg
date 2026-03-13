import json
import re
from io import StringIO
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.template.loader import get_template
from django.test import Client, TestCase
from django.test.utils import override_settings
from rest_framework.test import APIClient

from apps.analytics.models import NLQueryHistory
from apps.audit.models import AuditCase
from apps.authentication.models import EmailOTPVerification, Organization, OrganizationSettings
from apps.authentication.services.email_otp import PENDING_EMAIL_VERIFICATION_SESSION_KEY
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

    @override_settings(
        GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_google_login_creates_user_and_starts_email_verification(self, mock_verify):
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
        self.assertEqual(response.status_code, 202)

        payload = response.json()
        self.assertTrue(payload["is_new"])
        self.assertTrue(payload["needs_org"])
        self.assertTrue(payload["verification_required"])
        self.assertEqual(payload["redirect"], "/verify-email/")
        self.assertNotIn("access", payload)

        created_user = User.objects.get(email="google.user@finai.sa")
        self.assertIsNone(created_user.email_verified_at)
        self.assertEqual(self.web_client.session.get(PENDING_EMAIL_VERIFICATION_SESSION_KEY), str(created_user.id))
        self.assertIsNone(self.web_client.session.get("_auth_user_id"))
        self.assertTrue(created_user.has_usable_password() is False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertRegex(mail.outbox[0].body, r"\b\d{6}\b")

    def test_google_pending_redirects_to_otp_for_unverified_user(self):
        pending_user = User.objects.create_user(
            email="pending@finai.sa",
            password="PendingPass123!",
            full_name="Pending User",
            role=User.Role.JUNIOR_AUDITOR,
            organization=None,
            email_verified_at=None,
        )
        session = self.web_client.session
        session[PENDING_EMAIL_VERIFICATION_SESSION_KEY] = str(pending_user.id)
        session.save()

        response = self.web_client.get("/google-pending/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/verify-email/")

    @override_settings(
        GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET="test-client-secret",
        GOOGLE_REDIRECT_URI="http://testserver/auth/google/callback/",
    )
    def test_google_oauth_login_redirects_to_google_and_stores_state(self):
        response = self.web_client.get("/auth/google/login/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
        state = self.web_client.session.get("google_oauth_state")
        self.assertTrue(state)
        self.assertIn(f"state={state}", response["Location"])

    def test_google_oauth_callback_without_code_redirects_with_error(self):
        response = self.web_client.get("/auth/google/callback/")

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.path, "/login/")
        self.assertEqual(parse_qs(parsed.query).get("auth_error"), ["missing_code"])

    @patch("apps.frontend.page_views.fetch_google_user_profile")
    @patch("apps.frontend.page_views.exchange_google_code_for_tokens")
    def test_google_oauth_callback_logs_in_user_and_redirects_dashboard(
        self,
        mock_exchange_google_code_for_tokens,
        mock_fetch_google_user_profile,
    ):
        session = self.web_client.session
        session["google_oauth_state"] = "state-123"
        session.save()

        mock_exchange_google_code_for_tokens.return_value = {"access_token": "google-access-token"}
        mock_fetch_google_user_profile.return_value = {
            "email": "oauth.user@finai.sa",
            "name": "OAuth User",
        }

        response = self.web_client.get(
            "/auth/google/callback/",
            {"code": "auth-code", "state": "state-123"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/dashboard/")

        created_user = User.objects.get(email="oauth.user@finai.sa")
        session = self.web_client.session
        self.assertEqual(session.get("_auth_user_id"), str(created_user.id))
        self.assertIn("access", session.get("post_login_tokens", {}))
        self.assertIsNotNone(created_user.email_verified_at)

    @patch("apps.frontend.page_views.fetch_google_user_profile")
    @patch("apps.frontend.page_views.exchange_google_code_for_tokens")
    def test_google_oauth_callback_handles_missing_email(
        self,
        mock_exchange_google_code_for_tokens,
        mock_fetch_google_user_profile,
    ):
        session = self.web_client.session
        session["google_oauth_state"] = "state-456"
        session.save()

        mock_exchange_google_code_for_tokens.return_value = {"access_token": "google-access-token"}
        mock_fetch_google_user_profile.return_value = {"name": "OAuth User"}

        response = self.web_client.get(
            "/auth/google/callback/",
            {"code": "auth-code", "state": "state-456"},
        )

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.path, "/login/")
        self.assertEqual(parse_qs(parsed.query).get("auth_error"), ["no_email"])

    @patch("apps.frontend.page_views.exchange_google_code_for_tokens")
    def test_google_oauth_callback_handles_token_exchange_failure(self, mock_exchange_google_code_for_tokens):
        from apps.authentication.services.google_oauth import GoogleOAuthError

        session = self.web_client.session
        session["google_oauth_state"] = "state-789"
        session.save()

        mock_exchange_google_code_for_tokens.side_effect = GoogleOAuthError("token_exchange_failed")

        response = self.web_client.get(
            "/auth/google/callback/",
            {"code": "auth-code", "state": "state-789"},
        )

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.path, "/login/")
        self.assertEqual(parse_qs(parsed.query).get("auth_error"), ["token_exchange_failed"])

    @override_settings(
        GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET="test-client-secret",
        GOOGLE_REDIRECT_URI="http://testserver/auth/google/callback/",
    )
    @patch("apps.authentication.services.google_oauth.requests.post")
    def test_google_token_exchange_maps_invalid_client_response(self, mock_post):
        from apps.authentication.services.google_oauth import GoogleOAuthError, exchange_google_code_for_tokens

        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "invalid_client", "error_description": "Unauthorized"}
        mock_response.text = '{"error":"invalid_client","error_description":"Unauthorized"}'
        mock_post.return_value = mock_response

        with self.assertRaises(GoogleOAuthError) as ctx:
            exchange_google_code_for_tokens("debug-code")

        self.assertEqual(ctx.exception.code, "invalid_client")

    @patch("apps.frontend.page_views.fetch_google_user_profile")
    @patch("apps.frontend.page_views.exchange_google_code_for_tokens")
    def test_google_oauth_callback_handles_userinfo_failure(
        self,
        mock_exchange_google_code_for_tokens,
        mock_fetch_google_user_profile,
    ):
        from apps.authentication.services.google_oauth import GoogleOAuthError

        session = self.web_client.session
        session["google_oauth_state"] = "state-321"
        session.save()

        mock_exchange_google_code_for_tokens.return_value = {"access_token": "google-access-token"}
        mock_fetch_google_user_profile.side_effect = GoogleOAuthError("userinfo_failed")

        response = self.web_client.get(
            "/auth/google/callback/",
            {"code": "auth-code", "state": "state-321"},
        )

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.path, "/login/")
        self.assertEqual(parse_qs(parsed.query).get("auth_error"), ["userinfo_failed"])


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

    @patch("apps.analytics.views.detect_anomalies_ai")
    def test_frontend_analytics_endpoints_remain_compatible(self, mock_detect_anomalies_ai):
        self.create_transaction(amount=Decimal("1234.56"))
        self.create_transaction(amount=Decimal("2345.67"))
        self.api_client.force_authenticate(user=self.admin)

        mock_detect_anomalies_ai.return_value = {
            "anomalies": [
                {
                    "transaction_id": "1",
                    "anomaly_type": "round-number-bias",
                    "severity": "medium",
                    "risk_score": 64,
                    "description": "Suspicious leading-digit pattern",
                }
            ]
        }

        anomaly_response = self.api_client.post(
            "/api/v1/analytics/detect-anomalies/",
            {},
            format="json",
        )
        self.assertEqual(anomaly_response.status_code, 200)
        self.assertEqual(len(anomaly_response.data["anomalies"]), 1)

        benford_response = self.api_client.post(
            "/api/v1/analytics/benford-analysis/",
            {},
            format="json",
        )
        self.assertEqual(benford_response.status_code, 200)
        self.assertEqual(len(benford_response.data["actual_distribution"]), 9)
        self.assertEqual(len(benford_response.data["expected_distribution"]), 9)
        self.assertIn("suspicious", benford_response.data)


class FrontendRouteTests(BaseFinAITestCase):
    def test_public_landing_and_auth_pages_render_for_anonymous_users(self):
        for path in ["/", "/login/", "/register/"]:
            with self.subTest(path=path):
                response = self.web_client.get(path)
                self.assertEqual(response.status_code, 200)

    @override_settings(
        GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
        GOOGLE_CLIENT_SECRET="test-client-secret",
        GOOGLE_REDIRECT_URI="http://testserver/auth/google/callback/",
    )
    def test_login_page_links_google_oauth_when_configured(self):
        response = self.web_client.get("/login/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/auth/google/login/")
        self.assertNotContains(response, "Google Login غير مهيأ في الإعدادات")

    def test_login_page_shows_invalid_client_google_message(self):
        response = self.web_client.get("/login/", {"auth_error": "invalid_client"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Client ID")
        self.assertContains(response, "Client Secret")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_register_page_creates_user_and_redirects_to_otp_verification(self):
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
        self.assertTrue(payload["requires_verification"])
        self.assertEqual(payload["redirect"], "/verify-email/")

        user = User.objects.get(email="new-auditor@finai.sa")
        self.assertIsNone(user.organization_id)
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(self.web_client.session.get(PENDING_EMAIL_VERIFICATION_SESSION_KEY), str(user.id))
        self.assertIsNone(self.web_client.session.get("_auth_user_id"))
        self.assertEqual(len(mail.outbox), 1)

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


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailOTPFlowTests(BaseFinAITestCase):
    def _register_pending_user(self, email="otp-user@finai.sa"):
        response = self.web_client.post(
            "/register/",
            {
                "full_name": "OTP User",
                "email": email,
                "password": "StrongPass123!",
                "password_confirm": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        return User.objects.get(email=email)

    def _extract_last_otp(self):
        self.assertTrue(mail.outbox)
        match = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_verify_email_otp_marks_user_verified_and_logs_in(self):
        user = self._register_pending_user()
        otp_code = self._extract_last_otp()

        response = self.web_client.post(
            "/verify-email/",
            {"otp_code": otp_code},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["redirect"], "/dashboard/")
        self.assertIn("tokens", payload)

        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertEqual(str(user.id), self.web_client.session.get("_auth_user_id"))
        self.assertIsNone(self.web_client.session.get(PENDING_EMAIL_VERIFICATION_SESSION_KEY))

        verification = EmailOTPVerification.objects.get(user=user)
        self.assertTrue(verification.is_used)

    def test_invalid_email_otp_increments_attempt_counter(self):
        user = self._register_pending_user("wrong-otp@finai.sa")

        response = self.web_client.post(
            "/verify-email/",
            {"otp_code": "000000"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        verification = EmailOTPVerification.objects.get(user=user)
        self.assertEqual(verification.attempts_count, 1)
        self.assertFalse(user.is_email_verified)

    def test_resend_endpoint_is_throttled_until_cooldown_finishes(self):
        self._register_pending_user("resend-otp@finai.sa")

        response = self.web_client.post(
            "/verify-email/resend/",
            {},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 429)
        payload = response.json()
        self.assertIn("error", payload)
        self.assertGreater(payload.get("retry_after", 0), 0)

    @patch("apps.frontend.page_views.issue_email_otp")
    def test_verify_page_surfaces_initial_otp_send_failure(self, mock_issue_email_otp):
        from apps.authentication.services.email_otp import EmailOTPError

        pending_user = User.objects.create_user(
            email="otp-failure@finai.sa",
            password="StrongPass123!",
            full_name="OTP Failure",
            role=User.Role.JUNIOR_AUDITOR,
            organization=None,
            email_verified_at=None,
        )
        session = self.web_client.session
        session[PENDING_EMAIL_VERIFICATION_SESSION_KEY] = str(pending_user.id)
        session.save()

        mock_issue_email_otp.side_effect = EmailOTPError(
            "تعذر إرسال رمز التحقق حالياً. يرجى المحاولة مرة أخرى بعد قليل.",
            code="send_failed",
        )

        response = self.web_client.get("/verify-email/")

        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "تعذر إرسال رمز التحقق حالياً", status_code=503)

    def test_send_test_otp_email_command_uses_real_otp_service(self):
        stdout = StringIO()

        call_command(
            "send_test_otp_email",
            "command-otp@finai.sa",
            "--create-if-missing",
            stdout=stdout,
        )

        user = User.objects.get(email="command-otp@finai.sa")
        challenge = EmailOTPVerification.objects.get(user=user)

        self.assertFalse(user.is_email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(challenge.id), stdout.getvalue())
        self.assertIn("OTP email sent successfully.", stdout.getvalue())
