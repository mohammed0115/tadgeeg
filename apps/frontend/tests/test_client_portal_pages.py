"""TADGEEG-FIN-AUDIT-6B — Client portal & host page frontend tests.

Covers the client-portal pages (list/detail/upload/explanation/submit/timeline),
the auditor host pages added to carry the required evidence affordances
(GL finding / SAD item / readiness), the dashboard evidence widget, and the
security rules: login required, per-request client scoping, cross-org 404, and
that a client can never review evidence from the UI.
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
from apps.audit.services import audit_difference_summary as sad
from apps.audit.services import audit_readiness_workpaper as readiness
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_R = AuditEvidenceRequest
_FS = GeneralLedgerRiskFinding.Status
PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}


def _activate_subscription(org):
    """Satisfy the billing gate so UI pages render instead of redirecting."""
    if not Plan.objects.filter(code=PlanCode.BUSINESS).exists():
        call_command("seed_billing_plans", stdout=StringIO())
    svc = SubscriptionService()
    sub = svc.create_pending_paid_subscription(org, Plan.objects.get(code=PlanCode.BUSINESS))
    svc.activate_subscription(sub)


def _org(name="Acme"):
    org = Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)
    _activate_subscription(org)
    return org


def _auditor(org, email="auditor@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _client_user(org, email="client@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Cli Ent",
        role=User.Role.FINANCE_MANAGER, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31", materiality=PROFILE)


def _finding(eng, *, status=_FS.NEEDS_EVIDENCE, amount="20000"):
    imp = GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="Unusual entry",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal(amount), account_code="6000", status=status)


def _f(name="evidence.pdf", content=b"hello"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class Base(TestCase):
    def setUp(self):
        self.org = _org()
        self.auditor = _auditor(self.org)
        self.client_user = _client_user(self.org)
        self.eng = _eng(self.org)
        self.finding = _finding(self.eng)
        self.req = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="Provide invoice",
            gl_finding=self.finding, assigned_client_user=self.client_user)


class AuthTests(Base):
    def test_client_portal_requires_login(self):
        resp = self.client.get(reverse("frontend:client_evidence_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])


class ClientPortalListTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.client_user)

    def test_list_shows_assigned_request_with_badges(self):
        resp = self.client.get(reverse("frontend:client_evidence_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Provide invoice")
        self.assertContains(resp, self.req.request_number)
        self.assertContains(resp, 'class="badge open"')

    def test_list_hides_other_clients_requests(self):
        other = _client_user(self.org, "c2@e.com")
        ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="NOT-MINE",
            gl_finding=self.finding, assigned_client_user=other)
        resp = self.client.get(reverse("frontend:client_evidence_list"))
        self.assertNotContains(resp, "NOT-MINE")

    def test_list_filters_by_status(self):
        resp = self.client.get(reverse("frontend:client_evidence_list"),
                               {"status": "accepted"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Provide invoice")

    def test_list_search_by_request_number(self):
        resp = self.client.get(reverse("frontend:client_evidence_list"),
                               {"q": self.req.request_number})
        self.assertContains(resp, "Provide invoice")

    def test_list_overdue_filter(self):
        resp = self.client.get(reverse("frontend:client_evidence_list"),
                               {"overdue": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Provide invoice")  # no due date → not overdue


class ClientPortalDetailTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.client_user)

    def _url(self, req=None):
        return reverse("frontend:client_evidence_detail", args=[(req or self.req).id])

    def test_detail_renders_upload_and_timeline(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="dropzone"')        # drag & drop area
        self.assertContains(resp, 'class="timeline"')     # append-only history
        self.assertContains(resp, 'value="upload"')
        self.assertContains(resp, 'value="explain"')

    def test_cross_client_detail_is_404(self):
        other = _client_user(self.org, "c3@e.com")
        hidden = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="hidden",
            gl_finding=self.finding, assigned_client_user=other)
        self.assertEqual(self.client.get(self._url(hidden)).status_code, 404)

    def test_cross_org_detail_is_404(self):
        other_org = _org("OrgB")
        oa, oc = _auditor(other_org, "a2@e.com"), _client_user(other_org, "c4@e.com")
        oeng = _eng(other_org, code="B-1")
        foreign = ev.create_evidence_request(
            engagement=oeng, actor=oa, title="foreign",
            gl_finding=_finding(oeng), assigned_client_user=oc)
        self.assertEqual(self.client.get(self._url(foreign)).status_code, 404)

    def test_multi_file_upload(self):
        resp = self.client.post(self._url(), {
            "action": "upload",
            "files": [_f("a.pdf"), _f("b.xlsx")],
            "description": "supporting docs",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.req.attachments.count(), 2)

    def test_upload_rejects_disallowed_format_and_stores_nothing(self):
        resp = self.client.post(self._url(), {
            "action": "upload", "files": [_f("ok.pdf"), _f("bad.exe")]})
        self.assertEqual(resp.status_code, 200)
        # Whole batch rejected — no partial upload.
        self.assertEqual(self.req.attachments.count(), 0)

    def test_management_explanation_saved(self):
        self.client.post(self._url(), {
            "action": "explain", "management_explanation": "Late delivery."})
        self.req.refresh_from_db()
        self.assertEqual(self.req.management_explanation, "Late delivery.")

    def test_client_can_submit(self):
        self.client.post(self._url(), {"action": "upload", "files": [_f()]})
        self.client.post(self._url(), {"action": "submit"})
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, _R.Status.SUBMITTED)

    def test_client_cannot_review_from_portal(self):
        self.client.post(self._url(), {"action": "upload", "files": [_f()]})
        self.client.post(self._url(), {"action": "submit"})
        resp = self.client.post(self._url(), {"action": "accept"})
        self.req.refresh_from_db()
        self.assertNotEqual(self.req.status, _R.Status.ACCEPTED)
        self.assertContains(resp, "Unknown action")


class HostPageTests(Base):
    """The pages 6B added to host the required evidence affordances."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.auditor)

    def test_gl_finding_page_has_request_evidence_button(self):
        resp = self.client.get(reverse("frontend:gl_finding_detail", args=[self.finding.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "GL-RISK-DESC")
        self.assertContains(resp, reverse("frontend:evidence_create"))
        self.assertContains(resp, self.req.request_number)  # its evidence requests

    def test_gl_finding_cross_org_404(self):
        other_org = _org("OrgC")
        foreign = _finding(_eng(other_org, code="C-1"))
        resp = self.client.get(reverse("frontend:gl_finding_detail", args=[foreign.id]))
        self.assertEqual(resp.status_code, 404)

    def test_sad_item_page_lists_evidence(self):
        _finding(self.eng, status=_FS.ACCEPTED, amount="30000")
        summary = sad.recalculate_for_engagement(self.eng)
        item = summary.items.first()
        ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="SAD support",
            sad_item=item, assigned_client_user=self.client_user)
        resp = self.client.get(reverse("frontend:sad_item_detail", args=[item.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "SAD support")

    def test_readiness_page_shows_evidence_counts(self):
        _finding(self.eng, status=_FS.ACCEPTED, amount="30000")
        sad.recalculate_for_engagement(self.eng)
        wp = readiness.generate_for_engagement(self.eng)
        resp = self.client.get(reverse("frontend:readiness_evidence_summary", args=[wp.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Outstanding")
        self.assertContains(resp, self.req.request_number)
        # Safe wording preserved — never a formal opinion.
        self.assertNotContains(resp, "In our opinion")

    def test_readiness_cross_org_404(self):
        other_org = _org("OrgD")
        oeng = _eng(other_org, code="D-1")
        _finding(oeng, status=_FS.ACCEPTED)
        sad.recalculate_for_engagement(oeng)
        foreign_wp = readiness.generate_for_engagement(oeng)
        resp = self.client.get(
            reverse("frontend:readiness_evidence_summary", args=[foreign_wp.id]))
        self.assertEqual(resp.status_code, 404)


class DashboardWidgetTests(Base):
    def test_dashboard_shows_evidence_widget(self):
        self.client.force_login(self.auditor)
        resp = self.client.get(reverse("frontend:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Evidence Requests")
        self.assertContains(resp, reverse("frontend:evidence_list"))
