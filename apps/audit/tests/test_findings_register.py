"""TADGEEG-G2.3 — unified findings register + finding->risk link tests."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.control_deficiency_models import AuditControlDeficiency
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import assessed_risk as ar
from apps.audit.services import findings_register as fr
from apps.audit.services import management_letter as ml
from apps.authentication.models import Organization, User


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


class RegisterTests(Base):
    def test_aggregates_deficiencies_and_links_to_risk(self):
        risk = ar.create_risk(engagement=self.eng, actor=self.auditor, title="Revenue")
        d1 = ml.create_deficiency(engagement=self.eng, actor=self.auditor,
                                  title="Weak control", classification="material_weakness")
        d1.assessed_risk = risk
        d1.save(update_fields=["assessed_risk"])
        ml.create_deficiency(engagement=self.eng, actor=self.auditor,
                             title="Minor", classification="other_deficiency")
        rows = fr.list_findings(organization=self.org, engagement=self.eng)
        self.assertEqual(len(rows), 2)
        # Material weakness ranks above other deficiency.
        self.assertEqual(rows[0]["severity"], "material_weakness")
        self.assertEqual(rows[0]["assessed_risk_id"], str(risk.id))
        s = fr.summary(organization=self.org, engagement=self.eng)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["control_deficiencies"], 2)
        self.assertEqual(s["linked_to_risk"], 1)
        self.assertEqual(s["unlinked"], 1)

    def test_source_filter(self):
        ml.create_deficiency(engagement=self.eng, actor=self.auditor, title="X")
        gl = fr.list_findings(organization=self.org, engagement=self.eng,
                              source="gl_finding")
        self.assertEqual(gl, [])
        de = fr.list_findings(organization=self.org, engagement=self.eng,
                              source="control_deficiency")
        self.assertEqual(len(de), 1)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_register_endpoint(self):
        ml.create_deficiency(engagement=self.eng, actor=self.auditor, title="X",
                             classification="significant_deficiency")
        resp = self.api.get(f"/api/v1/audit/engagements/{self.eng.id}/findings-register/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["summary"]["total"], 1)
        self.assertEqual(len(body["findings"]), 1)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get(
            f"/api/v1/audit/engagements/{self.eng.id}/findings-register/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        self.assertEqual(self.api.get(
            f"/api/v1/audit/engagements/{other.id}/findings-register/").status_code, 404)
