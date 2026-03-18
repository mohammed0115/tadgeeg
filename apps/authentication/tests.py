from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from .models import Organization, OrganizationSettings
from .serializers import RegisterSerializer


class OrganizationBootstrapAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            full_name="Owner User",
        )
        self.client.force_authenticate(self.user)

    def test_user_without_organization_can_bootstrap_company_from_settings(self):
        org_response = self.client.get("/api/v1/auth/organization/")
        self.assertEqual(org_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(org_response.json()["id"])
        self.assertEqual(org_response.json()["country"], "SA")

        settings_response = self.client.get("/api/v1/auth/organization/settings/")
        self.assertEqual(settings_response.status_code, status.HTTP_200_OK)
        self.assertIn("financial", settings_response.json())
        self.assertIn("notifications", settings_response.json())

        create_response = self.client.patch(
            "/api/v1/auth/organization/",
            {
                "name": "Tadgeeg Labs",
                "country": "SA",
                "currency": "SAR",
                "industry": "Fintech",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.organization_id)
        self.assertEqual(self.user.role, get_user_model().Role.ADMIN)

        save_settings_response = self.client.post(
            "/api/v1/auth/organization/settings/",
            {
                "financial": {
                    "large_invoice_threshold": 25000,
                    "vat_rate": 15,
                },
                "notifications": {
                    "email_invoice_flagged": False,
                },
            },
            format="json",
        )
        self.assertEqual(save_settings_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            save_settings_response.json()["financial"]["large_invoice_threshold"],
            25000,
        )
        self.assertFalse(save_settings_response.json()["notifications"]["email_invoice_flagged"])

        settings_obj = OrganizationSettings.objects.get(organization=self.user.organization)
        self.assertEqual(settings_obj.financial["large_invoice_threshold"], 25000)
        self.assertFalse(settings_obj.notifications["email_invoice_flagged"])

        update_response = self.client.patch(
            "/api/v1/auth/organization/",
            {"website": "https://tadgeeg.com"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.json()["website"], "https://tadgeeg.com")


class RegistrationProvisioningTests(TestCase):
    def test_register_serializer_auto_provisions_organization_and_admin_role(self):
        serializer = RegisterSerializer(
            data={
                "email": "founder@example.com",
                "full_name": "Founding Team",
                "password": "StrongPass123!",
                "password_confirm": "StrongPass123!",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()

        self.assertIsNotNone(user.organization_id)
        self.assertEqual(user.role, get_user_model().Role.ADMIN)
        self.assertTrue(user.organization.name)
        self.assertTrue(OrganizationSettings.objects.filter(organization=user.organization).exists())


class UserIsolationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org_a = Organization.objects.create(name="Org A")
        self.org_b = Organization.objects.create(name="Org B")
        self.admin_a = get_user_model().objects.create_user(
            email="admin-a@example.com",
            password="StrongPass123!",
            full_name="Admin A",
            role=get_user_model().Role.ADMIN,
            organization=self.org_a,
        )
        self.member_a = get_user_model().objects.create_user(
            email="member-a@example.com",
            password="StrongPass123!",
            full_name="Member A",
            role=get_user_model().Role.JUNIOR_AUDITOR,
            organization=self.org_a,
        )
        self.admin_b = get_user_model().objects.create_user(
            email="admin-b@example.com",
            password="StrongPass123!",
            full_name="Admin B",
            role=get_user_model().Role.ADMIN,
            organization=self.org_b,
        )
        self.junior = get_user_model().objects.create_user(
            email="junior@example.com",
            password="StrongPass123!",
            full_name="Junior",
            role=get_user_model().Role.JUNIOR_AUDITOR,
            organization=self.org_a,
        )

    def test_org_admin_only_sees_same_organization_users(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.get("/api/v1/auth/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.json()["results"]}
        self.assertIn("admin-a@example.com", emails)
        self.assertIn("member-a@example.com", emails)
        self.assertNotIn("admin-b@example.com", emails)

    def test_non_admin_cannot_list_users(self):
        self.client.force_authenticate(self.junior)
        response = self.client.get("/api/v1/auth/users/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PublicMarketingPagesTests(TestCase):
    def test_public_marketing_pages_return_success(self):
        for path in ["/pricing/", "/about/", "/contact/", "/privacy/", "/blog/", "/integrations/", "/api/", "/careers/"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_200_OK)


class HealthEndpointTests(TestCase):
    @override_settings(HEALTH_REDIS_REQUIRED=False)
    @patch("core.services.monitoring.PipelineHealthCheck.check_redis")
    @patch("core.services.monitoring.PipelineHealthCheck.check_database")
    @patch("core.services.monitoring.PipelineHealthCheck.check_tesseract")
    @patch("core.services.monitoring.PipelineHealthCheck.check_stuck_documents")
    @patch("core.services.monitoring.PipelineHealthCheck.check_stuck_audit_sessions")
    def test_health_endpoint_stays_200_when_redis_is_optional(
        self,
        stuck_sessions_mock,
        stuck_documents_mock,
        tesseract_mock,
        database_mock,
        redis_mock,
    ):
        from core.services.monitoring import ComponentHealth, HealthStatus

        redis_mock.return_value = ComponentHealth("redis", HealthStatus.DEGRADED, "Unavailable")
        database_mock.return_value = ComponentHealth("database", HealthStatus.HEALTHY, "Connected")
        tesseract_mock.return_value = ComponentHealth("tesseract", HealthStatus.HEALTHY, "Ready")
        stuck_documents_mock.return_value = ComponentHealth("stuck_documents", HealthStatus.HEALTHY, "None")
        stuck_sessions_mock.return_value = ComponentHealth("stuck_audit_sessions", HealthStatus.HEALTHY, "None")

        response = self.client.get("/health/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["redis"], "degraded")
