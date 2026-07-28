"""TADGEEG-G3 — engagement sign-off tests (ISA 220 segregation)."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import signoff as so
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
        self.org = _org()
        self.preparer = _auditor(self.org, "prep@e.com")
        self.reviewer = _auditor(self.org, "rev@e.com")
        self.eng = _eng(self.org)


class ServiceTests(Base):
    def test_preparer_then_reviewer_ok(self):
        so.sign(engagement=self.eng, actor=self.preparer,
                artifact_type="procedure", artifact_id="p-1", role="preparer")
        so.sign(engagement=self.eng, actor=self.reviewer,
                artifact_type="procedure", artifact_id="p-1", role="reviewer")
        st = so.status_for(engagement=self.eng, artifact_type="procedure", artifact_id="p-1")
        self.assertTrue(st["preparer"])
        self.assertTrue(st["reviewer"])
        self.assertFalse(st["partner"])

    def test_preparer_cannot_review_own_work(self):
        so.sign(engagement=self.eng, actor=self.preparer,
                artifact_type="procedure", artifact_id="p-1", role="preparer")
        with self.assertRaises(so.SignoffError):
            so.sign(engagement=self.eng, actor=self.preparer,
                    artifact_type="procedure", artifact_id="p-1", role="reviewer")

    def test_invalid_role(self):
        with self.assertRaises(so.SignoffError):
            so.sign(engagement=self.eng, actor=self.reviewer,
                    artifact_type="procedure", artifact_id="p-1", role="nope")

    def test_is_signed_off(self):
        self.assertFalse(so.is_signed_off(engagement=self.eng,
                                          artifact_type="risk", artifact_id="r-1", role="partner"))
        so.sign(engagement=self.eng, actor=self.reviewer,
                artifact_type="risk", artifact_id="r-1", role="partner")
        self.assertTrue(so.is_signed_off(engagement=self.eng,
                                         artifact_type="risk", artifact_id="r-1", role="partner"))


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.reviewer)

    def _url(self, eng=None):
        return f"/api/v1/audit/engagements/{(eng or self.eng).id}/signoffs/"

    def test_post_and_get(self):
        resp = self.api.post(self._url(), {
            "artifact_type": "procedure", "artifact_id": "p-9", "role": "reviewer"},
            format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        got = self.api.get(self._url() + "?artifact_type=procedure&artifact_id=p-9")
        self.assertEqual(got.status_code, 200)
        self.assertTrue(got.json()["status"]["reviewer"])

    def test_segregation_enforced_via_api(self):
        so.sign(engagement=self.eng, actor=self.reviewer,
                artifact_type="wp", artifact_id="w-1", role="preparer")
        resp = self.api.post(self._url(), {
            "artifact_type": "wp", "artifact_id": "w-1", "role": "reviewer"},
            format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("segregation", resp.json()["error"])

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get(self._url()).status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        self.assertEqual(self.api.get(self._url(other)).status_code, 404)


class LedgerIsolationTests(Base):
    def test_no_ledger_writes(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        so.sign(engagement=self.eng, actor=self.preparer,
                artifact_type="procedure", artifact_id="p-1", role="preparer")
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
