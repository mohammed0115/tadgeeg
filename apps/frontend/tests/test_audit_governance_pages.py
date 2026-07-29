"""TADGEEG-G2.3/G3.2/G3.3/G6 — audit governance frontend page tests.

Covers the pages that surface the previously API-only engagement-governance
modules: findings register, issues, reports (+ sign-offs) and team.
"""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.engagement_models import AuditEngagement
from apps.audit.issue_models import AuditIssue
from apps.audit.member_models import EngagementMember
from apps.audit.report_models import EngagementReport
from apps.audit.services import audit_issue as ai
from apps.audit.services import report_builder as rb
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


class _Base:
    """Shared page assertions. A plain mixin (not a TestCase) so it is not
    collected directly; concrete classes below mix it with TestCase."""
    url_name = ""

    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)
        self.client.force_login(self.auditor)

    def _url(self, **q):
        base = reverse(self.url_name)
        if q:
            base += "?" + "&".join(f"{k}={v}" for k, v in q.items())
        return base

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse(self.url_name)).status_code, 302)

    def test_junior_denied(self):
        self.client.force_login(_junior(self.org))
        self.assertEqual(self.client.get(reverse(self.url_name)).status_code, 403)

    def test_no_engagement_state(self):
        self.assertEqual(self.client.get(reverse(self.url_name)).status_code, 200)


class FindingsRegisterTests(_Base, TestCase):
    url_name = "frontend:findings_register"

    def test_renders_for_engagement(self):
        resp = self.client.get(self._url(engagement=self.eng.id))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Findings Register")


class IssuesTests(_Base, TestCase):
    url_name = "frontend:issues"

    def test_create_issue(self):
        resp = self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "create_issue",
            "title": "Revenue cut-off", "severity": "high", "owner": "CFO"})
        self.assertEqual(resp.status_code, 200)
        obj = AuditIssue.objects.get(engagement=self.eng)
        self.assertEqual(obj.title, "Revenue cut-off")
        self.assertEqual(obj.severity, "high")
        self.assertContains(resp, obj.reference)

    def test_remediate_and_close(self):
        issue = ai.create_issue(engagement=self.eng, actor=self.auditor, title="X")
        # record remediation → moves OPEN to IN_REMEDIATION
        self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "remediate",
            "issue": str(issue.id), "remediation_plan": "Fix it", "owner": "Ops"})
        issue.refresh_from_db()
        self.assertEqual(issue.status, AuditIssue.Status.IN_REMEDIATION)
        self.assertEqual(issue.remediation_plan, "Fix it")
        # close it
        self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "set_status",
            "issue": str(issue.id), "status": "closed", "note": "Done"})
        issue.refresh_from_db()
        self.assertEqual(issue.status, AuditIssue.Status.CLOSED)
        self.assertIsNotNone(issue.closed_at)

    def test_scoping_other_org_issue_not_found(self):
        other = _org("Other"); other_eng = _eng(other, code="O-1")
        foreign = ai.create_issue(engagement=other_eng, actor=self.auditor, title="Y")
        resp = self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "set_status",
            "issue": str(foreign.id), "status": "closed"})
        self.assertContains(resp, "not found")
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, AuditIssue.Status.OPEN)


class ReportsTests(_Base, TestCase):
    url_name = "frontend:engagement_reports"

    def test_create_report(self):
        resp = self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "create_report", "title": "AR"})
        self.assertEqual(resp.status_code, 200)
        rep = EngagementReport.objects.get(engagement=self.eng)
        self.assertEqual(rep.version, 1)
        self.assertTrue(rep.not_an_opinion)
        self.assertContains(resp, rep.reference)

    def test_sign_off_and_sod(self):
        rep = rb.create_report(engagement=self.eng, actor=self.auditor)
        # auditor signs as preparer
        self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "sign",
            "report": str(rep.id), "role": "preparer"})
        # same actor cannot then sign as reviewer (ISA 220 SoD)
        resp = self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "sign",
            "report": str(rep.id), "role": "reviewer"})
        self.assertContains(resp, "segregation of duties")

    def test_finalize(self):
        rep = rb.create_report(engagement=self.eng, actor=self.auditor)
        self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "set_status",
            "report": str(rep.id), "status": "final"})
        rep.refresh_from_db()
        self.assertEqual(rep.status, EngagementReport.Status.FINAL)
        self.assertIsNotNone(rep.finalized_at)


class TeamTests(_Base, TestCase):
    url_name = "frontend:engagement_team"

    def test_assign_and_remove(self):
        member_user = _junior(self.org, email="member@e.com")
        resp = self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "assign",
            "user": str(member_user.pk), "role": "reviewer",
            "responsibilities": "Detail review"})
        self.assertEqual(resp.status_code, 200)
        m = EngagementMember.objects.get(engagement=self.eng, user=member_user)
        self.assertEqual(m.role, "reviewer")
        self.assertTrue(m.is_active)
        # remove → deactivate
        self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "remove", "member": str(m.id)})
        m.refresh_from_db()
        self.assertFalse(m.is_active)

    def test_cross_org_user_rejected(self):
        other = _org("Other"); foreign = _auditor(other, email="foreign@e.com")
        resp = self.client.post(self._url(), {
            "engagement": str(self.eng.id), "action": "assign",
            "user": str(foreign.pk), "role": "member"})
        self.assertContains(resp, "not found")
        self.assertFalse(EngagementMember.objects.filter(engagement=self.eng).exists())
