"""TADGEEG-FIN-AUDIT-9D — Substantive Testing frontend tests."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import substantive_testing as st
from apps.audit.substantive_test_models import SubstantiveTestItem
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_I = SubstantiveTestItem


def _activate_subscription(org):
    if not Plan.objects.filter(code=PlanCode.BUSINESS).exists():
        call_command("seed_billing_plans", stdout=StringIO())
    svc = SubscriptionService()
    svc.activate_subscription(
        svc.create_pending_paid_subscription(org, Plan.objects.get(code=PlanCode.BUSINESS)))


def _org(name="Acme"):
    org = Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)
    _activate_subscription(org)
    return org


def _auditor(org, email="auditor@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _junior(org, email="junior@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Jun Ior",
        role=User.Role.JUNIOR_AUDITOR, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


class PageTests(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)
        self.client.force_login(self.auditor)

    def _url(self, eng=None, area="inventory"):
        return f"{reverse('frontend:substantive_testing')}?engagement={(eng or self.eng).id}&area={area}"

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("frontend:substantive_testing")).status_code, 302)

    def test_junior_denied(self):
        self.client.force_login(_junior(self.org))
        self.assertEqual(
            self.client.get(reverse("frontend:substantive_testing")).status_code, 403)

    def test_no_engagement_state(self):
        resp = self.client.get(reverse("frontend:substantive_testing"))
        self.assertContains(resp, "Choose an engagement")

    def test_create_inventory_item_with_recompute(self):
        resp = self.client.post(reverse("frontend:substantive_testing"), {
            "engagement": str(self.eng.id), "area": "inventory", "action": "create",
            "item_reference": "SKU-9", "book_value": "400",
            "quantity_counted": "30", "unit_cost": "12.5"})
        self.assertEqual(resp.status_code, 200)
        it = SubstantiveTestItem.objects.get(engagement=self.eng)
        self.assertEqual(str(it.tested_value), "375.0000")
        self.assertEqual(it.status, _I.Status.VARIANCE)

    def test_create_fixed_asset_item_with_recompute(self):
        resp = self.client.post(reverse("frontend:substantive_testing"), {
            "engagement": str(self.eng.id), "area": "fixed_assets", "action": "create",
            "item_reference": "FA-1", "book_value": "6400",
            "cost": "10000", "salvage": "1000",
            "useful_life_years": "5", "elapsed_years": "2"})
        self.assertEqual(resp.status_code, 200)
        it = SubstantiveTestItem.objects.get(engagement=self.eng, area="fixed_assets")
        self.assertEqual(str(it.tested_value), "6400.0000")
        self.assertEqual(it.status, _I.Status.MATCHED)

    def test_record_tested_from_ui(self):
        it = st.create_item(engagement=self.eng, actor=self.auditor,
                            area=_I.Area.INVENTORY, book_value="100", tolerance="5")
        self.client.post(reverse("frontend:substantive_testing"), {
            "engagement": str(self.eng.id), "area": "inventory", "action": "record",
            "item": str(it.id), "tested_value": "103"})
        it.refresh_from_db()
        self.assertEqual(it.status, _I.Status.MATCHED)

    def test_register_renders_with_tabs_and_summary_link(self):
        st.create_item(engagement=self.eng, actor=self.auditor,
                       area=_I.Area.INVENTORY, book_value="400",
                       inputs={"quantity": "30", "unit_cost": "12.5"})
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-sec="register"')
        self.assertContains(resp, "SUB-00001")
        self.assertContains(resp, "substantive-summary/")
        self.assertContains(resp, 'class="mod-tabs"')

    def test_area_tab_filters_items(self):
        st.create_item(engagement=self.eng, actor=self.auditor,
                       area=_I.Area.INVENTORY, book_value="10")
        st.create_item(engagement=self.eng, actor=self.auditor,
                       area=_I.Area.PAYROLL, book_value="20")
        inv = self.client.get(self._url(area="inventory"))
        self.assertContains(inv, "SUB-00001")
        self.assertNotContains(inv, "SUB-00002")
        pay = self.client.get(self._url(area="payroll"))
        self.assertContains(pay, "SUB-00002")

    def test_cross_org_engagement_ignored(self):
        other = _eng(_org("OrgB"), code="B-1")
        resp = self.client.get(self._url(other))
        self.assertContains(resp, "Choose an engagement")
