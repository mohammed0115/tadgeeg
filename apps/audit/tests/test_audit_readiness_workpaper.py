"""TADGEEG-FIN-AUDIT-5A — Audit Readiness / Opinion Preparation Workpaper tests.

Covers readiness conclusions across tiers (no diffs / below materiality /
unadjusted-need-evaluation / possible-material-impact / insufficient-evidence /
not-assessed), pending-response handling, proposed-adjustment counting, the
legal disclaimer, ABSENCE of unsafe formal-opinion phrases, SAD immutability,
idempotency, org scoping (service + API), cross-org denial, and no ledger writes.
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AuditDifferenceItem,
    AuditEngagement,
    AuditReadinessWorkpaper,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import audit_difference_summary as sad
from apps.audit.services import audit_readiness_workpaper as readiness
from apps.authentication.models import Organization, User

_W = AuditReadinessWorkpaper
_RC = _W.ReadinessConclusion
_OD = _W.OpinionDirection
_MR = AuditDifferenceItem.ManagementResponse
_FS = GeneralLedgerRiskFinding.Status

PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}

# Phrases that would imply the system issued a formal opinion — must NOT appear.
UNSAFE_PHRASES = [
    "in our opinion", "present fairly", "unqualified opinion issued",
    "qualified opinion issued", "adverse opinion issued", "disclaimer issued",
]


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


def _finding(eng, imp, amount, *, status=_FS.ACCEPTED, account_code="6000"):
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="t",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal(str(amount)), account_code=account_code, status=status)


def _build_sad(eng):
    return sad.recalculate_for_engagement(eng)


class ConclusionTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def test_no_accepted_differences(self):
        _build_sad(self.eng)  # no accepted findings
        wp = readiness.generate_for_engagement(self.eng)
        self.assertEqual(wp.readiness_conclusion, _RC.NO_ACCEPTED_DIFFERENCES)
        self.assertEqual(wp.suggested_opinion_direction, _OD.LIKELY_UNMODIFIED)

    def test_below_materiality(self):
        # Single small accepted diff, response adjusted → uncorrected 0.
        f = _finding(self.eng, self.imp, 1000)
        s = _build_sad(self.eng)
        item = s.items.first()
        item.management_response_status = _MR.ADJUSTED
        item.save(update_fields=["management_response_status"])
        wp = readiness.generate_for_engagement(self.eng)
        self.assertEqual(wp.readiness_conclusion, _RC.DIFFERENCES_BELOW_MATERIALITY)
        self.assertEqual(wp.suggested_opinion_direction, _OD.LIKELY_UNMODIFIED)

    def test_unadjusted_need_evaluation(self):
        # 20k uncorrected (> trivial, < overall), response unadjusted.
        _finding(self.eng, self.imp, 20000)
        s = _build_sad(self.eng)
        it = s.items.first()
        it.management_response_status = _MR.UNADJUSTED
        it.save(update_fields=["management_response_status"])
        wp = readiness.generate_for_engagement(self.eng)
        self.assertEqual(wp.readiness_conclusion, _RC.UNADJUSTED_NEED_EVALUATION)
        self.assertEqual(wp.suggested_opinion_direction, _OD.POSSIBLE_MODIFIED)

    def test_possible_material_impact(self):
        _finding(self.eng, self.imp, 150000)  # >= overall, uncorrected
        s = _build_sad(self.eng)
        it = s.items.first()
        it.management_response_status = _MR.UNADJUSTED
        it.save(update_fields=["management_response_status"])
        wp = readiness.generate_for_engagement(self.eng)
        self.assertEqual(wp.readiness_conclusion, _RC.POSSIBLE_MATERIAL_IMPACT)
        self.assertEqual(wp.suggested_opinion_direction, _OD.POSSIBLE_MODIFIED)

    def test_insufficient_evidence_when_needs_evidence_open(self):
        _finding(self.eng, self.imp, 20000)               # accepted
        _finding(self.eng, self.imp, 30000, status=_FS.NEEDS_EVIDENCE)  # open evidence
        _build_sad(self.eng)
        wp = readiness.generate_for_engagement(self.eng)
        self.assertEqual(wp.readiness_conclusion, _RC.INSUFFICIENT_EVIDENCE)
        self.assertEqual(wp.suggested_opinion_direction, _OD.INSUFFICIENT_BASIS)
        self.assertEqual(wp.total_needs_evidence, 1)

    def test_not_assessed_without_materiality(self):
        eng = _eng(_org("B"), code="NOPROF", materiality={})
        imp = _imp(eng)
        _finding(eng, imp, 20000)
        _build_sad(eng)
        wp = readiness.generate_for_engagement(eng)
        self.assertEqual(wp.readiness_conclusion, _RC.NOT_ASSESSED)
        self.assertEqual(wp.suggested_opinion_direction, _OD.NO_DIRECTION)

    def test_pending_response_forces_evaluation(self):
        # Accepted 1000 (trivial) but response still pending → cannot conclude below.
        _finding(self.eng, self.imp, 1000)
        s = _build_sad(self.eng)
        it = s.items.first()
        it.management_response_status = _MR.PENDING
        it.save(update_fields=["management_response_status"])
        wp = readiness.generate_for_engagement(self.eng)
        self.assertEqual(wp.readiness_conclusion, _RC.UNADJUSTED_NEED_EVALUATION)
        self.assertEqual(wp.total_pending_management_response, 1)


class WordingAndCountsTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)
        _finding(self.eng, self.imp, 150000)
        _build_sad(self.eng)

    def test_disclaimer_present(self):
        wp = readiness.generate_for_engagement(self.eng)
        self.assertIn("does not constitute a formal audit opinion", wp.legal_disclaimer)
        self.assertIn("licensed auditor", wp.legal_disclaimer)

    def test_no_unsafe_opinion_phrases(self):
        wp = readiness.generate_for_engagement(self.eng)
        from apps.audit.serializers import AuditReadinessWorkpaperSerializer
        blob = json.dumps(AuditReadinessWorkpaperSerializer(wp).data, default=str).lower()
        for phrase in UNSAFE_PHRASES:
            self.assertNotIn(phrase, blob, f"unsafe phrase present: {phrase}")
        # Any direction must be "subject to auditor review".
        self.assertIn("subject_to_auditor_review", wp.suggested_opinion_direction)

    def test_proposed_adjustments_counted(self):
        from apps.audit.services import proposed_audit_adjustment as adj
        item = self.eng.difference_summaries.first().items.first()
        user = _user(self.org, "x@e.com")
        adj.create_or_update_adjustment(
            item, actor=user, adjustment_type="correction", amount="5000",
            debit_account_code="5200", credit_account_code="2100")
        wp = readiness.generate_for_engagement(self.eng)
        self.assertEqual(wp.proposed_adjustment_summary["count"], 1)


class ImmutabilityAndIdempotencyTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)
        self.f = _finding(self.eng, self.imp, 150000)
        self.summary = _build_sad(self.eng)

    def test_idempotent_single_workpaper(self):
        w1 = readiness.generate_for_engagement(self.eng)
        w2 = readiness.generate_for_engagement(self.eng)
        self.assertEqual(w1.id, w2.id)
        self.assertEqual(AuditReadinessWorkpaper.objects.filter(engagement=self.eng).count(), 1)
        self.assertEqual(w1.readiness_conclusion, w2.readiness_conclusion)

    def test_sad_and_findings_not_modified(self):
        before_items = list(self.summary.items.values_list("id", "amount_impact",
                                                            "management_response_status"))
        before_finding = (self.f.status, self.f.score, self.f.amount_impact)
        readiness.generate_for_engagement(self.eng)
        self.summary.refresh_from_db(); self.f.refresh_from_db()
        after_items = list(self.summary.items.values_list("id", "amount_impact",
                                                          "management_response_status"))
        self.assertEqual(before_items, after_items)
        self.assertEqual((self.f.status, self.f.score, self.f.amount_impact), before_finding)

    def test_no_sad_raises(self):
        eng2 = _eng(_org("C"), code="NOSAD")
        with self.assertRaises(readiness.ReadinessError):
            readiness.generate_for_engagement(eng2)


class ModelTests(TestCase):
    def test_clean_rejects_cross_tenant(self):
        eng = _eng(_org("A"))
        s = _build_sad(eng)
        wp = AuditReadinessWorkpaper(engagement=eng, organization=_org("B"), sad_summary=s)
        with self.assertRaises(ValidationError):
            wp.clean()


class ApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA"); self.user = _user(self.org); self.eng = _eng(self.org)
        self.imp = _imp(self.eng)
        _finding(self.eng, self.imp, 150000)
        _build_sad(self.eng)
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def test_generate_view_detail_org_scoped(self):
        gen = self.client.post(
            f"/api/v1/audit/engagements/{self.eng.id}/audit-readiness/generate/", {}, format="json")
        self.assertEqual(gen.status_code, 200, gen.content)
        wid = gen.json()["id"]
        self.assertIn("does not constitute a formal audit opinion",
                      gen.json()["legal_disclaimer"])
        got = self.client.get(f"/api/v1/audit/engagements/{self.eng.id}/audit-readiness/")
        self.assertEqual(got.status_code, 200)
        detail = self.client.get(f"/api/v1/audit/audit-readiness/{wid}/")
        self.assertEqual(detail.status_code, 200)

    def test_generate_other_org_denied(self):
        other_eng = _eng(_org("OrgB"), code="OTHER-1")
        resp = self.client.post(
            f"/api/v1/audit/engagements/{other_eng.id}/audit-readiness/generate/", {}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(AuditReadinessWorkpaper.objects.filter(engagement=other_eng).count(), 0)

    def test_detail_other_org_denied(self):
        other_eng = _eng(_org("OrgC"), code="OTHER-2")
        _imp_o = _imp(other_eng); _finding(other_eng, _imp_o, 1000)
        _build_sad(other_eng)
        other_wp = readiness.generate_for_engagement(other_eng)
        resp = self.client.get(f"/api/v1/audit/audit-readiness/{other_wp.id}/")
        self.assertEqual(resp.status_code, 404)


class LedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        org = _org(); eng = _eng(org); imp = _imp(eng)
        _finding(eng, imp, 150000)
        _build_sad(eng)
        readiness.generate_for_engagement(eng)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
