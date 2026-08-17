"""TADGEEG-G6 — engagement report builder tests (ISA 700-safe, versioned)."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.report_models import EngagementReport
from apps.audit.services import assessed_risk as ar
from apps.audit.services import audit_issue as ai
from apps.audit.services import report_builder as rb
from apps.audit.services import signoff
from apps.audit.signoff_models import EngagementSignoff
from apps.authentication.models import Organization, User

_St = EngagementReport.Status


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
    def test_build_assembles_from_spine_and_is_safe(self):
        ar.create_risk(engagement=self.eng, actor=self.auditor, title="R", is_significant=True)
        ai.create_issue(engagement=self.eng, actor=self.auditor, title="I")
        rep = rb.create_report(engagement=self.eng, actor=self.auditor)
        self.assertEqual(rep.reference, "REP-00001")
        self.assertEqual(rep.status, _St.DRAFT)
        self.assertTrue(rep.not_an_opinion)
        c = rep.content
        self.assertEqual(c["executive_summary"]["assessed_risks"], 1)
        self.assertEqual(c["executive_summary"]["significant_risks"], 1)
        self.assertEqual(c["executive_summary"]["open_issues"], 1)
        # ISA 700-safe: the assembled report must never assert an opinion.
        blob = json.dumps(c).lower()
        self.assertNotIn("in our opinion", blob)
        self.assertNotIn("present fairly", blob.replace(
            "does not state whether the financial statements present fairly", ""))
        self.assertIn("does not constitute an audit opinion", c["disclaimer"])

    def test_lifecycle_requires_independent_review_and_partner_signoffs(self):
        reviewer = _auditor(self.org, "reviewer@e.com")
        partner = _auditor(self.org, "partner@e.com")
        rep = rb.create_report(engagement=self.eng, actor=self.auditor)

        with self.assertRaises(rb.ReportBuilderError):
            rb.set_status(report=rep, actor=self.auditor, status=_St.FINAL)

        rb.set_status(report=rep, actor=self.auditor, status=_St.IN_REVIEW)
        with self.assertRaises(rb.ReportBuilderError):
            rb.set_status(report=rep, actor=self.auditor, status=_St.FINAL)

        signoff.sign(
            engagement=self.eng, actor=reviewer, artifact_type="engagement_report",
            artifact_id=rep.id, role=EngagementSignoff.Role.REVIEWER,
        )
        signoff.sign(
            engagement=self.eng, actor=partner, artifact_type="engagement_report",
            artifact_id=rep.id, role=EngagementSignoff.Role.PARTNER,
        )
        rb.set_status(report=rep, actor=self.auditor, status=_St.FINAL)
        self.assertIsNotNone(rep.finalized_at)

        with self.assertRaises(rb.ReportBuilderError):
            rb.set_status(report=rep, actor=self.auditor, status=_St.ARCHIVED)
        with self.assertRaises(rb.ReportBuilderError):
            rb.set_status(report=rep, actor=self.auditor, status="nope")

    def test_finalize_rejects_same_person_as_reviewer_and_partner(self):
        reviewer = _auditor(self.org, "reviewer@e.com")
        rep = rb.create_report(engagement=self.eng, actor=self.auditor)
        rb.set_status(report=rep, actor=self.auditor, status=_St.IN_REVIEW)
        for role in (EngagementSignoff.Role.REVIEWER, EngagementSignoff.Role.PARTNER):
            signoff.sign(
                engagement=self.eng, actor=reviewer, artifact_type="engagement_report",
                artifact_id=rep.id, role=role,
            )
        with self.assertRaises(rb.ReportBuilderError):
            rb.set_status(report=rep, actor=self.auditor, status=_St.FINAL)

    def test_build_content_fails_when_a_required_source_fails(self):
        with patch("apps.audit.services.findings_register.summary", side_effect=RuntimeError("db unavailable")):
            with self.assertRaises(rb.ReportBuilderError):
                rb.create_report(engagement=self.eng, actor=self.auditor)

    def test_new_version(self):
        rep = rb.create_report(engagement=self.eng, actor=self.auditor)
        v2 = rb.new_version(report=rep, actor=self.auditor)
        self.assertEqual(v2.version, 2)
        self.assertEqual(EngagementReport.objects.filter(engagement=self.eng).count(), 2)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_build_list_detail_status(self):
        resp = self.api.post(f"/api/v1/audit/engagements/{self.eng.id}/reports/", {}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        rid = resp.json()["id"]
        self.assertEqual(len(self.api.get(
            f"/api/v1/audit/engagements/{self.eng.id}/reports/").json()), 1)
        r = self.api.post(f"/api/v1/audit/reports/{rid}/", {"status": "in_review"}, format="json")
        self.assertEqual(r.status_code, 200)
        rep = EngagementReport.objects.get(pk=rid)
        reviewer = _auditor(self.org, "api-reviewer@e.com")
        partner = _auditor(self.org, "api-partner@e.com")
        signoff.sign(
            engagement=self.eng, actor=reviewer, artifact_type="engagement_report",
            artifact_id=rep.id, role=EngagementSignoff.Role.REVIEWER,
        )
        signoff.sign(
            engagement=self.eng, actor=partner, artifact_type="engagement_report",
            artifact_id=rep.id, role=EngagementSignoff.Role.PARTNER,
        )
        r = self.api.post(f"/api/v1/audit/reports/{rid}/", {"status": "final"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "final")

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get(
            f"/api/v1/audit/engagements/{self.eng.id}/reports/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        self.assertEqual(self.api.get(
            f"/api/v1/audit/engagements/{other.id}/reports/").status_code, 404)


class LedgerIsolationTests(Base):
    def test_no_ledger_writes(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        rb.create_report(engagement=self.eng, actor=self.auditor)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
