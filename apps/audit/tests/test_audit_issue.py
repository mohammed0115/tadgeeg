"""TADGEEG-G3.2 — audit issue lifecycle tests (issue->remediation->closure)."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.issue_models import AuditIssue
from apps.audit.services import assessed_risk as ar
from apps.audit.services import audit_issue as ai
from apps.authentication.models import Organization, User

_St = AuditIssue.Status


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


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


class Base(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)


class ServiceTests(Base):
    def test_full_lifecycle(self):
        i = ai.create_issue(engagement=self.eng, actor=self.auditor,
                            title="Missing approvals", severity="high")
        self.assertEqual(i.reference, "ISSUE-00001")
        self.assertEqual(i.status, _St.OPEN)
        self.assertTrue(i.is_open)
        ai.record_remediation(issue=i, actor=self.auditor,
                              remediation_plan="Add approval gate", owner="CFO",
                              due_date=date.today() + timedelta(days=30))
        self.assertEqual(i.status, _St.IN_REMEDIATION)
        self.assertEqual(i.owner, "CFO")
        ai.set_status(issue=i, actor=self.auditor, status=_St.REMEDIATED, note="Done")
        self.assertFalse(i.is_open)
        self.assertIsNotNone(i.closed_at)
        self.assertEqual(i.management_response, "Done")

    def test_reopen_clears_closed_at(self):
        i = ai.create_issue(engagement=self.eng, actor=self.auditor, title="X")
        ai.set_status(issue=i, actor=self.auditor, status=_St.CLOSED)
        self.assertIsNotNone(i.closed_at)
        ai.set_status(issue=i, actor=self.auditor, status=_St.OPEN)
        self.assertIsNone(i.closed_at)

    def test_overdue(self):
        i = ai.create_issue(engagement=self.eng, actor=self.auditor, title="X",
                            due_date=timezone.localdate() - timedelta(days=1))
        self.assertTrue(i.is_overdue)
        ai.set_status(issue=i, actor=self.auditor, status=_St.CLOSED)
        self.assertFalse(i.is_overdue)  # closed issues are never overdue

    def test_link_to_risk(self):
        risk = ar.create_risk(engagement=self.eng, actor=self.auditor, title="R")
        i = ai.create_issue(engagement=self.eng, actor=self.auditor, title="X",
                            assessed_risk=risk)
        self.assertEqual(i.assessed_risk_id, risk.id)
        self.assertEqual(risk.issues.count(), 1)

    def test_title_required_and_invalid_status(self):
        with self.assertRaises(ai.AuditIssueError):
            ai.create_issue(engagement=self.eng, actor=self.auditor, title=" ")
        i = ai.create_issue(engagement=self.eng, actor=self.auditor, title="X")
        with self.assertRaises(ai.AuditIssueError):
            ai.set_status(issue=i, actor=self.auditor, status="nope")

    def test_summary(self):
        ai.create_issue(engagement=self.eng, actor=self.auditor, title="A",
                        severity="critical", due_date=date.today() - timedelta(days=2))
        b = ai.create_issue(engagement=self.eng, actor=self.auditor, title="B")
        ai.set_status(issue=b, actor=self.auditor, status=_St.CLOSED)
        s = ai.summary(organization=self.org, engagement=self.eng)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["open"], 1)
        self.assertEqual(s["overdue"], 1)
        self.assertEqual(s["critical"], 1)
        self.assertEqual(s["closed"], 1)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_create_list_detail_status(self):
        resp = self.api.post("/api/v1/audit/issues/", {
            "engagement": str(self.eng.id), "title": "Missing approvals",
            "severity": "high"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        iid = resp.json()["id"]
        self.assertTrue(self.api.get(
            f"/api/v1/audit/issues/?engagement={self.eng.id}").json())
        r = self.api.post(f"/api/v1/audit/issues/{iid}/",
                          {"status": "remediated", "note": "fixed"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["is_open"])

    def test_summary_endpoint(self):
        ai.create_issue(engagement=self.eng, actor=self.auditor, title="A",
                        severity="critical")
        s = self.api.get(f"/api/v1/audit/engagements/{self.eng.id}/issue-summary/")
        self.assertEqual(s.json()["critical"], 1)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get("/api/v1/audit/issues/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        foreign = ai.create_issue(engagement=other,
                                  actor=_auditor(other.organization, "o@e.com"), title="X")
        self.assertEqual(self.api.get(f"/api/v1/audit/issues/{foreign.id}/").status_code, 404)


class BridgeTests(Base):
    """G5 — promote a GL risk finding into the issue/remediation loop."""

    def _finding(self):
        import datetime
        from decimal import Decimal
        from apps.audit.general_ledger_models import (
            GeneralLedgerImport, GeneralLedgerRiskFinding)
        imp = GeneralLedgerImport.objects.create(
            engagement=self.eng, organization=self.org, source_format="csv",
            period_end=datetime.date(2025, 12, 31))
        return GeneralLedgerRiskFinding.objects.create(
            engagement=self.eng, organization=self.org, general_ledger_import=imp,
            risk_code="GL-DUP", risk_title="Duplicate posting",
            risk_category=GeneralLedgerRiskFinding.Category.OTHER,
            severity=GeneralLedgerRiskFinding.Severity.HIGH, score=80,
            amount_impact=Decimal("50000"), account_code="6000",
            risk_description="Possible duplicate journal.")

    def test_promote_is_idempotent_and_linked(self):
        risk = ar.create_risk(engagement=self.eng, actor=self.auditor, title="R")
        f = self._finding()
        issue = ai.promote_from_gl_finding(finding=f, actor=self.auditor, assessed_risk=risk)
        self.assertEqual(issue.gl_finding_id, f.id)
        self.assertEqual(issue.assessed_risk_id, risk.id)
        self.assertEqual(issue.severity, "high")
        # Idempotent — promoting again returns the same issue.
        again = ai.promote_from_gl_finding(finding=f, actor=self.auditor)
        self.assertEqual(again.id, issue.id)
        self.assertEqual(AuditIssue.objects.filter(gl_finding=f).count(), 1)

    def test_promote_via_api(self):
        f = self._finding()
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.post("/api/v1/audit/issues/", {
            "engagement": str(self.eng.id), "gl_finding": str(f.id)}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["gl_finding"], str(f.id))

    def _invoice(self):
        from apps.invoices.models import Invoice
        return Invoice.objects.create(
            organization=self.org, original_filename="inv-001.pdf",
            invoice_number="INV-001", vendor_name="Acme Supplies")

    def test_promote_from_invoice_idempotent_and_traceable(self):
        inv = self._invoice()
        issue = ai.promote_from_invoice(invoice=inv, engagement=self.eng, actor=self.auditor)
        self.assertEqual(issue.source_type, "invoice")
        self.assertEqual(issue.source_id, str(inv.id))
        self.assertIn("INV-001", issue.title)
        again = ai.promote_from_invoice(invoice=inv, engagement=self.eng, actor=self.auditor)
        self.assertEqual(again.id, issue.id)
        self.assertEqual(AuditIssue.objects.filter(
            source_type="invoice", source_id=str(inv.id)).count(), 1)

    def test_promote_invoice_via_api(self):
        inv = self._invoice()
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.post("/api/v1/audit/issues/", {
            "engagement": str(self.eng.id), "invoice": str(inv.id)}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["source_type"], "invoice")


class LedgerIsolationTests(Base):
    def test_no_ledger_writes(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        i = ai.create_issue(engagement=self.eng, actor=self.auditor, title="X")
        ai.set_status(issue=i, actor=self.auditor, status=_St.CLOSED)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
