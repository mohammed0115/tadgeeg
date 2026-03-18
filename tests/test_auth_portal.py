from django.contrib.auth import get_user_model
from django.test import Client, TestCase


class AuthPortalErrorMappingTests(TestCase):
    def setUp(self):
        self.client = Client()
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
