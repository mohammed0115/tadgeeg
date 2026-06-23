"""TADGEEG-FIN-AUDIT-4A — Summary of Audit Differences (SAD) tests.

Covers accepted-only accumulation, exclusion of other statuses, conclusion
tiers vs materiality, by-category/by-account rollups, idempotency, that findings
are not modified, org scoping (service + API), cross-org denial, and no ledger
writes.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AuditDifferenceItem,
    AuditDifferenceSummary,
    AuditEngagement,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import audit_difference_summary as sad
from apps.authentication.models import Organization, User

_F = GeneralLedgerRiskFinding
_S = _F.Status
_C = AuditDifferenceSummary.Conclusion

# overall=100k, performance=75k, trivial=5k
PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "benchmark": "Revenue", "currency": "SAR"}


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _user(org, email="a@e.com"):
    return User.objects.create_user(email=email, password="StrongPass123!",
                                    full_name="T", role=User.Role.ADMIN, organization=org)


def _eng(org, code="AUD-1", materiality=None):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31",
        materiality=materiality if materiality is not None else PROFILE)


def _imp(eng):
    return GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")


def _finding(imp, amount, *, status=_S.ACCEPTED, account_code="6000",
             mapped_category="operating_expense", risk_code="GL-RISK-DESC"):
    eng = imp.engagement
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code=risk_code, risk_title="t", risk_category=_F.Category.OTHER,
        severity=_F.Severity.MEDIUM, score=50, amount_impact=Decimal(str(amount)),
        account_code=account_code, account_name="Acct", mapped_category=mapped_category,
        status=status)


class AcceptedOnlyTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def test_only_accepted_included(self):
        _finding(self.imp, 10000, status=_S.ACCEPTED)
        _finding(self.imp, 20000, status=_S.CANDIDATE)
        _finding(self.imp, 30000, status=_S.DISMISSED)
        _finding(self.imp, 40000, status=_S.NEEDS_EVIDENCE)
        _finding(self.imp, 50000, status=_S.ESCALATED)
        summary = sad.recalculate_for_engagement(self.eng)
        self.assertEqual(summary.total_accepted_findings, 1)
        self.assertEqual(summary.total_absolute_impact, Decimal("10000.0000"))
        self.assertEqual(summary.items.count(), 1)

    def test_no_accepted_findings(self):
        _finding(self.imp, 20000, status=_S.CANDIDATE)
        summary = sad.recalculate_for_engagement(self.eng)
        self.assertEqual(summary.total_accepted_findings, 0)
        self.assertEqual(summary.conclusion_status, _C.NO_ACCEPTED_DIFFERENCES)


class ConclusionTierTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def _concl(self, amount):
        _finding(self.imp, amount, status=_S.ACCEPTED)
        return sad.recalculate_for_engagement(self.eng).conclusion_status

    def test_below_trivial(self):
        self.assertEqual(self._concl(1000), _C.BELOW_TRIVIAL)

    def test_below_performance(self):
        self.assertEqual(self._concl(20000), _C.BELOW_PERFORMANCE)

    def test_above_performance(self):
        self.assertEqual(self._concl(80000), _C.ABOVE_PERFORMANCE)

    def test_above_overall(self):
        self.assertEqual(self._concl(150000), _C.ABOVE_OVERALL)

    def test_not_assessed_without_materiality(self):
        eng = _eng(_org("B"), code="NOPROF", materiality={})
        imp = _imp(eng)
        _finding(imp, 20000, status=_S.ACCEPTED)
        summary = sad.recalculate_for_engagement(eng)
        self.assertEqual(summary.conclusion_status, _C.NOT_ASSESSED)
        self.assertIsNone(summary.overall_materiality)


class RollupAndExceedTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def test_by_category_and_account(self):
        _finding(self.imp, 30000, account_code="6000", mapped_category="operating_expense")
        _finding(self.imp, 20000, account_code="4000", mapped_category="revenue")
        _finding(self.imp, 10000, account_code="6000", mapped_category="operating_expense")
        summary = sad.recalculate_for_engagement(self.eng)
        self.assertEqual(summary.summary_by_account["6000"], "40000.0000")
        self.assertEqual(summary.summary_by_account["4000"], "20000.0000")
        self.assertEqual(summary.summary_by_category["operating_expense"], "40000.0000")
        # 60,000 total: < performance (75k) → below_performance; exceeds flags off.
        self.assertEqual(summary.conclusion_status, _C.BELOW_PERFORMANCE)
        self.assertFalse(summary.exceeds_performance_materiality)
        self.assertFalse(summary.exceeds_overall_materiality)

    def test_exceeds_flags(self):
        _finding(self.imp, 150000, status=_S.ACCEPTED)
        summary = sad.recalculate_for_engagement(self.eng)
        self.assertTrue(summary.exceeds_performance_materiality)
        self.assertTrue(summary.exceeds_overall_materiality)


class IdempotencyAndImmutabilityTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def test_idempotent_no_duplicate_items(self):
        _finding(self.imp, 30000, status=_S.ACCEPTED)
        _finding(self.imp, 20000, status=_S.ACCEPTED)
        s1 = sad.recalculate_for_engagement(self.eng)
        n1 = s1.items.count()
        s2 = sad.recalculate_for_engagement(self.eng)
        self.assertEqual(s1.id, s2.id)  # single current summary
        self.assertEqual(s2.items.count(), n1)
        self.assertEqual(AuditDifferenceSummary.objects.filter(engagement=self.eng).count(), 1)

    def test_findings_not_modified(self):
        f = _finding(self.imp, 30000, status=_S.ACCEPTED)
        before = (f.status, f.score, f.severity, f.amount_impact)
        sad.recalculate_for_engagement(self.eng)
        f.refresh_from_db()
        self.assertEqual((f.status, f.score, f.severity, f.amount_impact), before)


class ModelTests(TestCase):
    def test_summary_clean_rejects_cross_tenant(self):
        eng = _eng(_org("A"))
        s = AuditDifferenceSummary(engagement=eng, organization=_org("B"))
        with self.assertRaises(ValidationError):
            s.clean()

    def test_item_creation(self):
        org = _org(); eng = _eng(org); imp = _imp(eng)
        _finding(imp, 30000, status=_S.ACCEPTED)
        summary = sad.recalculate_for_engagement(eng)
        item = summary.items.first()
        self.assertEqual(item.source_type, AuditDifferenceItem.SourceType.GL_RISK_FINDING)
        self.assertEqual(item.amount_impact, Decimal("30000.0000"))
        self.assertEqual(item.management_response_status,
                         AuditDifferenceItem.ManagementResponse.NOT_REQUESTED)


class ApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA"); self.user = _user(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)
        _finding(self.imp, 150000, status=_S.ACCEPTED)
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def test_recalculate_view_items_org_scoped(self):
        rc = self.client.post(f"/api/v1/audit/engagements/{self.eng.id}/sad/recalculate/",
                              {}, format="json")
        self.assertEqual(rc.status_code, 200, rc.content)
        sad_id = rc.json()["id"]
        self.assertEqual(rc.json()["conclusion_status"], "above_overall_materiality")

        got = self.client.get(f"/api/v1/audit/engagements/{self.eng.id}/sad/")
        self.assertEqual(got.status_code, 200)
        detail = self.client.get(f"/api/v1/audit/sad/{sad_id}/")
        self.assertEqual(detail.status_code, 200)
        items = self.client.get(f"/api/v1/audit/sad/{sad_id}/items/")
        self.assertEqual(items.status_code, 200)
        self.assertEqual(len(items.json()), 1)

    def test_recalculate_other_org_denied(self):
        other_eng = _eng(_org("OrgB"), code="OTHER-1")
        resp = self.client.post(
            f"/api/v1/audit/engagements/{other_eng.id}/sad/recalculate/", {}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(AuditDifferenceSummary.objects.filter(engagement=other_eng).count(), 0)

    def test_detail_other_org_denied(self):
        other_eng = _eng(_org("OrgC"), code="OTHER-2")
        other_summary = sad.recalculate_for_engagement(other_eng)
        resp = self.client.get(f"/api/v1/audit/sad/{other_summary.id}/")
        self.assertEqual(resp.status_code, 404)


class LedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        org = _org(); eng = _eng(org); imp = _imp(eng)
        _finding(imp, 150000, status=_S.ACCEPTED)
        sad.recalculate_for_engagement(eng)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
