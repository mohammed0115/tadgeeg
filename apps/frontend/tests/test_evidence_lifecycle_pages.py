"""TADGEEG-FIN-AUDIT-6C — Evidence lifecycle frontend tests.

Every 6C backend capability must have a UI entry point; these tests assert the
Evidence Queue page (buckets, filters, search, bulk assignment), the version
history / download / archive / restore / freeze / verify controls on the
auditor detail page, the client download button, and the dashboard cards —
plus permission and cross-organization behaviour.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.audit.engagement_models import AuditEngagement
from apps.audit.evidence_models import AuditEvidenceAttachment, AuditEvidenceRequest
from apps.audit.general_ledger_models import (
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import evidence_lifecycle as lc
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_A = AuditEvidenceAttachment
_L = _A.Lifecycle
_R = AuditEvidenceRequest
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


def _finding(eng):
    imp = GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="t",
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
                                     uploaded_file=_f(content=b"payload"))


class QueuePageTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.auditor)

    def test_queue_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("frontend:evidence_queue"))
        self.assertEqual(resp.status_code, 302)

    def test_queue_renders_with_buckets_and_cards(self):
        resp = self.client.get(reverse("frontend:evidence_queue"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.req.request_number)
        self.assertContains(resp, "bucket=overdue")          # bucket tabs
        self.assertContains(resp, 'name="request_ids"')       # bulk selection
        self.assertContains(resp, 'value="bulk_assign"')      # bulk action

    def test_queue_client_denied(self):
        self.client.force_login(self.client_user)
        resp = self.client.get(reverse("frontend:evidence_queue"))
        self.assertEqual(resp.status_code, 403)

    def test_queue_bucket_filter(self):
        resp = self.client.get(reverse("frontend:evidence_queue"), {"bucket": "overdue"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, self.req.request_number)  # not overdue

    def test_queue_search(self):
        resp = self.client.get(reverse("frontend:evidence_queue"), {"q": "Provide invoice"})
        self.assertContains(resp, self.req.request_number)
        resp2 = self.client.get(reverse("frontend:evidence_queue"), {"q": "NOMATCHXYZ"})
        self.assertNotContains(resp2, self.req.request_number)

    def test_queue_excludes_other_org(self):
        other = _org("OrgB")
        oa = _auditor(other, "a2@e.com")
        oeng = _eng(other, code="B-1")
        ev.create_evidence_request(engagement=oeng, actor=oa, title="FOREIGNREQ",
                                   gl_finding=_finding(oeng))
        resp = self.client.get(reverse("frontend:evidence_queue"))
        self.assertNotContains(resp, "FOREIGNREQ")

    def test_bulk_assign_from_ui(self):
        reviewer = _auditor(self.org, "rev@e.com")
        resp = self.client.post(reverse("frontend:evidence_queue"), {
            "action": "bulk_assign", "reviewer": str(reviewer.id),
            "request_ids": [str(self.req.id)]})
        self.assertEqual(resp.status_code, 200)
        self.req.refresh_from_db()
        self.assertEqual(self.req.assigned_to_id, reviewer.id)

    def test_bulk_assign_requires_selection(self):
        reviewer = _auditor(self.org, "rev2@e.com")
        resp = self.client.post(reverse("frontend:evidence_queue"), {
            "action": "bulk_assign", "reviewer": str(reviewer.id)})
        self.assertContains(resp, "Select at least one")


class AuditorDetailLifecycleTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.auditor)

    def _url(self):
        return reverse("frontend:evidence_detail", args=[self.req.id])

    def test_detail_shows_version_history_and_controls(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"/api/v1/audit/evidence-attachments/{self.att.id}/download/")
        self.assertContains(resp, 'value="verify"')
        self.assertContains(resp, 'value="archive"')
        self.assertContains(resp, 'value="freeze"')
        self.assertContains(resp, 'class="ig unverified"')   # integrity badge
        self.assertContains(resp, 'class="lc active"')       # lifecycle badge

    def test_archive_then_restore_from_ui(self):
        resp = self.client.post(self._url(), {
            "action": "archive", "attachment_id": str(self.att.id)})
        self.assertEqual(resp.status_code, 200)
        self.att.refresh_from_db()
        self.assertEqual(self.att.lifecycle_state, _L.ARCHIVED)
        self.assertContains(resp, 'value="restore"')

        self.client.post(self._url(), {
            "action": "restore", "attachment_id": str(self.att.id)})
        self.att.refresh_from_db()
        self.assertEqual(self.att.lifecycle_state, _L.ACTIVE)

    def test_freeze_from_ui_then_blocked(self):
        self.client.post(self._url(), {
            "action": "freeze", "attachment_id": str(self.att.id)})
        self.att.refresh_from_db()
        self.assertEqual(self.att.lifecycle_state, _L.FROZEN)
        resp = self.client.post(self._url(), {
            "action": "archive", "attachment_id": str(self.att.id)})
        self.assertContains(resp, "frozen")

    def test_verify_from_ui_shows_result(self):
        resp = self.client.post(self._url(), {
            "action": "verify", "attachment_id": str(self.att.id)})
        self.assertContains(resp, "Integrity verified")
        self.att.refresh_from_db()
        self.assertTrue(self.att.last_verification_ok)

    def test_verify_failure_surfaced_in_ui(self):
        with open(self.att.uploaded_file.path, "wb") as fh:
            fh.write(b"TAMPERED")
        resp = self.client.post(self._url(), {
            "action": "verify", "attachment_id": str(self.att.id)})
        self.assertContains(resp, "INTEGRITY FAILED")

    def test_cannot_act_on_other_org_attachment(self):
        other = _org("OrgC")
        oa = _auditor(other, "a3@e.com")
        oeng = _eng(other, code="C-1")
        oreq = ev.create_evidence_request(engagement=oeng, actor=oa, title="x",
                                          gl_finding=_finding(oeng))
        oatt = ev.add_attachment(request=oreq, actor=oa, uploaded_file=_f())
        resp = self.client.post(self._url(), {
            "action": "archive", "attachment_id": str(oatt.id)})
        self.assertContains(resp, "Attachment not found")
        oatt.refresh_from_db()
        self.assertEqual(oatt.lifecycle_state, _L.ACTIVE)

    def test_client_cannot_perform_lifecycle_actions(self):
        self.client.force_login(self.client_user)
        resp = self.client.post(self._url(), {
            "action": "archive", "attachment_id": str(self.att.id)})
        self.assertEqual(resp.status_code, 403)
        self.att.refresh_from_db()
        self.assertEqual(self.att.lifecycle_state, _L.ACTIVE)


class ClientPortalDownloadTests(Base):
    def test_client_sees_download_button_and_badge(self):
        self.client.force_login(self.client_user)
        resp = self.client.get(
            reverse("frontend:client_evidence_detail", args=[self.req.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"/api/v1/audit/evidence-attachments/{self.att.id}/download/")


class DashboardCardTests(Base):
    def test_dashboard_shows_lifecycle_cards_and_queue_link(self):
        self.client.force_login(self.auditor)
        resp = self.client.get(reverse("frontend:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("frontend:evidence_queue"))
        self.assertContains(resp, "Avg review time")
