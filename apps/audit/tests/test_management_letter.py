"""TADGEEG-FIN-AUDIT-9B — Management Letter tests (service + API)."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.control_deficiency_models import AuditControlDeficiency
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import management_letter as ml
from apps.authentication.models import Organization, User

_D = AuditControlDeficiency
_Cls = _D.Classification
_St = _D.Status


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

    def _make(self, classification=_Cls.OTHER_DEFICIENCY, title="Weak control"):
        return ml.create_deficiency(engagement=self.eng, actor=self.auditor,
                                    title=title, classification=classification,
                                    recommendation="Fix it")


class ServiceTests(Base):
    def test_create_and_numbering(self):
        a = self._make(); b = self._make()
        self.assertEqual(a.reference, "DEF-00001")
        self.assertEqual(b.reference, "DEF-00002")
        self.assertEqual(a.status, _St.OPEN)

    def test_management_response_moves_status(self):
        d = self._make()
        ml.record_management_response(deficiency=d, actor=self.auditor,
                                      response="We will fix by Q2", owner="CFO")
        self.assertEqual(d.status, _St.MANAGEMENT_RESPONDED)
        self.assertEqual(d.management_action_owner, "CFO")

    def test_empty_response_rejected(self):
        d = self._make()
        with self.assertRaises(ml.ManagementLetterError):
            ml.record_management_response(deficiency=d, actor=self.auditor, response="  ")

    def test_set_status(self):
        d = self._make()
        ml.set_status(deficiency=d, actor=self.auditor, status=_St.REMEDIATED)
        self.assertEqual(d.status, _St.REMEDIATED)
        with self.assertRaises(ml.ManagementLetterError):
            ml.set_status(deficiency=d, actor=self.auditor, status="nope")

    def test_build_letter_grouped_and_ordered(self):
        self._make(_Cls.OTHER_DEFICIENCY, "Minor")
        self._make(_Cls.MATERIAL_WEAKNESS, "Severe")
        self._make(_Cls.SIGNIFICANT_DEFICIENCY, "Notable")
        letter = ml.build_management_letter(engagement=self.eng)
        self.assertEqual(len(letter["groups"]["material_weakness"]), 1)
        self.assertEqual(len(letter["groups"]["significant_deficiency"]), 1)
        self.assertEqual(len(letter["groups"]["other_deficiency"]), 1)
        self.assertEqual(letter["counts"]["total"], 3)
        # Safe wording — communication, not an opinion.
        self.assertTrue(letter["not_an_opinion"])
        self.assertIn("does not modify the audit opinion", letter["disclaimer"])

    def test_status_counts(self):
        self._make(_Cls.MATERIAL_WEAKNESS)
        self._make(_Cls.OTHER_DEFICIENCY)
        counts = ml.status_counts(organization=self.org, engagement=self.eng)
        self.assertEqual(counts["material_weakness"], 1)
        self.assertEqual(counts["total"], 2)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_create_list_detail(self):
        resp = self.api.post("/api/v1/audit/control-deficiencies/", {
            "engagement": str(self.eng.id), "title": "Segregation of duties",
            "classification": "significant_deficiency", "area": "payroll"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        did = resp.json()["id"]
        self.assertTrue(self.api.get("/api/v1/audit/control-deficiencies/").json())
        self.assertEqual(self.api.get(f"/api/v1/audit/control-deficiencies/{did}/").status_code, 200)

    def test_record_response_via_api(self):
        d = self._make()
        resp = self.api.post(f"/api/v1/audit/control-deficiencies/{d.id}/",
                             {"management_response": "Fixed", "status": "remediated"},
                             format="json")
        self.assertEqual(resp.status_code, 200)
        d.refresh_from_db()
        self.assertEqual(d.status, _St.REMEDIATED)
        self.assertEqual(d.management_response, "Fixed")

    def test_letter_json_and_html(self):
        self._make(_Cls.MATERIAL_WEAKNESS, "Severe control gap")
        base = f"/api/v1/audit/engagements/{self.eng.id}/management-letter/"
        j = self.api.get(base)
        self.assertEqual(j.status_code, 200)
        self.assertTrue(j.json()["not_an_opinion"])
        h = self.api.get(base + "?format=html")
        self.assertEqual(h.status_code, 200)
        self.assertIn("text/html", h["Content-Type"])
        self.assertIn(b"Management Letter", h.content)
        self.assertIn(b"Severe control gap", h.content)
        self.assertNotIn(b"In our opinion", h.content)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get("/api/v1/audit/control-deficiencies/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        oa = _auditor(other.organization, "o@e.com")
        foreign = ml.create_deficiency(engagement=other, actor=oa, title="X")
        self.assertEqual(self.api.get(
            f"/api/v1/audit/control-deficiencies/{foreign.id}/").status_code, 404)
        self.assertEqual(self.api.get(
            f"/api/v1/audit/engagements/{other.id}/management-letter/").status_code, 404)


class LedgerIsolationTests(Base):
    def test_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        d = self._make(_Cls.MATERIAL_WEAKNESS)
        ml.record_management_response(deficiency=d, actor=self.auditor, response="ok")
        ml.build_management_letter(engagement=self.eng)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
