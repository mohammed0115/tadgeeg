"""TADGEEG-G2 — Assessed Risk register tests (service + API). ISA 315 anchor."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.assessed_risk_models import AssessedRisk
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import assessed_risk as ar
from apps.authentication.models import Organization, User

_R = AssessedRisk
_St = _R.Status


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
    def test_create_numbering_scoping(self):
        a = ar.create_risk(engagement=self.eng, actor=self.auditor,
                           title="Revenue cut-off", assertion="cutoff", fs_area="revenue")
        b = ar.create_risk(engagement=self.eng, actor=self.auditor, title="Payables completeness")
        self.assertEqual(a.reference, "RISK-00001")
        self.assertEqual(b.reference, "RISK-00002")
        self.assertEqual(a.organization_id, self.org.id)
        self.assertEqual(a.status, _St.IDENTIFIED)
        self.assertEqual(a.fs_area, "revenue")

    def test_title_required(self):
        with self.assertRaises(ar.AssessedRiskError):
            ar.create_risk(engagement=self.eng, actor=self.auditor, title="  ")

    def test_combined_risk_and_significant(self):
        high = ar.create_risk(engagement=self.eng, actor=self.auditor, title="H",
                              inherent_risk="high", control_risk="low")
        self.assertEqual(high.combined_risk, "high")
        fraud = ar.create_risk(engagement=self.eng, actor=self.auditor, title="F",
                               inherent_risk="low", control_risk="low", is_fraud_risk=True)
        self.assertEqual(fraud.combined_risk, "significant")

    def test_status_transitions(self):
        r = ar.create_risk(engagement=self.eng, actor=self.auditor, title="X")
        ar.set_status(risk=r, actor=self.auditor, status=_St.RESPONDED)
        self.assertEqual(r.status, _St.RESPONDED)
        with self.assertRaises(ar.AssessedRiskError):
            ar.set_status(risk=r, actor=self.auditor, status="nope")

    def test_summary(self):
        ar.create_risk(engagement=self.eng, actor=self.auditor, title="A", is_significant=True)
        ar.create_risk(engagement=self.eng, actor=self.auditor, title="B", is_fraud_risk=True)
        s = ar.summary(organization=self.org, engagement=self.eng)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["significant"], 1)
        self.assertEqual(s["fraud"], 1)
        self.assertEqual(s["identified"], 2)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_create_list_detail(self):
        resp = self.api.post("/api/v1/audit/assessed-risks/", {
            "engagement": str(self.eng.id), "title": "Revenue occurrence",
            "assertion": "existence", "fs_area": "revenue",
            "inherent_risk": "high", "control_risk": "high", "is_significant": True},
            format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["combined_risk"], "significant")
        rid = body["id"]
        self.assertTrue(self.api.get(
            f"/api/v1/audit/assessed-risks/?engagement={self.eng.id}").json())
        self.assertEqual(self.api.get(f"/api/v1/audit/assessed-risks/{rid}/").status_code, 200)

    def test_status_via_api(self):
        r = ar.create_risk(engagement=self.eng, actor=self.auditor, title="X")
        resp = self.api.post(f"/api/v1/audit/assessed-risks/{r.id}/",
                             {"status": "responded"}, format="json")
        self.assertEqual(resp.status_code, 200)
        r.refresh_from_db()
        self.assertEqual(r.status, _St.RESPONDED)

    def test_summary_endpoint(self):
        ar.create_risk(engagement=self.eng, actor=self.auditor, title="A", is_significant=True)
        resp = self.api.get(f"/api/v1/audit/engagements/{self.eng.id}/risk-summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["significant"], 1)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get("/api/v1/audit/assessed-risks/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        foreign = ar.create_risk(engagement=other,
                                 actor=_auditor(other.organization, "o@e.com"), title="X")
        self.assertEqual(self.api.get(
            f"/api/v1/audit/assessed-risks/{foreign.id}/").status_code, 404)
        self.assertEqual(self.api.get(
            f"/api/v1/audit/engagements/{other.id}/risk-summary/").status_code, 404)


class LedgerIsolationTests(Base):
    def test_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        r = ar.create_risk(engagement=self.eng, actor=self.auditor, title="X",
                           is_significant=True)
        ar.set_status(risk=r, actor=self.auditor, status=_St.RESPONDED)
        ar.summary(organization=self.org, engagement=self.eng)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
