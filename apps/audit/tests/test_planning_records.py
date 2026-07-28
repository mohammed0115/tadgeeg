"""TADGEEG-FIN-AUDIT-9H — Engagement planning records (service + API)."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.planning_record_models import EngagementPlanningRecord
from apps.audit.services import planning_records as pr
from apps.authentication.models import Organization, User

_R = EngagementPlanningRecord


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
    def test_save_and_list_each_kind(self):
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="audit_plan",
                       payload={"strategy": {"scope": "x"}}, inputs={"industry": "retail"},
                       title="Acme — FY2026")
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="risk_responses",
                       payload={"mappings": []}, title="2 responses")
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="fraud_plan",
                       payload={"overall_severity": "high"}, title="Fraud plan")
        self.assertEqual(len(pr.list_records(engagement=self.eng)), 3)
        plans = pr.list_records(engagement=self.eng, kind="audit_plan")
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].payload["strategy"]["scope"], "x")
        self.assertEqual(plans[0].created_by_id, self.auditor.id)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(pr.PlanningRecordError):
            pr.save_record(engagement=self.eng, actor=self.auditor, kind="nope",
                           payload={})

    def test_counts(self):
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="audit_plan", payload={})
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="audit_plan", payload={})
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="fraud_plan", payload={})
        c = pr.counts(organization=self.org, engagement=self.eng)
        self.assertEqual(c["audit_plan"], 2)
        self.assertEqual(c["fraud_plan"], 1)
        self.assertEqual(c["total"], 3)

    def test_org_must_match_engagement(self):
        other_org = _org("OrgB")
        rec = EngagementPlanningRecord(engagement=self.eng, organization=other_org,
                                       kind="audit_plan", payload={})
        with self.assertRaises(ValidationError):
            rec.full_clean(exclude=["created_by"])

    def test_delete(self):
        rec = pr.save_record(engagement=self.eng, actor=self.auditor,
                             kind="audit_plan", payload={})
        pr.delete_record(record=rec, actor=self.auditor)
        self.assertEqual(len(pr.list_records(engagement=self.eng)), 0)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_list_and_filter(self):
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="audit_plan", payload={})
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="fraud_plan", payload={})
        base = f"/api/v1/audit/engagements/{self.eng.id}/planning-records/"
        self.assertEqual(len(self.api.get(base).json()), 2)
        self.assertEqual(len(self.api.get(base + "?kind=fraud_plan").json()), 1)

    def test_detail_and_delete(self):
        rec = pr.save_record(engagement=self.eng, actor=self.auditor,
                             kind="audit_plan", payload={"a": 1})
        url = f"/api/v1/audit/planning-records/{rec.id}/"
        self.assertEqual(self.api.get(url).status_code, 200)
        self.assertEqual(self.api.delete(url).status_code, 204)
        self.assertEqual(self.api.get(url).status_code, 404)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get(
            f"/api/v1/audit/engagements/{self.eng.id}/planning-records/").status_code, 403)

    def test_cross_org_404(self):
        other = _eng(_org("OrgB"), code="B-1")
        rec = pr.save_record(engagement=other, actor=_auditor(other.organization, "o@e.com"),
                             kind="audit_plan", payload={})
        self.assertEqual(self.api.get(
            f"/api/v1/audit/engagements/{other.id}/planning-records/").status_code, 404)
        self.assertEqual(self.api.get(
            f"/api/v1/audit/planning-records/{rec.id}/").status_code, 404)


class LedgerIsolationTests(Base):
    def test_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        pr.save_record(engagement=self.eng, actor=self.auditor, kind="audit_plan",
                       payload={"strategy": {}}, inputs={})
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
