"""TADGEEG-FIN-AUDIT-3A — Materiality classification of GL candidate findings.

Covers the classification tiers, ratio calculation, adjusted-vs-original score
separation, trivial caps + exceptions, idempotency, candidate-status
preservation, benchmark compute path, org scoping (service + API), and no
ledger writes.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AuditEngagement,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import gl_finding_materiality as gm
from apps.authentication.models import Organization, User

_F = GeneralLedgerRiskFinding
_MS = _F.MaterialityStatus
_Sev = _F.Severity

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
        materiality=materiality or {})


def _imp(eng):
    return GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")


def _finding(imp, amount, *, score=50, severity=_Sev.MEDIUM,
             risk_code="GL-RISK-DESC", status=_F.Status.CANDIDATE):
    eng = imp.engagement
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code=risk_code, risk_title="t", risk_category=_F.Category.OTHER,
        severity=severity, score=score, amount_impact=Decimal(str(amount)),
        status=status)


class ClassificationTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def _apply(self, **kw):
        return gm.apply_materiality_to_import(self.imp, materiality=PROFILE, **kw)

    def test_trivial(self):
        f = _finding(self.imp, 1000)
        self._apply()
        f.refresh_from_db()
        self.assertEqual(f.materiality_status, _MS.TRIVIAL)

    def test_below_performance(self):
        f = _finding(self.imp, 20000)
        self._apply(); f.refresh_from_db()
        self.assertEqual(f.materiality_status, _MS.BELOW_PERFORMANCE)

    def test_above_performance(self):
        f = _finding(self.imp, 80000)
        self._apply(); f.refresh_from_db()
        self.assertEqual(f.materiality_status, _MS.ABOVE_PERFORMANCE)

    def test_above_overall(self):
        f = _finding(self.imp, 150000)
        self._apply(); f.refresh_from_db()
        self.assertEqual(f.materiality_status, _MS.ABOVE_OVERALL)

    def test_unknown_amount(self):
        f = _finding(self.imp, 0)
        self._apply(); f.refresh_from_db()
        self.assertEqual(f.materiality_status, _MS.UNKNOWN_AMOUNT)

    def test_not_assessed_without_profile(self):
        f = _finding(self.imp, 20000)
        gm.apply_materiality_to_import(self.imp)  # no profile anywhere
        f.refresh_from_db()
        self.assertEqual(f.materiality_status, _MS.NOT_ASSESSED)
        self.assertIsNone(f.materiality_overall)

    def test_reads_profile_from_engagement(self):
        self.eng.materiality = PROFILE
        self.eng.save(update_fields=["materiality"])
        f = _finding(self.imp, 150000)
        gm.apply_materiality_to_import(self.imp)  # reads engagement.materiality
        f.refresh_from_db()
        self.assertEqual(f.materiality_status, _MS.ABOVE_OVERALL)


class RatioAndAdjustmentTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def test_ratios(self):
        f = _finding(self.imp, 150000)
        gm.apply_materiality_to_import(self.imp, materiality=PROFILE)
        f.refresh_from_db()
        self.assertEqual(f.amount_to_overall_materiality_ratio, Decimal("1.5000"))
        self.assertEqual(f.amount_to_performance_materiality_ratio, Decimal("2.0000"))

    def test_adjusted_separate_from_original(self):
        f = _finding(self.imp, 150000, score=50, severity=_Sev.MEDIUM)
        gm.apply_materiality_to_import(self.imp, materiality=PROFILE)
        f.refresh_from_db()
        # Original preserved.
        self.assertEqual(f.score, 50)
        self.assertEqual(f.severity, _Sev.MEDIUM)
        # Above overall → +25 → 75 → high.
        self.assertEqual(f.materiality_adjusted_score, 75)
        self.assertEqual(f.materiality_adjusted_severity, _Sev.HIGH)

    def test_trivial_caps_high_to_medium(self):
        f = _finding(self.imp, 1000, score=75, severity=_Sev.HIGH)
        gm.apply_materiality_to_import(self.imp, materiality=PROFILE)
        f.refresh_from_db()
        self.assertEqual(f.materiality_adjusted_score, 60)
        self.assertEqual(f.materiality_adjusted_severity, _Sev.MEDIUM)
        self.assertEqual(f.severity, _Sev.HIGH)  # original untouched

    def test_trivial_keeps_critical(self):
        f = _finding(self.imp, 1000, score=90, severity=_Sev.CRITICAL)
        gm.apply_materiality_to_import(self.imp, materiality=PROFILE)
        f.refresh_from_db()
        self.assertEqual(f.materiality_adjusted_severity, _Sev.CRITICAL)

    def test_trivial_sensitive_keeps_high(self):
        f = _finding(self.imp, 1000, score=75, severity=_Sev.HIGH,
                     risk_code="GL-RISK-SENSITIVE")
        gm.apply_materiality_to_import(self.imp, materiality=PROFILE)
        f.refresh_from_db()
        self.assertEqual(f.materiality_adjusted_severity, _Sev.HIGH)


class BenchmarkComputeTests(TestCase):
    def test_compute_persists_profile_and_classifies(self):
        org = _org(); eng = _eng(org); imp = _imp(eng)
        f = _finding(imp, 80000)
        # Revenue 10M @ midpoint 0.75% → overall 75,000; 80,000 ≥ overall.
        summary = gm.apply_materiality_to_import(
            imp, benchmark_amount=10_000_000, benchmark_key="revenue")
        eng.refresh_from_db(); f.refresh_from_db()
        self.assertTrue(eng.materiality)  # persisted
        self.assertTrue(summary["materiality_available"])
        self.assertEqual(f.materiality_status, _MS.ABOVE_OVERALL)


class IdempotencyAndStatusTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def test_idempotent(self):
        f = _finding(self.imp, 150000)
        s1 = gm.apply_materiality_to_import(self.imp, materiality=PROFILE)
        f.refresh_from_db(); v1 = (f.materiality_status, f.materiality_adjusted_score)
        s2 = gm.apply_materiality_to_import(self.imp, materiality=PROFILE)
        f.refresh_from_db(); v2 = (f.materiality_status, f.materiality_adjusted_score)
        self.assertEqual(v1, v2)
        self.assertEqual(s1["by_materiality_status"], s2["by_materiality_status"])
        self.assertEqual(GeneralLedgerRiskFinding.objects.count(), 1)  # no new rows

    def test_candidate_status_preserved(self):
        f = _finding(self.imp, 150000, status=_F.Status.CANDIDATE)
        g = _finding(self.imp, 20000, status=_F.Status.ACCEPTED)
        gm.apply_materiality_to_import(self.imp, materiality=PROFILE)
        f.refresh_from_db(); g.refresh_from_db()
        self.assertEqual(f.status, _F.Status.CANDIDATE)
        self.assertEqual(g.status, _F.Status.ACCEPTED)  # untouched


class TenantTests(TestCase):
    def test_service_rejects_cross_tenant(self):
        eng = _eng(_org("A"))
        imp = GeneralLedgerImport.objects.create(
            engagement=eng, organization=_org("B"), source_format="csv")
        with self.assertRaises(ValidationError):
            gm.apply_materiality_to_import(imp, materiality=PROFILE)


class ApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA"); self.user = _user(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def test_apply_and_filter(self):
        _finding(self.imp, 1000)        # trivial
        _finding(self.imp, 150000)      # above overall
        url = f"/api/v1/audit/general-ledger/imports/{self.imp.id}/apply-materiality/"
        resp = self.client.post(url, {"materiality": PROFILE}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["materiality_available"])
        # Filter by materiality_status.
        lst = self.client.get(
            "/api/v1/audit/general-ledger/risk-findings/?materiality_status=trivial").json()
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["materiality_status"], "trivial")

    def test_apply_other_org_denied(self):
        other_imp = _imp(_eng(_org("OrgB"), code="OTHER-1"))
        _finding(other_imp, 150000)
        url = f"/api/v1/audit/general-ledger/imports/{other_imp.id}/apply-materiality/"
        resp = self.client.post(url, {"materiality": PROFILE}, format="json")
        self.assertEqual(resp.status_code, 404)
        other_imp.risk_findings.first().refresh_from_db()
        self.assertEqual(other_imp.risk_findings.first().materiality_status,
                         _MS.NOT_ASSESSED)


class LedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        eng = _eng(_org()); imp = _imp(eng)
        _finding(imp, 150000)
        gm.apply_materiality_to_import(imp, materiality=PROFILE)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
