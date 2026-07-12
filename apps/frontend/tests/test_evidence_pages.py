"""TADGEEG-FIN-AUDIT-6A — Evidence Request frontend page tests.

Covers: login required, org scoping (list + detail), create page for own org,
cross-org 404, attachment upload from the detail page, review actions rendered
for auditor+ and hidden/denied for junior users, status badges, and event
history rendering.
"""
from __future__ import annotations

from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.engagement_models import AuditEngagement
from apps.audit.evidence_models import AuditEvidenceRequest
from apps.audit.general_ledger_models import (
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_FS = GeneralLedgerRiskFinding.Status
PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}


def _activate_subscription(org):
    """Give the org a usable subscription so the billing gate lets UI pages through."""
    if not Plan.objects.filter(code=PlanCode.BUSINESS).exists():
        call_command("seed_billing_plans", stdout=StringIO())
    svc = SubscriptionService()
    plan = Plan.objects.get(code=PlanCode.BUSINESS)
    sub = svc.create_pending_paid_subscription(org, plan)
    svc.activate_subscription(sub)


def _org(name="Acme"):
    org = Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)
    _activate_subscription(org)
    return org


def _user(org, email="a@e.com", role=None):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=role or User.Role.SENIOR_AUDITOR, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31", materiality=PROFILE)


def _finding(eng):
    imp = GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="t",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal("20000"), account_code="6000", status=_FS.NEEDS_EVIDENCE)


class AuthTests(TestCase):
    def test_list_requires_login(self):
        resp = self.client.get(reverse("frontend:evidence_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])


class ListAndScopingTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA"); self.user = _user(self.org)
        self.eng = _eng(self.org); self.finding = _finding(self.eng)
        self.req = ev.create_evidence_request(
            engagement=self.eng, actor=self.user, title="Need invoice",
            gl_finding=self.finding)
        self.client.force_login(self.user)

    def test_list_shows_own_org_requests_with_badge(self):
        resp = self.client.get(reverse("frontend:evidence_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Need invoice")
        # Status badge for 'open' rendered.
        self.assertContains(resp, 'class="badge open"')

    def test_list_excludes_other_org(self):
        other = _org("OrgB"); ouser = _user(other, email="o@e.com")
        oeng = _eng(other, code="B-1"); ofinding = _finding(oeng)
        ev.create_evidence_request(engagement=oeng, actor=ouser,
                                   title="OTHER-ORG-SECRET", gl_finding=ofinding)
        resp = self.client.get(reverse("frontend:evidence_list"))
        self.assertNotContains(resp, "OTHER-ORG-SECRET")

    def test_detail_cross_org_404(self):
        other = _org("OrgC"); ouser = _user(other, email="c@e.com")
        oeng = _eng(other, code="C-1"); ofinding = _finding(oeng)
        oreq = ev.create_evidence_request(engagement=oeng, actor=ouser,
                                          title="x", gl_finding=ofinding)
        resp = self.client.get(reverse("frontend:evidence_detail", args=[oreq.id]))
        self.assertEqual(resp.status_code, 404)


class CreateTests(TestCase):
    def setUp(self):
        self.org = _org(); self.user = _user(self.org)
        self.eng = _eng(self.org); self.finding = _finding(self.eng)
        self.client.force_login(self.user)

    def test_create_page_renders(self):
        resp = self.client.get(reverse("frontend:evidence_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Request Evidence")

    def test_create_post_creates_request(self):
        resp = self.client.post(reverse("frontend:evidence_create"), {
            "engagement": str(self.eng.id), "gl_finding": str(self.finding.id),
            "title": "Provide invoice", "request_reason": "invoice_support",
            "priority": "high",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(AuditEvidenceRequest.objects.filter(
            organization=self.org, title="Provide invoice").exists())

    def test_junior_cannot_open_create_page(self):
        junior = _user(self.org, email="j@e.com", role=User.Role.JUNIOR_AUDITOR)
        self.client.force_login(junior)
        resp = self.client.get(reverse("frontend:evidence_create"))
        self.assertEqual(resp.status_code, 403)


class DetailActionTests(TestCase):
    def setUp(self):
        self.org = _org(); self.user = _user(self.org)
        self.eng = _eng(self.org); self.finding = _finding(self.eng)
        self.req = ev.create_evidence_request(
            engagement=self.eng, actor=self.user, title="Need doc",
            gl_finding=self.finding)
        self.client.force_login(self.user)

    def _url(self):
        return reverse("frontend:evidence_detail", args=[self.req.id])

    def test_detail_renders_actions_and_history(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        # Assert on non-translated markers (UI labels may render in Arabic).
        self.assertContains(resp, 'class="timeline"')          # event history
        self.assertContains(resp, 'name="action" value="submit"')  # a review action button
        self.assertContains(resp, 'class="act-btn act-upload"')    # upload button
        self.assertContains(resp, 'value="upload"')                # upload form action

    def test_upload_attachment_from_detail(self):
        f = SimpleUploadedFile("evidence.pdf", b"hello", content_type="application/pdf")
        resp = self.client.post(self._url(), {"action": "upload", "file": f,
                                              "description": "the invoice"})
        self.assertEqual(resp.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.attachments.count(), 1)
        self.assertContains(resp, "evidence.pdf")

    def test_review_flow_via_detail(self):
        f = SimpleUploadedFile("e.pdf", b"x", content_type="application/pdf")
        self.client.post(self._url(), {"action": "upload", "file": f})
        self.client.post(self._url(), {"action": "submit"})
        self.client.post(self._url(), {"action": "under_review"})
        resp = self.client.post(self._url(), {"action": "accept"})
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, AuditEvidenceRequest.Status.ACCEPTED)
        self.assertContains(resp, 'class="badge accepted"')

    def test_junior_cannot_post_actions(self):
        junior = _user(self.org, email="j2@e.com", role=User.Role.JUNIOR_AUDITOR)
        self.client.force_login(junior)
        # Junior can view...
        self.assertEqual(self.client.get(self._url()).status_code, 200)
        # ...but not act.
        resp = self.client.post(self._url(), {"action": "submit"})
        self.assertEqual(resp.status_code, 403)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, AuditEvidenceRequest.Status.OPEN)
