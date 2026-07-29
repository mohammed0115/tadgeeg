"""TADGEEG-G10 — end-to-end audit journey + cross-tenant security.

Walks the full traceability chain built across G2–G6 in one flow and asserts it
is linked and reportable end-to-end:

    Engagement → AssessedRisk → Procedure → Evidence
                      │            │
                      └── Finding ─┴── Issue → Sign-off → Report

Plus a cross-tenant isolation sweep over the new endpoints (defence in depth).
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import (
    GeneralLedgerImport, GeneralLedgerRiskFinding)
from apps.audit.services import assessed_risk as ar
from apps.audit.services import audit_issue as ai
from apps.audit.services import audit_procedure as ap
from apps.audit.services import report_builder as rb
from apps.audit.services import signoff as so
from apps.authentication.models import Organization, User


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _auditor(org, email):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


class AuditJourneyE2ETests(TestCase):
    def setUp(self):
        self.org = _org()
        self.preparer = _auditor(self.org, "prep@e.com")
        self.reviewer = _auditor(self.org, "rev@e.com")
        self.eng = _eng(self.org)

    def _gl_finding(self, risk=None):
        imp = GeneralLedgerImport.objects.create(
            engagement=self.eng, organization=self.org, source_format="csv",
            period_end=datetime.date(2025, 12, 31))
        return GeneralLedgerRiskFinding.objects.create(
            engagement=self.eng, organization=self.org, general_ledger_import=imp,
            risk_code="GL-CUTOFF", risk_title="Revenue cut-off",
            risk_category=GeneralLedgerRiskFinding.Category.OTHER,
            severity=GeneralLedgerRiskFinding.Severity.HIGH, score=80,
            amount_impact=Decimal("50000"), account_code="4000",
            risk_description="Revenue near period end.", assessed_risk=risk)

    def test_full_chain_is_linked_and_reportable(self):
        # 1) Assess a significant risk (ISA 315).
        risk = ar.create_risk(engagement=self.eng, actor=self.preparer,
                              title="Revenue cut-off", assertion="cutoff",
                              fs_area="revenue", inherent_risk="high",
                              control_risk="high", is_significant=True)
        self.assertEqual(risk.combined_risk, "significant")

        # 2) Design a responsive procedure (ISA 330) linked to the risk.
        proc = ap.create_procedure(engagement=self.eng, actor=self.preparer,
                                   title="Cut-off testing", assessed_risk=risk,
                                   nature="test_of_details", extent="increased")

        # 3) Request evidence for the procedure -> Risk→Procedure→Evidence.
        ereq = ap.request_evidence(procedure=proc, actor=self.preparer)
        self.assertEqual(ereq.procedure.assessed_risk_id, risk.id)  # walk back to risk

        # 4) A GL finding linked to the risk, promoted into an issue.
        finding = self._gl_finding(risk=risk)
        issue = ai.promote_from_gl_finding(finding=finding, actor=self.preparer,
                                           assessed_risk=risk)
        self.assertEqual(issue.assessed_risk_id, risk.id)
        self.assertEqual(issue.gl_finding_id, finding.id)

        # 5) Review governance — preparer then reviewer sign-off (ISA 220).
        so.sign(engagement=self.eng, actor=self.preparer,
                artifact_type="procedure", artifact_id=str(proc.id), role="preparer")
        so.sign(engagement=self.eng, actor=self.reviewer,
                artifact_type="procedure", artifact_id=str(proc.id), role="reviewer")
        status = so.status_for(engagement=self.eng, artifact_type="procedure",
                               artifact_id=str(proc.id))
        self.assertTrue(status["preparer"] and status["reviewer"])

        # 6) The report assembles the whole chain (ISA 700-safe).
        report = rb.create_report(engagement=self.eng, actor=self.reviewer)
        summ = report.content["executive_summary"]
        self.assertEqual(summ["assessed_risks"], 1)
        self.assertEqual(summ["significant_risks"], 1)
        self.assertEqual(summ["procedures"], 1)
        self.assertGreaterEqual(summ["findings"], 1)
        self.assertGreaterEqual(summ["open_issues"], 1)
        self.assertTrue(report.not_an_opinion)

        # 7) Findings register shows the finding linked to the risk.
        from apps.audit.services import findings_register as fr
        rows = fr.list_findings(organization=self.org, engagement=self.eng)
        linked = [r for r in rows if r["source"] == "gl_finding"
                  and r["assessed_risk_id"] == str(risk.id)]
        self.assertEqual(len(linked), 1)


class CrossTenantSecuritySweepTests(TestCase):
    """Defence in depth — the new endpoints must never leak across tenants."""

    def setUp(self):
        self.org_a = _org("A"); self.aud_a = _auditor(self.org_a, "a@e.com")
        self.org_b = _org("B"); self.aud_b = _auditor(self.org_b, "b@e.com")
        self.eng_b = _eng(self.org_b, code="B-1")
        self.api = APIClient(); self.api.force_authenticate(self.aud_a)

    def test_org_a_cannot_read_org_b_engagement_surfaces(self):
        eid = self.eng_b.id
        for url in (
            f"/api/v1/audit/engagements/{eid}/risk-summary/",
            f"/api/v1/audit/engagements/{eid}/procedure-summary/",
            f"/api/v1/audit/engagements/{eid}/issue-summary/",
            f"/api/v1/audit/engagements/{eid}/findings-register/",
            f"/api/v1/audit/engagements/{eid}/reports/",
            f"/api/v1/audit/engagements/{eid}/members/",
            f"/api/v1/audit/engagements/{eid}/signoffs/?artifact_type=x&artifact_id=y",
        ):
            self.assertEqual(self.api.get(url).status_code, 404, url)
