from django.conf import settings
from django.test import Client, SimpleTestCase


class I18nTemplateTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_login_page_uses_rtl_for_arabic(self):
        """System is Arabic-only — always renders RTL Arabic"""
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="ar"', content)
        self.assertIn('dir="rtl"', content)

    def test_login_page_always_arabic(self):
        """System is Arabic-only — no language switching"""
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        # Always Arabic RTL regardless of any cookie
        self.assertIn('lang="ar"', content)
        self.assertIn('dir="rtl"', content)

    def test_branding_is_centralized_on_public_pages(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Tadgeeg AI", content)
        self.assertTrue(settings.COMPANY_NAME in content or settings.COMPANY_NAME_AR in content)

    def test_branding_is_exposed_on_auth_pages(self):
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Tadgeeg AI", content)
