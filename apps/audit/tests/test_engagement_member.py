"""TADGEEG-G3.3 — engagement team member tests."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.member_models import EngagementMember
from apps.audit.services import engagement_member as em
from apps.authentication.models import Organization, User


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _auditor(org, email):
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
        self.lead = _auditor(self.org, "lead@e.com")
        self.member = _auditor(self.org, "member@e.com")
        self.eng = _eng(self.org)


class ServiceTests(Base):
    def test_assign_and_reactivate(self):
        m = em.assign(engagement=self.eng, actor=self.lead, user=self.member,
                      role="reviewer", responsibilities="Review GL")
        self.assertEqual(m.role, "reviewer")
        self.assertTrue(m.is_active)
        em.remove(member=m, actor=self.lead)
        self.assertFalse(m.is_active)
        # Re-assigning the same (user, role) reactivates the same row.
        m2 = em.assign(engagement=self.eng, actor=self.lead, user=self.member, role="reviewer")
        self.assertEqual(m2.id, m.id)
        self.assertTrue(m2.is_active)

    def test_cross_org_member_rejected(self):
        other_user = _auditor(_org("OrgB"), "x@e.com")
        with self.assertRaises(em.EngagementMemberError):
            em.assign(engagement=self.eng, actor=self.lead, user=other_user, role="member")

    def test_invalid_role(self):
        with self.assertRaises(em.EngagementMemberError):
            em.assign(engagement=self.eng, actor=self.lead, user=self.member, role="nope")

    def test_summary(self):
        em.assign(engagement=self.eng, actor=self.lead, user=self.lead, role="partner")
        em.assign(engagement=self.eng, actor=self.lead, user=self.member, role="reviewer")
        s = em.summary(organization=self.org, engagement=self.eng)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["role_partner"], 1)
        self.assertEqual(s["role_reviewer"], 1)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.lead)

    def test_assign_list_remove(self):
        resp = self.api.post(f"/api/v1/audit/engagements/{self.eng.id}/members/", {
            "user": str(self.member.id), "role": "reviewer"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        mid = resp.json()["id"]
        self.assertEqual(len(self.api.get(
            f"/api/v1/audit/engagements/{self.eng.id}/members/").json()), 1)
        self.assertEqual(self.api.delete(f"/api/v1/audit/members/{mid}/").status_code, 204)
        # Deactivated -> no longer in the active list.
        self.assertEqual(len(self.api.get(
            f"/api/v1/audit/engagements/{self.eng.id}/members/").json()), 0)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get(
            f"/api/v1/audit/engagements/{self.eng.id}/members/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        self.assertEqual(self.api.get(
            f"/api/v1/audit/engagements/{other.id}/members/").status_code, 404)
