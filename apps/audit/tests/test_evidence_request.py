"""TADGEEG-FIN-AUDIT-6A — Evidence Request workflow tests (backend).

Covers: creation linked to a GL finding / SAD item, link + org validation,
allowed and rejected transitions, note-required reviews, attachment creation +
hash/metadata, accept-requires-attachment (with the explanation-only exception),
append-only event history, finality, cross-org denial, API org scoping and
permissions, no automatic finding change, and no writes to the ledger.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AuditDifferenceItem,
    AuditEngagement,
    AuditEvidenceAttachment,
    AuditEvidenceRequest,
    AuditEvidenceRequestEvent,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import audit_difference_summary as sad
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User

_R = AuditEvidenceRequest
_S = _R.Status
_FS = GeneralLedgerRiskFinding.Status

PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _user(org, email="a@e.com", role=None):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="T",
        role=role or User.Role.SENIOR_AUDITOR, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31", materiality=PROFILE)


def _imp(eng):
    return GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")


def _finding(eng, imp, amount=20000, *, status=_FS.NEEDS_EVIDENCE):
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="t",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal(str(amount)), account_code="6000", status=status)


def _file(name="evidence.pdf", content=b"hello-evidence"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class CreationTests(TestCase):
    def setUp(self):
        self.org = _org(); self.user = _user(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)
        self.finding = _finding(self.eng, self.imp)

    def test_create_linked_to_gl_finding(self):
        req = ev.create_evidence_request(
            engagement=self.eng, actor=self.user, title="Need invoice",
            gl_finding=self.finding)
        self.assertEqual(req.status, _S.OPEN)
        self.assertEqual(req.gl_finding_id, self.finding.id)
        self.assertEqual(req.organization_id, self.org.id)
        self.assertTrue(req.events.filter(event_type="created").exists())

    def test_create_linked_to_sad_item(self):
        _build = sad.recalculate_for_engagement
        # need an accepted finding for a SAD item
        _finding(self.eng, self.imp, 30000, status=_FS.ACCEPTED)
        summary = _build(self.eng)
        item = summary.items.first()
        req = ev.create_evidence_request(
            engagement=self.eng, actor=self.user, title="SAD support", sad_item=item)
        self.assertEqual(req.sad_item_id, item.id)

    def test_create_requires_linked_object(self):
        with self.assertRaises(ValidationError):
            ev.create_evidence_request(
                engagement=self.eng, actor=self.user, title="orphan")

    def test_create_cross_org_finding_rejected(self):
        other_eng = _eng(_org("B"), code="B-1")
        other_finding = _finding(other_eng, _imp(other_eng))
        with self.assertRaises(ValidationError):
            ev.create_evidence_request(
                engagement=self.eng, actor=self.user, title="x",
                gl_finding=other_finding)


class TransitionTests(TestCase):
    def setUp(self):
        self.org = _org(); self.user = _user(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)
        self.finding = _finding(self.eng, self.imp)
        self.req = ev.create_evidence_request(
            engagement=self.eng, actor=self.user, title="Need doc",
            gl_finding=self.finding)

    def test_full_happy_path(self):
        ev.add_attachment(request=self.req, actor=self.user, uploaded_file=_file())
        ev.submit_evidence(request=self.req, actor=self.user)
        self.assertEqual(self.req.status, _S.SUBMITTED)
        self.assertIsNotNone(self.req.submitted_at)
        ev.review_evidence_request(request=self.req, actor=self.user, action="under_review")
        self.assertEqual(self.req.status, _S.UNDER_REVIEW)
        ev.review_evidence_request(request=self.req, actor=self.user, action="accept")
        self.assertEqual(self.req.status, _S.ACCEPTED)
        self.assertIsNotNone(self.req.reviewed_at)

    def test_invalid_transition_rejected(self):
        # open → accepted is not allowed.
        with self.assertRaises(ev.EvidenceRequestError):
            ev.review_evidence_request(request=self.req, actor=self.user, action="accept")

    def test_reject_requires_note(self):
        ev.add_attachment(request=self.req, actor=self.user, uploaded_file=_file())
        ev.submit_evidence(request=self.req, actor=self.user)
        ev.review_evidence_request(request=self.req, actor=self.user, action="under_review")
        with self.assertRaises(ev.EvidenceRequestError):
            ev.review_evidence_request(request=self.req, actor=self.user, action="reject")
        ev.review_evidence_request(request=self.req, actor=self.user,
                                   action="reject", note="insufficient")
        self.assertEqual(self.req.status, _S.REJECTED)

    def test_more_evidence_requires_note_then_resubmit(self):
        ev.add_attachment(request=self.req, actor=self.user, uploaded_file=_file())
        ev.submit_evidence(request=self.req, actor=self.user)
        ev.review_evidence_request(request=self.req, actor=self.user, action="under_review")
        with self.assertRaises(ev.EvidenceRequestError):
            ev.review_evidence_request(request=self.req, actor=self.user, action="more_evidence")
        ev.review_evidence_request(request=self.req, actor=self.user,
                                   action="more_evidence", note="need bank statement")
        self.assertEqual(self.req.status, _S.MORE_EVIDENCE_REQUIRED)
        ev.submit_evidence(request=self.req, actor=self.user)
        self.assertEqual(self.req.status, _S.SUBMITTED)

    def test_accept_requires_attachment(self):
        ev.submit_evidence(request=self.req, actor=self.user)
        ev.review_evidence_request(request=self.req, actor=self.user, action="under_review")
        with self.assertRaises(ev.EvidenceRequestError):
            ev.review_evidence_request(request=self.req, actor=self.user, action="accept")

    def test_accept_explanation_only_without_attachment(self):
        req = ev.create_evidence_request(
            engagement=self.eng, actor=self.user, title="explain",
            gl_finding=self.finding,
            request_reason=_R.RequestReason.MANAGEMENT_EXPLANATION)
        ev.submit_evidence(request=req, actor=self.user)
        ev.review_evidence_request(request=req, actor=self.user, action="under_review")
        ev.review_evidence_request(request=req, actor=self.user, action="accept")
        self.assertEqual(req.status, _S.ACCEPTED)

    def test_final_states_cannot_transition(self):
        ev.review_evidence_request(request=self.req, actor=self.user, action="cancel")
        self.assertEqual(self.req.status, _S.CANCELLED)
        with self.assertRaises(ev.EvidenceRequestError):
            ev.submit_evidence(request=self.req, actor=self.user)

    def test_cannot_attach_to_final_request(self):
        ev.review_evidence_request(request=self.req, actor=self.user, action="cancel")
        with self.assertRaises(ev.EvidenceRequestError):
            ev.add_attachment(request=self.req, actor=self.user, uploaded_file=_file())


class AttachmentAndHistoryTests(TestCase):
    def setUp(self):
        self.org = _org(); self.user = _user(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)
        self.finding = _finding(self.eng, self.imp)
        self.req = ev.create_evidence_request(
            engagement=self.eng, actor=self.user, title="Need doc",
            gl_finding=self.finding)

    def test_attachment_hash_and_metadata(self):
        att = ev.add_attachment(request=self.req, actor=self.user,
                                uploaded_file=_file(content=b"abc123"),
                                description="the invoice")
        import hashlib
        self.assertEqual(att.file_sha256, hashlib.sha256(b"abc123").hexdigest())
        self.assertEqual(att.size_bytes, 6)
        self.assertEqual(att.organization_id, self.org.id)
        self.assertEqual(att.engagement_id, self.eng.id)

    def test_event_history_is_append_only_and_ordered(self):
        ev.add_attachment(request=self.req, actor=self.user, uploaded_file=_file())
        ev.submit_evidence(request=self.req, actor=self.user)
        types = list(self.req.events.values_list("event_type", flat=True))
        self.assertEqual(types[0], "created")
        self.assertIn("attachment_added", types)
        self.assertIn("submitted", types)


class LedgerAndFindingIsolationTests(TestCase):
    def test_accept_does_not_change_finding_and_no_ledger_writes(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        org = _org(); user = _user(org); eng = _eng(org); imp = _imp(eng)
        finding = _finding(eng, imp)
        before_status = finding.status
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())

        req = ev.create_evidence_request(
            engagement=eng, actor=user, title="x", gl_finding=finding)
        ev.add_attachment(request=req, actor=user, uploaded_file=_file())
        ev.submit_evidence(request=req, actor=user)
        ev.review_evidence_request(request=req, actor=user, action="under_review")
        ev.review_evidence_request(request=req, actor=user, action="accept")

        finding.refresh_from_db()
        self.assertEqual(finding.status, before_status)  # finding NOT auto-resolved
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)


class ApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA"); self.user = _user(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)
        self.finding = _finding(self.eng, self.imp)
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def _create(self):
        return self.client.post("/api/v1/audit/evidence-requests/", {
            "engagement": str(self.eng.id), "gl_finding": str(self.finding.id),
            "title": "Need invoice", "request_reason": "invoice_support",
        }, format="json")

    def test_create_list_detail_org_scoped(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 201, resp.content)
        wid = resp.json()["id"]
        lst = self.client.get("/api/v1/audit/evidence-requests/")
        self.assertEqual(lst.status_code, 200)
        self.assertTrue(any(r["id"] == wid for r in lst.json()))
        detail = self.client.get(f"/api/v1/audit/evidence-requests/{wid}/")
        self.assertEqual(detail.status_code, 200)

    def test_upload_submit_review_flow(self):
        wid = self._create().json()["id"]
        up = self.client.post(
            f"/api/v1/audit/evidence-requests/{wid}/attachments/",
            {"file": _file(), "description": "invoice"}, format="multipart")
        self.assertEqual(up.status_code, 201, up.content)
        sub = self.client.post(f"/api/v1/audit/evidence-requests/{wid}/submit/", {}, format="json")
        self.assertEqual(sub.status_code, 200)
        self.assertEqual(sub.json()["status"], "submitted")
        rev = self.client.post(f"/api/v1/audit/evidence-requests/{wid}/review/",
                               {"action": "under_review"}, format="json")
        self.assertEqual(rev.json()["status"], "under_review")
        acc = self.client.post(f"/api/v1/audit/evidence-requests/{wid}/review/",
                               {"action": "accept"}, format="json")
        self.assertEqual(acc.json()["status"], "accepted")
        events = self.client.get(f"/api/v1/audit/evidence-requests/{wid}/events/")
        self.assertEqual(events.status_code, 200)
        self.assertGreaterEqual(len(events.json()), 4)

    def test_junior_cannot_create(self):
        junior = _user(self.org, email="j@e.com", role=User.Role.JUNIOR_AUDITOR)
        c = APIClient(); c.force_authenticate(junior)
        resp = c.post("/api/v1/audit/evidence-requests/", {
            "engagement": str(self.eng.id), "gl_finding": str(self.finding.id),
            "title": "x"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_cross_org_denied(self):
        other = _org("OrgB"); ouser = _user(other, email="o@e.com")
        oeng = _eng(other, code="B-1"); oimp = _imp(oeng); of = _finding(oeng, oimp)
        oreq = ev.create_evidence_request(
            engagement=oeng, actor=ouser, title="x", gl_finding=of)
        detail = self.client.get(f"/api/v1/audit/evidence-requests/{oreq.id}/")
        self.assertEqual(detail.status_code, 404)
        rev = self.client.post(f"/api/v1/audit/evidence-requests/{oreq.id}/review/",
                               {"action": "cancel"}, format="json")
        self.assertEqual(rev.status_code, 404)
        # And it is not visible in OrgA's list.
        lst = self.client.get("/api/v1/audit/evidence-requests/")
        self.assertFalse(any(r["id"] == str(oreq.id) for r in lst.json()))
