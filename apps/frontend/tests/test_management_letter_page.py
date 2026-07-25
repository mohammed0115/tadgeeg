"""TADGEEG-FIN-AUDIT-9B — Management Letter frontend tests."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.control_deficiency_models import AuditControlDeficiency
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import management_letter as ml
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_D = AuditControlDeficiency


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

    def _url(self, eng=None):
        return f"{reverse('frontend:management_letter')}?engagement={(eng or self.eng).id}"

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("frontend:management_letter")).status_code, 302)

    def test_junior_denied(self):
        self.client.force_login(_junior(self.org))
        self.assertEqual(self.client.get(reverse("frontend:management_letter")).status_code, 403)

    def test_create_deficiency_from_ui(self):
        resp = self.client.post(reverse("frontend:management_letter"), {
            "engagement": str(self.eng.id), "action": "create",
            "title": "Missing approvals", "classification": "significant_deficiency",
            "area": "procurement_payables", "recommendation": "Add approval step"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AuditControlDeficiency.objects.filter(engagement=self.eng).exists())

    def test_record_response_and_status_from_ui(self):
        d = ml.create_deficiency(engagement=self.eng, actor=self.auditor, title="X")
        self.client.post(reverse("frontend:management_letter"), {
            "engagement": str(self.eng.id), "action": "respond",
            "deficiency": str(d.id), "management_response": "We agree", "owner": "CFO"})
        d.refresh_from_db()
        self.assertEqual(d.management_response, "We agree")
        self.client.post(reverse("frontend:management_letter"), {
            "engagement": str(self.eng.id), "action": "status",
            "deficiency": str(d.id), "status": "remediated"})
        d.refresh_from_db()
        self.assertEqual(d.status, _D.Status.REMEDIATED)

    def test_register_renders_with_export_links(self):
        ml.create_deficiency(engagement=self.eng, actor=self.auditor,
                             title="Weak control", classification="material_weakness")
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-sec="register"')
        self.assertContains(resp, "DEF-00001")
        self.assertContains(resp, "management-letter/?format=html")

    def test_no_engagement_state(self):
        resp = self.client.get(reverse("frontend:management_letter"))
        self.assertContains(resp, "Choose an engagement")

    def test_cross_org_engagement_ignored(self):
        other = _eng(_org("OrgB"), code="B-1")
        resp = self.client.get(self._url(other))
        self.assertContains(resp, "Choose an engagement")
