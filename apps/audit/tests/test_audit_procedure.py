"""TADGEEG-G2.2 — Audit procedure tests (service + API). Risk->Procedure link."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.procedure_models import AuditProcedure
from apps.audit.services import assessed_risk as ar
from apps.audit.services import audit_procedure as ap
from apps.authentication.models import Organization, User

_P = AuditProcedure
_St = _P.Status


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

    def _risk(self, title="Revenue cut-off"):
        return ar.create_risk(engagement=self.eng, actor=self.auditor, title=title)


class ServiceTests(Base):
    def test_create_and_link_to_risk(self):
        risk = self._risk()
        p = ap.create_procedure(engagement=self.eng, actor=self.auditor,
                                title="Cut-off testing", assessed_risk=risk,
                                nature="test_of_details", extent="increased")
        self.assertEqual(p.reference, "PROC-00001")
        self.assertEqual(p.assessed_risk_id, risk.id)
        self.assertEqual(p.status, _St.PLANNED)
        # Reverse traversal along the spine: risk -> procedures.
        self.assertEqual(risk.procedures.count(), 1)

    def test_title_required(self):
        with self.assertRaises(ap.AuditProcedureError):
            ap.create_procedure(engagement=self.eng, actor=self.auditor, title=" ")

    def test_cross_engagement_risk_rejected(self):
        other = _eng(_org("OrgB"), code="B-1")
        foreign_risk = ar.create_risk(engagement=other,
                                      actor=_auditor(other.organization, "o@e.com"), title="X")
        with self.assertRaises(Exception):
            ap.create_procedure(engagement=self.eng, actor=self.auditor,
                                title="P", assessed_risk=foreign_risk)

    def test_status_and_performed_by(self):
        p = ap.create_procedure(engagement=self.eng, actor=self.auditor, title="P")
        ap.set_status(procedure=p, actor=self.auditor, status=_St.COMPLETED,
                      conclusion="No exceptions")
        self.assertEqual(p.status, _St.COMPLETED)
        self.assertEqual(p.performed_by_id, self.auditor.id)
        self.assertEqual(p.conclusion, "No exceptions")
        with self.assertRaises(ap.AuditProcedureError):
            ap.set_status(procedure=p, actor=self.auditor, status="nope")

    def test_link_and_relink(self):
        p = ap.create_procedure(engagement=self.eng, actor=self.auditor, title="P")
        self.assertIsNone(p.assessed_risk_id)
        r = self._risk()
        ap.link_risk(procedure=p, assessed_risk=r, actor=self.auditor)
        self.assertEqual(p.assessed_risk_id, r.id)
        ap.link_risk(procedure=p, assessed_risk=None, actor=self.auditor)
        self.assertIsNone(p.assessed_risk_id)

    def test_summary(self):
        r = self._risk()
        ap.create_procedure(engagement=self.eng, actor=self.auditor, title="A", assessed_risk=r)
        ap.create_procedure(engagement=self.eng, actor=self.auditor, title="B")
        s = ap.summary(organization=self.org, engagement=self.eng)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["linked"], 1)
        self.assertEqual(s["planned"], 2)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_create_list_detail_with_risk(self):
        risk = self._risk()
        resp = self.api.post("/api/v1/audit/procedures/", {
            "engagement": str(self.eng.id), "title": "Cut-off testing",
            "assessed_risk": str(risk.id), "nature": "test_of_details",
            "extent": "increased"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["risk_reference"], risk.reference)
        pid = body["id"]
        self.assertTrue(self.api.get(
            f"/api/v1/audit/procedures/?assessed_risk={risk.id}").json())
        self.assertEqual(self.api.get(f"/api/v1/audit/procedures/{pid}/").status_code, 200)

    def test_status_and_summary(self):
        p = ap.create_procedure(engagement=self.eng, actor=self.auditor, title="P")
        self.assertEqual(self.api.post(f"/api/v1/audit/procedures/{p.id}/",
                                       {"status": "completed"}, format="json").status_code, 200)
        s = self.api.get(f"/api/v1/audit/engagements/{self.eng.id}/procedure-summary/")
        self.assertEqual(s.json()["completed"], 1)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get("/api/v1/audit/procedures/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        foreign = ap.create_procedure(engagement=other,
                                      actor=_auditor(other.organization, "o@e.com"), title="P")
        self.assertEqual(self.api.get(
            f"/api/v1/audit/procedures/{foreign.id}/").status_code, 404)


class EvidenceLinkTests(Base):
    def test_request_evidence_closes_chain(self):
        # Risk -> Procedure -> Evidence, all linked and walkable.
        risk = self._risk()
        p = ap.create_procedure(engagement=self.eng, actor=self.auditor,
                                title="Cut-off testing", assessed_risk=risk)
        ereq = ap.request_evidence(procedure=p, actor=self.auditor)
        self.assertEqual(ereq.procedure_id, p.id)
        self.assertEqual(ereq.engagement_id, self.eng.id)
        # Walk the chain backwards: evidence -> procedure -> risk.
        self.assertEqual(ereq.procedure.assessed_risk_id, risk.id)
        self.assertEqual(p.evidence_requests.count(), 1)

    def test_cross_org_procedure_target_rejected(self):
        from django.core.exceptions import ValidationError
        from apps.audit.evidence_models import AuditEvidenceRequest
        other = _eng(_org("OrgB"), code="B-1")
        foreign = ap.create_procedure(engagement=other,
                                      actor=_auditor(other.organization, "o@e.com"), title="P")
        req = AuditEvidenceRequest(engagement=self.eng, organization=self.org,
                                   procedure=foreign, title="X")
        with self.assertRaises(ValidationError):
            req.full_clean(exclude=["requested_by", "assigned_to",
                                    "assigned_client_user", "request_number"])


class LedgerIsolationTests(Base):
    def test_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        r = self._risk()
        p = ap.create_procedure(engagement=self.eng, actor=self.auditor, title="P",
                                assessed_risk=r)
        ap.set_status(procedure=p, actor=self.auditor, status=_St.COMPLETED)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
