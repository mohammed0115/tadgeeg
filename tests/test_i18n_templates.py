from django.conf import settings
from django.test import Client, SimpleTestCase
from django.urls import reverse


class I18nTemplateTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_login_page_uses_rtl_for_arabic(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "ar"

        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="ar"', content)
        self.assertIn('dir="rtl"', content)

    def test_login_page_uses_ltr_for_english(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"

        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="en"', content)
        self.assertIn('dir="ltr"', content)

    def test_set_language_keeps_user_on_same_page(self):
        response = self.client.post(
            reverse("set_language"),
            {"language": "en", "next": "/login/"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login/")
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "en")

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
