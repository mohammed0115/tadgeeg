from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import OrganizationSettings


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
