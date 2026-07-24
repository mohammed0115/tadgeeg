"""TADGEEG-FIN-AUDIT-6D — Evidence assurance frontend tests.

Every 6D backend capability must have a UI entry point: assurance overview,
integrity report (with on-demand sweep), coverage report, evidence index,
retention policy, and the dashboard widgets — plus auditor-only permissions and
cross-organization isolation.
"""
from __future__ import annotations

from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.engagement_models import AuditEngagement
from apps.audit.evidence_models import AuditEvidenceRetentionPolicy
from apps.audit.general_ledger_models import (
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import evidence_assurance as assurance
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_P = AuditEvidenceRetentionPolicy
_FS = GeneralLedgerRiskFinding.Status
PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}


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


def _client_user(org, email="client@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Cli Ent",
        role=User.Role.FINANCE_MANAGER, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31", materiality=PROFILE)


def _finding(eng, code="GL-RISK-DESC"):
    imp = GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code=code, risk_title="t",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal("20000"), account_code="6000", status=_FS.NEEDS_EVIDENCE)


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
            gl_finding=self.finding, assigned_client_user=self.client_user,
            assigned_to=self.auditor)
        self.att = ev.add_attachment(request=self.req, actor=self.client_user,
                                     uploaded_file=_f())
        self.client.force_login(self.auditor)

    ALL_PAGES = ("assurance_overview", "assurance_integrity", "assurance_coverage",
                 "assurance_index", "assurance_retention")


class AccessTests(Base):
    def test_all_pages_require_login(self):
        self.client.logout()
        for name in self.ALL_PAGES:
            resp = self.client.get(reverse(f"frontend:{name}"))
            self.assertEqual(resp.status_code, 302, name)

    def test_all_pages_denied_for_client_user(self):
        self.client.force_login(self.client_user)
        for name in self.ALL_PAGES:
            resp = self.client.get(reverse(f"frontend:{name}"))
            self.assertEqual(resp.status_code, 403, name)

    def test_all_pages_render_for_auditor(self):
        for name in self.ALL_PAGES:
            resp = self.client.get(reverse(f"frontend:{name}"))
            self.assertEqual(resp.status_code, 200, name)


class OverviewPageTests(Base):
    def test_overview_shows_assurance_widgets(self):
        resp = self.client.get(reverse("frontend:assurance_overview"))
        self.assertContains(resp, "Evidence Assurance")
        self.assertContains(resp, "Integrity")
        self.assertContains(resp, "Coverage")
        # Sub-navigation to every 6D report is present.
        self.assertContains(resp, reverse("frontend:assurance_integrity"))
        self.assertContains(resp, reverse("frontend:assurance_coverage"))
        self.assertContains(resp, reverse("frontend:assurance_index"))
        self.assertContains(resp, reverse("frontend:assurance_retention"))


class IntegrityPageTests(Base):
    def test_sweep_runs_from_ui(self):
        resp = self.client.post(reverse("frontend:assurance_integrity"),
                                {"action": "sweep"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sweep complete")
        self.att.refresh_from_db()
        self.assertEqual(self.att.verification_result, "ok")

    def test_failure_visible_in_report(self):
        with open(self.att.uploaded_file.path, "wb") as fh:
            fh.write(b"TAMPERED")
        resp = self.client.post(reverse("frontend:assurance_integrity"),
                                {"action": "sweep"})
        self.assertContains(resp, "hash_mismatch")
        self.att.refresh_from_db()
        self.assertEqual(self.att.verification_result, "hash_mismatch")

    def test_pending_bucket_before_sweep(self):
        resp = self.client.get(reverse("frontend:assurance_integrity"))
        self.assertContains(resp, "pending_verification")


class CoveragePageTests(Base):
    def test_coverage_page_lists_finding(self):
        resp = self.client.get(reverse("frontend:assurance_coverage"))
        self.assertContains(resp, "GL-RISK-DESC")
        self.assertContains(resp, 'class="cov none"')  # nothing accepted yet

    def test_coverage_reflects_acceptance(self):
        ev.submit_evidence(request=self.req, actor=self.client_user)
        ev.review_evidence_request(request=self.req, actor=self.auditor,
                                   action="under_review")
        ev.review_evidence_request(request=self.req, actor=self.auditor, action="accept")
        resp = self.client.get(reverse("frontend:assurance_coverage"))
        self.assertContains(resp, 'class="cov complete"')


class EvidenceIndexPageTests(Base):
    def test_index_page_lists_evidence_without_download_links(self):
        resp = self.client.get(reverse("frontend:assurance_index"))
        self.assertContains(resp, "EV-00001")
        self.assertContains(resp, self.req.request_number)
        # The index deliberately exposes no download URLs.
        self.assertNotContains(resp, "/download/")


class RetentionPageTests(Base):
    def test_set_and_apply_policy_from_ui(self):
        resp = self.client.post(reverse("frontend:assurance_retention"), {
            "engagement": str(self.eng.id), "policy": _P.Policy.YEARS_10,
            "reason": "statutory", "apply": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Policy applied")
        policy = _P.objects.get(engagement=self.eng)
        self.assertEqual(policy.policy, _P.Policy.YEARS_10)
        self.att.refresh_from_db()
        self.assertIsNotNone(self.att.retention_until)

    def test_policy_requires_engagement(self):
        resp = self.client.post(reverse("frontend:assurance_retention"),
                                {"policy": _P.Policy.YEARS_7})
        self.assertContains(resp, "Choose an engagement")

    def test_cross_org_engagement_not_selectable(self):
        other_eng = _eng(_org("OrgB"), code="B-1")
        resp = self.client.get(reverse("frontend:assurance_retention"),
                               {"engagement": str(other_eng.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "B-1")


class CrossOrgTests(Base):
    def test_reports_exclude_other_org_evidence(self):
        other = _org("OrgC")
        oa, oc = _auditor(other, "a2@e.com"), _client_user(other, "c2@e.com")
        oeng = _eng(other, code="C-1")
        oreq = ev.create_evidence_request(
            engagement=oeng, actor=oa, title="FOREIGNEVIDENCE",
            gl_finding=_finding(oeng, code="GL-FOREIGN"), assigned_client_user=oc)
        ev.add_attachment(request=oreq, actor=oc, uploaded_file=_f())

        self.assertNotContains(
            self.client.get(reverse("frontend:assurance_index")), "GL-FOREIGN")
        self.assertNotContains(
            self.client.get(reverse("frontend:assurance_coverage")), "GL-FOREIGN")


class DashboardWidgetTests(Base):
    def test_dashboard_shows_assurance_widgets_and_link(self):
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        resp = self.client.get(reverse("frontend:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("frontend:assurance_overview"))
        self.assertContains(resp, "Integrity")
        self.assertContains(resp, "Coverage")
