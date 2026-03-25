import uuid
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import resolve

from apps.authentication.models import Organization, User
from core.auth.redirect_service import _is_safe_org_redirect, get_post_login_redirect
from core.permissions import (
    IsOrganizationAdmin,
    IsOrganizationMember,
    IsPlatformAdmin,
    get_effective_org_role,
    get_effective_platform_role,
    is_org_admin,
    is_org_auditor,
    is_org_member,
    is_platform_user,
    org_member_required,
    platform_admin_required,
)


def make_user(**kwargs):
    user = MagicMock()
    user.id = kwargs.get("id", uuid.uuid4())
    user.is_authenticated = kwargs.get("is_authenticated", True)
    user.is_staff = kwargs.get("is_staff", False)
    user.is_superuser = kwargs.get("is_superuser", False)
    user.role = kwargs.get("role", User.Role.ADMIN)
    user.organization_id = kwargs.get("organization_id")
    user.organization = kwargs.get("organization")
    user.email_verified_at = kwargs.get("email_verified_at", "2026-01-01")
    user.is_email_verified = kwargs.get("is_email_verified", True)
    user.email = kwargs.get("email", "user@example.com")
    return user


class PermissionHelperTests(TestCase):
    def test_platform_user_is_staff(self):
        self.assertTrue(is_platform_user(make_user(is_staff=True)))

    def test_org_member_requires_real_org_context(self):
        self.assertTrue(is_org_member(make_user(organization_id=uuid.uuid4())))
        self.assertFalse(is_org_member(make_user()))

    def test_platform_staff_is_not_treated_as_org_member(self):
        self.assertFalse(is_org_member(make_user(is_staff=True, organization_id=uuid.uuid4())))

    def test_org_admin_and_auditor_roles(self):
        self.assertTrue(is_org_admin(make_user(organization_id=uuid.uuid4(), role=User.Role.ADMIN)))
        self.assertTrue(is_org_auditor(make_user(organization_id=uuid.uuid4(), role=User.Role.SENIOR_AUDITOR)))
        self.assertFalse(is_org_auditor(make_user(organization_id=uuid.uuid4(), role=User.Role.FINANCE_MANAGER)))

    def test_effective_roles(self):
        self.assertEqual(get_effective_platform_role(make_user(is_staff=True, is_superuser=True)), "PLATFORM_SUPER_ADMIN")
        self.assertEqual(get_effective_org_role(make_user(organization_id=uuid.uuid4(), role=User.Role.ADMIN)), "ORG_ADMIN")
        self.assertIsNone(get_effective_platform_role(make_user()))


class DRFPermissionTests(TestCase):
    def _request(self, user):
        request = MagicMock()
        request.user = user
        return request

    def test_is_platform_admin(self):
        permission = IsPlatformAdmin()
        self.assertTrue(permission.has_permission(self._request(make_user(is_staff=True)), None))
        self.assertFalse(permission.has_permission(self._request(make_user(organization_id=uuid.uuid4())), None))

    def test_is_organization_member(self):
        permission = IsOrganizationMember()
        self.assertTrue(permission.has_permission(self._request(make_user(organization_id=uuid.uuid4())), None))
        self.assertFalse(permission.has_permission(self._request(make_user(is_staff=True, organization_id=uuid.uuid4())), None))

    def test_is_organization_admin(self):
        permission = IsOrganizationAdmin()
        self.assertTrue(permission.has_permission(self._request(make_user(organization_id=uuid.uuid4(), role=User.Role.ADMIN)), None))
        self.assertFalse(permission.has_permission(self._request(make_user(organization_id=uuid.uuid4(), role=User.Role.JUNIOR_AUDITOR)), None))


class DecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _ok_view(self, request, *args, **kwargs):
        from django.http import HttpResponse
        return HttpResponse("ok")

    def test_platform_admin_required_blocks_org_user(self):
        request = self.factory.get("/platform-admin/")
        request.user = make_user(organization_id=uuid.uuid4())
        response = platform_admin_required(self._ok_view)(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard/", response["Location"])

    def test_org_member_required_blocks_platform_user(self):
        request = self.factory.get("/dashboard/")
        request.user = make_user(is_staff=True)
        response = org_member_required(self._ok_view)(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/platform-admin/", response["Location"])


class RedirectServiceTests(TestCase):
    def test_platform_users_go_to_platform_admin(self):
        self.assertEqual(get_post_login_redirect(make_user(is_staff=True)), "/platform-admin/")

    def test_org_users_go_to_vendor_dashboard(self):
        self.assertEqual(get_post_login_redirect(make_user(organization_id=uuid.uuid4())), "/dashboard/")

    def test_platform_priority_is_clear_for_dual_context_users(self):
        self.assertEqual(
            get_post_login_redirect(make_user(is_staff=True, organization_id=uuid.uuid4())),
            "/platform-admin/",
        )

    def test_org_next_url_must_stay_inside_vendor_namespace(self):
        self.assertEqual(
            get_post_login_redirect(make_user(organization_id=uuid.uuid4()), next_url="/dashboard/files/"),
            "/dashboard/files/",
        )
        self.assertEqual(
            get_post_login_redirect(make_user(organization_id=uuid.uuid4()), next_url="/platform-admin/settings/"),
            "/dashboard/",
        )
        self.assertFalse(_is_safe_org_redirect("https://evil.example"))


class NavigationDefinitionTests(TestCase):
    def test_platform_menu_uses_platform_namespace_only(self):
        from navigation.platform_menu import PLATFORM_MENU

        labels = [section["section_label_ar"] for section in PLATFORM_MENU]
        self.assertIn("الرئيسية", labels)
        self.assertIn("إدارة المحتوى", labels)

        route_names = [item["route_name"] for section in PLATFORM_MENU for item in section["items"]]
        self.assertTrue(all(route_name.startswith("platform_admin:") for route_name in route_names))

    def test_vendor_menu_uses_vendor_namespace_only(self):
        from navigation.vendor_menu import VENDOR_MENU

        labels = [section["section_label_ar"] for section in VENDOR_MENU]
        self.assertIn("الرئيسية", labels)
        self.assertIn("الملفات", labels)

        route_names = [item["route_name"] for section in VENDOR_MENU for item in section["items"]]
        self.assertTrue(all(route_name.startswith("vendor_dashboard:") for route_name in route_names))


class SplitDashboardIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Acme Org", name_ar="أكمي")
        user_model = get_user_model()

        cls.org_user = user_model.objects.create_user(
            email="org@example.com",
            password="StrongPass123!",
            full_name="Org User",
            role=User.Role.ADMIN,
            organization=cls.organization,
        )
        cls.platform_user = user_model.objects.create_user(
            email="platform@example.com",
            password="StrongPass123!",
            full_name="Platform Admin",
            role=User.Role.ADMIN,
            is_staff=True,
        )

    def setUp(self):
        self.client = Client()

    def test_dashboard_url_resolves_to_vendor_namespace(self):
        match = resolve("/dashboard/")
        self.assertEqual(match.namespace, "vendor_dashboard")

    def test_platform_admin_url_resolves_to_platform_namespace(self):
        match = resolve("/platform-admin/")
        self.assertEqual(match.namespace, "platform_admin")

    def test_org_user_cannot_access_platform_admin(self):
        self.client.force_login(self.org_user)
        response = self.client.get("/platform-admin/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/dashboard/")

    def test_platform_user_cannot_access_vendor_dashboard(self):
        self.client.force_login(self.platform_user)
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/platform-admin/")

    def test_platform_route_uses_platform_layout_and_sidebar(self):
        self.client.force_login(self.platform_user)
        response = self.client.get("/platform-admin/")
        self.assertContains(response, 'data-console-context="platform_admin"')
        self.assertContains(response, "/platform-admin/organizations/")
        self.assertNotContains(response, "/dashboard/files/")

    def test_vendor_route_uses_vendor_layout_and_sidebar(self):
        self.client.force_login(self.org_user)
        response = self.client.get("/dashboard/")
        self.assertContains(response, 'data-console-context="vendor_dashboard"')
        self.assertContains(response, "/dashboard/files/")
        self.assertContains(response, "Acme Org")
        self.assertNotContains(response, "/platform-admin/organizations/")
