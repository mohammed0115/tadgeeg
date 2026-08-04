from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings


@override_settings(LANGUAGE_CODE="ar")
class AuthPortalErrorMappingTests(TestCase):
    """Error-message *mapping*, asserted in Arabic.

    These pin the exact Arabic sentences the portal returns, but
    `finai_backend/settings/test.py` sets LANGUAGE_CODE="en" so the suite can
    assert stable English source strings. Without the override the tests were
    comparing Arabic expectations against English output and failing on the
    language, never reaching the thing they exist to check: that a wrong
    password does NOT return the "email already registered" message, which
    would tell an attacker which addresses have accounts.
    """

    def setUp(self):
        self.client = Client()
        self.client.cookies["django_language"] = "ar"
        self.user_model = get_user_model()

    def test_login_invalid_credentials_do_not_use_register_duplicate_email_message(self):
        self.user_model.objects.create_user(
            email="admin@finai.com",
            password="CorrectPass123!",
            full_name="Admin User",
        )

        response = self.client.post(
            "/login/",
            {"email": "admin@finai.com", "password": "WrongPass123!"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {
                "success": False,
                "error": "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
            },
        )

    def test_register_duplicate_email_keeps_register_specific_message(self):
        self.user_model.objects.create_user(
            email="admin@finai.com",
            password="CorrectPass123!",
            full_name="Admin User",
        )

        response = self.client.post(
            "/register/",
            {
                "full_name": "Another Admin",
                "email": "admin@finai.com",
                "password": "CorrectPass123!",
                "password_confirm": "CorrectPass123!",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {
                "success": False,
                "error": "هذا البريد الإلكتروني مستخدم بالفعل.",
            },
        )
