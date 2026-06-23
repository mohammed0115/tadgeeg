"""TADGEEG-FIN-AUDIT-3B — GL finding review workflow tests.

Covers allowed/invalid transitions, finality of accepted/dismissed, note
requirements, trail creation (one per transition), reviewed_by/at/note,
preservation of original risk score/severity and materiality fields, org
scoping (service + API), cross-org denial, and no ledger writes.
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
    GeneralLedgerRiskFindingReview,
)
from apps.audit.services import gl_finding_review as rv
from apps.authentication.models import Organization, User

_F = GeneralLedgerRiskFinding
_S = _F.Status


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _user(org, email="a@e.com"):
    return User.objects.create_user(email=email, password="StrongPass123!",
                                    full_name="T", role=User.Role.ADMIN, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


def _imp(eng):
    return GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")


def _finding(imp, *, status=_S.CANDIDATE, score=50, severity=_F.Severity.MEDIUM):
    eng = imp.engagement
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="t", risk_category=_F.Category.OTHER,
        severity=severity, score=score, amount_impact=Decimal("1000"), status=status)


class TransitionServiceTests(TestCase):
    def setUp(self):
        self.org = _org(); self.user = _user(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def test_candidate_to_accepted(self):
        f = _finding(self.imp)
        rv.review_finding(f, actor=self.user, to_status=_S.ACCEPTED)
        f.refresh_from_db()
        self.assertEqual(f.status, _S.ACCEPTED)
        self.assertEqual(f.reviewed_by, self.user)
        self.assertIsNotNone(f.reviewed_at)
        self.assertEqual(f.reviews.count(), 1)

    def test_candidate_to_dismissed_requires_note(self):
        f = _finding(self.imp)
        with self.assertRaises(rv.GLFindingReviewError):
            rv.review_finding(f, actor=self.user, to_status=_S.DISMISSED)
        # With a note it works.
        rv.review_finding(f, actor=self.user, to_status=_S.DISMISSED,
                          reviewer_note="Not a real issue", review_reason="false_positive")
        f.refresh_from_db()
        self.assertEqual(f.status, _S.DISMISSED)

    def test_candidate_to_needs_evidence_requires_note(self):
        f = _finding(self.imp)
        with self.assertRaises(rv.GLFindingReviewError):
            rv.review_finding(f, actor=self.user, to_status=_S.NEEDS_EVIDENCE)
        rv.review_finding(f, actor=self.user, to_status=_S.NEEDS_EVIDENCE,
                          reviewer_note="Need invoice copy")
        f.refresh_from_db()
        self.assertEqual(f.status, _S.NEEDS_EVIDENCE)

    def test_candidate_to_escalated_requires_note(self):
        f = _finding(self.imp)
        with self.assertRaises(rv.GLFindingReviewError):
            rv.review_finding(f, actor=self.user, to_status=_S.ESCALATED)
        rv.review_finding(f, actor=self.user, to_status=_S.ESCALATED,
                          reviewer_note="Escalate to partner")
        f.refresh_from_db()
        self.assertEqual(f.status, _S.ESCALATED)

    def test_needs_evidence_to_accepted(self):
        f = _finding(self.imp, status=_S.NEEDS_EVIDENCE)
        rv.review_finding(f, actor=self.user, to_status=_S.ACCEPTED)
        f.refresh_from_db()
        self.assertEqual(f.status, _S.ACCEPTED)

    def test_escalated_to_dismissed(self):
        f = _finding(self.imp, status=_S.ESCALATED)
        rv.review_finding(f, actor=self.user, to_status=_S.DISMISSED,
                          reviewer_note="Resolved after escalation")
        f.refresh_from_db()
        self.assertEqual(f.status, _S.DISMISSED)

    def test_accepted_is_final(self):
        f = _finding(self.imp, status=_S.ACCEPTED)
        with self.assertRaises(rv.GLFindingReviewError):
            rv.review_finding(f, actor=self.user, to_status=_S.DISMISSED,
                              reviewer_note="x")

    def test_dismissed_is_final(self):
        f = _finding(self.imp, status=_S.DISMISSED)
        with self.assertRaises(rv.GLFindingReviewError):
            rv.review_finding(f, actor=self.user, to_status=_S.ACCEPTED)

    def test_invalid_status_rejected(self):
        f = _finding(self.imp)
        with self.assertRaises(rv.GLFindingReviewError):
            rv.review_finding(f, actor=self.user, to_status="bogus")

    def test_invalid_transition_candidate_to_candidate(self):
        f = _finding(self.imp)
        with self.assertRaises(rv.GLFindingReviewError):
            rv.review_finding(f, actor=self.user, to_status=_S.CANDIDATE)

    def test_trail_created_once_per_transition(self):
        f = _finding(self.imp)
        rv.review_finding(f, actor=self.user, to_status=_S.NEEDS_EVIDENCE,
                          reviewer_note="n1")
        rv.review_finding(f, actor=self.user, to_status=_S.ACCEPTED)
        self.assertEqual(f.reviews.count(), 2)
        latest = f.reviews.first()  # ordered -created_at
        self.assertEqual(latest.to_status, _S.ACCEPTED)
        self.assertEqual(latest.from_status, _S.NEEDS_EVIDENCE)

    def test_preserves_risk_and_materiality(self):
        f = _finding(self.imp, score=72, severity=_F.Severity.HIGH)
        f.materiality_status = _F.MaterialityStatus.ABOVE_OVERALL
        f.materiality_adjusted_score = 97
        f.save(update_fields=["materiality_status", "materiality_adjusted_score"])
        rv.review_finding(f, actor=self.user, to_status=_S.ACCEPTED)
        f.refresh_from_db()
        self.assertEqual(f.score, 72)
        self.assertEqual(f.severity, _F.Severity.HIGH)
        self.assertEqual(f.materiality_status, _F.MaterialityStatus.ABOVE_OVERALL)
        self.assertEqual(f.materiality_adjusted_score, 97)

    def test_cross_tenant_actor_denied(self):
        f = _finding(self.imp)
        outsider = _user(_org("OrgB"), "b@e.com")
        with self.assertRaises(rv.GLFindingReviewError):
            rv.review_finding(f, actor=outsider, to_status=_S.ACCEPTED)
        f.refresh_from_db()
        self.assertEqual(f.status, _S.CANDIDATE)  # unchanged


class ReviewModelTests(TestCase):
    def test_clean_rejects_cross_tenant(self):
        eng = _eng(_org("A")); imp = _imp(eng); f = _finding(imp)
        review = GeneralLedgerRiskFindingReview(
            finding=f, engagement=eng, organization=_org("B"),
            from_status=_S.CANDIDATE, to_status=_S.ACCEPTED)
        with self.assertRaises(ValidationError):
            review.clean()


class ReviewApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA"); self.user = _user(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def _url(self, fid):
        return f"/api/v1/audit/general-ledger/risk-findings/{fid}/review/"

    def test_review_success(self):
        f = _finding(self.imp)
        resp = self.client.post(self._url(f.id), {
            "status": "accepted", "review_reason": "evidence_sufficient",
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["finding"]["status"], "accepted")
        self.assertEqual(resp.json()["finding"]["reviews_count"], 1)

    def test_missing_note_returns_400(self):
        f = _finding(self.imp)
        resp = self.client.post(self._url(f.id), {"status": "dismissed"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_transition_returns_400(self):
        f = _finding(self.imp, status=_S.ACCEPTED)
        resp = self.client.post(self._url(f.id), {
            "status": "dismissed", "reviewer_note": "x"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_cross_org_review_denied(self):
        other = _finding(_imp(_eng(_org("OrgB"), code="OTHER-1")))
        resp = self.client.post(self._url(other.id), {"status": "accepted"}, format="json")
        self.assertEqual(resp.status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.status, _S.CANDIDATE)


class LedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        org = _org(); user = _user(org); imp = _imp(_eng(org))
        f = _finding(imp)
        rv.review_finding(f, actor=user, to_status=_S.ACCEPTED)
        self.assertEqual(f.reviews.count(), 1)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
