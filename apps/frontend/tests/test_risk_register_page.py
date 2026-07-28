"""TADGEEG-G2.2 — Risk Register frontend tests."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.assessed_risk_models import AssessedRisk
from apps.audit.engagement_models import AuditEngagement
from apps.audit.procedure_models import AuditProcedure
from apps.audit.services import assessed_risk as ar
from apps.audit.services import audit_procedure as ap
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService


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
        return f"{reverse('frontend:risk_register')}?engagement={(eng or self.eng).id}"

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("frontend:risk_register")).status_code, 302)

    def test_junior_denied(self):
        self.client.force_login(_junior(self.org))
        self.assertEqual(self.client.get(reverse("frontend:risk_register")).status_code, 403)

    def test_no_engagement_state(self):
        self.assertContains(self.client.get(reverse("frontend:risk_register")),
                            "Choose an engagement")

    def test_create_risk_from_ui(self):
        resp = self.client.post(reverse("frontend:risk_register"), {
            "engagement": str(self.eng.id), "action": "create_risk",
            "title": "Revenue cut-off", "fs_area": "revenue", "assertion": "cutoff",
            "inherent_risk": "high", "control_risk": "high", "is_significant": "on"})
        self.assertEqual(resp.status_code, 200)
        r = AssessedRisk.objects.get(engagement=self.eng)
        self.assertEqual(r.combined_risk, "significant")

    def test_create_procedure_under_risk(self):
        r = ar.create_risk(engagement=self.eng, actor=self.auditor, title="R")
        self.client.post(reverse("frontend:risk_register"), {
            "engagement": str(self.eng.id), "action": "create_procedure",
            "assessed_risk": str(r.id), "title": "Cut-off testing",
            "nature": "test_of_details", "extent": "increased"})
        p = AuditProcedure.objects.get(engagement=self.eng)
        self.assertEqual(p.assessed_risk_id, r.id)

    def test_request_evidence_for_procedure(self):
        r = ar.create_risk(engagement=self.eng, actor=self.auditor, title="R")
        p = ap.create_procedure(engagement=self.eng, actor=self.auditor,
                                title="P", assessed_risk=r)
        self.client.post(reverse("frontend:risk_register"), {
            "engagement": str(self.eng.id), "action": "request_evidence",
            "procedure": str(p.id)})
        self.assertEqual(p.evidence_requests.count(), 1)

    def test_register_renders_chain(self):
        r = ar.create_risk(engagement=self.eng, actor=self.auditor, title="Revenue cut-off")
        ap.create_procedure(engagement=self.eng, actor=self.auditor,
                            title="Cut-off testing", assessed_risk=r)
        resp = self.client.get(self._url())
        self.assertContains(resp, "RISK-00001")
        self.assertContains(resp, "PROC-00001")
        self.assertContains(resp, 'data-sec="register"')

    def test_cross_org_ignored(self):
        other = _eng(_org("OrgB"), code="B-1")
        self.assertContains(self.client.get(self._url(other)), "Choose an engagement")
