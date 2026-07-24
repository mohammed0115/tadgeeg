"""TADGEEG-FIN-AUDIT-6B — Client portal & collaboration tests (backend).

Covers the additive 6B backend: request numbering, client assignment, SLA
helpers, upload format validation, management explanation, notifications,
status counts, append-only timeline, and the security rules that a client user
can only ever touch their OWN assigned requests (and never review, or reach
another organization).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import (
    AuditEngagement,
    AuditEvidenceRequest,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User
from apps.notifications.models import Notification

_R = AuditEvidenceRequest
_S = _R.Status
_FS = GeneralLedgerRiskFinding.Status

PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _auditor(org, email="auditor@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _client_user(org, email="client@e.com"):
    """A client-side user. Role is irrelevant — access is per-request (6B)."""
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Cli Ent",
        role=User.Role.FINANCE_MANAGER, organization=org)


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31", materiality=PROFILE)


def _finding(eng):
    imp = GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="t",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal("20000"), account_code="6000", status=_FS.NEEDS_EVIDENCE)


def _f(name="evidence.pdf", content=b"hello-evidence"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class Fixture(TestCase):
    def setUp(self):
        self.org = _org()
        self.auditor = _auditor(self.org)
        self.client_user = _client_user(self.org)
        self.eng = _eng(self.org)
        self.finding = _finding(self.eng)

    def _make(self, **kwargs):
        kwargs.setdefault("assigned_client_user", self.client_user)
        return ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="Provide invoice",
            gl_finding=self.finding, **kwargs)


class RequestNumberAndAssignmentTests(Fixture):
    def test_request_number_is_sequential_per_org(self):
        r1 = self._make()
        r2 = self._make()
        self.assertEqual(r1.request_number, "EVR-00001")
        self.assertEqual(r2.request_number, "EVR-00002")

    def test_request_numbers_are_independent_per_org(self):
        self._make()
        other = _org("OrgB")
        oa, oc = _auditor(other, "a2@e.com"), _client_user(other, "c2@e.com")
        oeng = _eng(other, code="B-1")
        r = ev.create_evidence_request(
            engagement=oeng, actor=oa, title="x", gl_finding=_finding(oeng),
            assigned_client_user=oc)
        self.assertEqual(r.request_number, "EVR-00001")

    def test_client_assignment_recorded_and_notified(self):
        req = self._make()
        self.assertEqual(req.assigned_client_user_id, self.client_user.id)
        self.assertTrue(req.events.filter(event_type="assigned").exists())
        self.assertTrue(Notification.objects.filter(
            user=self.client_user, source_id=str(req.id)).exists())

    def test_assign_users_cross_org_rejected(self):
        req = self._make()
        outsider = _client_user(_org("OrgC"), "out@e.com")
        with self.assertRaises(ev.EvidenceRequestError):
            ev.assign_users(request=req, actor=self.auditor,
                            assigned_client_user=outsider)

    def test_reassignment_appends_event(self):
        req = self._make(assigned_client_user=None)
        before = req.events.count()
        ev.assign_users(request=req, actor=self.auditor,
                        assigned_client_user=self.client_user)
        self.assertEqual(req.assigned_client_user_id, self.client_user.id)
        self.assertGreater(req.events.count(), before)


class SlaTests(Fixture):
    def test_overdue_and_days_remaining(self):
        past = timezone.now().date() - timedelta(days=3)
        req = self._make(due_date=past)
        self.assertTrue(req.is_overdue)
        self.assertEqual(req.days_remaining, -3)
        self.assertEqual(req.sla_state, "overdue")

    def test_on_track_and_due_soon(self):
        soon = self._make(due_date=timezone.now().date() + timedelta(days=2))
        self.assertEqual(soon.sla_state, "due_soon")
        later = self._make(due_date=timezone.now().date() + timedelta(days=30))
        self.assertEqual(later.sla_state, "on_track")

    def test_final_request_is_completed_not_overdue(self):
        req = self._make(due_date=timezone.now().date() - timedelta(days=5))
        ev.review_evidence_request(request=req, actor=self.auditor, action="cancel")
        self.assertFalse(req.is_overdue)
        self.assertEqual(req.sla_state, "completed")

    def test_no_due_date(self):
        req = self._make()
        self.assertIsNone(req.days_remaining)
        self.assertFalse(req.is_overdue)


class UploadValidationTests(Fixture):
    def test_allowed_formats_accepted(self):
        req = self._make()
        for name in ("a.pdf", "b.docx", "c.xlsx", "d.png", "e.jpg", "f.zip"):
            att = ev.add_attachment(request=req, actor=self.client_user,
                                    uploaded_file=_f(name, b"data"))
            self.assertEqual(att.evidence_request_id, req.id)

    def test_disallowed_format_rejected(self):
        req = self._make()
        for bad in ("virus.exe", "script.sh", "page.html", "data.csv"):
            with self.assertRaises(ev.EvidenceRequestError, msg=bad):
                ev.add_attachment(request=req, actor=self.client_user,
                                  uploaded_file=_f(bad, b"data"))
        self.assertEqual(req.attachments.count(), 0)

    def test_executable_disguised_as_pdf_rejected(self):
        req = self._make()
        with self.assertRaises(ev.EvidenceRequestError):
            ev.add_attachment(request=req, actor=self.client_user,
                              uploaded_file=_f("payload.pdf", b"MZ\x90\x00binary"))

    def test_sha256_and_metadata_stored(self):
        import hashlib
        req = self._make()
        att = ev.add_attachment(request=req, actor=self.client_user,
                                uploaded_file=_f("x.pdf", b"abc123"))
        self.assertEqual(att.file_sha256, hashlib.sha256(b"abc123").hexdigest())
        self.assertEqual(att.size_bytes, 6)


class ManagementExplanationTests(Fixture):
    def test_record_and_append_event(self):
        req = self._make()
        ev.record_management_explanation(
            request=req, actor=self.client_user, explanation="Goods received late.")
        req.refresh_from_db()
        self.assertEqual(req.management_explanation, "Goods received late.")
        self.assertTrue(req.events.filter(event_type="note_added").exists())

    def test_empty_rejected(self):
        req = self._make()
        with self.assertRaises(ev.EvidenceRequestError):
            ev.record_management_explanation(
                request=req, actor=self.client_user, explanation="   ")

    def test_not_allowed_on_final_request(self):
        req = self._make()
        ev.review_evidence_request(request=req, actor=self.auditor, action="cancel")
        with self.assertRaises(ev.EvidenceRequestError):
            ev.record_management_explanation(
                request=req, actor=self.client_user, explanation="late")


class NotificationTests(Fixture):
    def test_upload_notifies_auditor(self):
        req = self._make()
        Notification.objects.all().delete()
        ev.add_attachment(request=req, actor=self.client_user,
                          uploaded_file=_f(), notify_auditor=True)
        self.assertTrue(Notification.objects.filter(
            user=self.auditor, source_id=str(req.id)).exists())

    def test_review_outcomes_notify_client(self):
        for action, note in (("accept", ""), ("reject", "bad"), ("more_evidence", "more")):
            req = self._make()
            ev.add_attachment(request=req, actor=self.client_user, uploaded_file=_f())
            ev.submit_evidence(request=req, actor=self.client_user)
            ev.review_evidence_request(request=req, actor=self.auditor, action="under_review")
            Notification.objects.all().delete()
            ev.review_evidence_request(request=req, actor=self.auditor,
                                       action=action, note=note)
            self.assertTrue(
                Notification.objects.filter(user=self.client_user,
                                            source_id=str(req.id)).exists(),
                f"no notification for {action}")

    def test_no_client_assigned_means_no_crash(self):
        req = self._make(assigned_client_user=None)
        ev.add_attachment(request=req, actor=self.auditor, uploaded_file=_f())
        ev.submit_evidence(request=req, actor=self.auditor)
        ev.review_evidence_request(request=req, actor=self.auditor, action="under_review")
        ev.review_evidence_request(request=req, actor=self.auditor, action="accept")
        self.assertEqual(req.status, _S.ACCEPTED)


class StatusCountsTests(Fixture):
    def test_counts_and_overdue(self):
        self._make()  # open
        overdue = self._make(due_date=timezone.now().date() - timedelta(days=1))
        cancelled = self._make()
        ev.review_evidence_request(request=cancelled, actor=self.auditor, action="cancel")

        counts = ev.status_counts(organization=self.org)
        self.assertEqual(counts["open"], 2)
        self.assertEqual(counts["cancelled"], 1)
        self.assertEqual(counts["overdue"], 1)
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["open_gaps"], 2)

    def test_counts_scoped_to_client_user(self):
        self._make()
        other_client = _client_user(self.org, "c9@e.com")
        self._make(assigned_client_user=other_client)
        counts = ev.status_counts(organization=self.org, client_user=self.client_user)
        self.assertEqual(counts["total"], 1)

    def test_counts_are_a_single_query(self):
        self._make()
        with self.assertNumQueries(1):
            ev.status_counts(organization=self.org)


class ClientApiSecurityTests(Fixture):
    """The client may upload/submit on THEIR request — and nothing else."""

    def setUp(self):
        super().setUp()
        self.req = self._make()
        self.api = APIClient()
        self.api.force_authenticate(self.client_user)

    def _url(self, suffix=""):
        return f"/api/v1/audit/evidence-requests/{self.req.id}/{suffix}"

    def test_client_sees_only_assigned_requests(self):
        other_client = _client_user(self.org, "c8@e.com")
        hidden = self._make(assigned_client_user=other_client)
        resp = self.api.get("/api/v1/audit/evidence-requests/")
        ids = [r["id"] for r in resp.json()]
        self.assertIn(str(self.req.id), ids)
        self.assertNotIn(str(hidden.id), ids)

    def test_client_cannot_open_another_clients_request(self):
        other_client = _client_user(self.org, "c7@e.com")
        hidden = self._make(assigned_client_user=other_client)
        resp = self.api.get(f"/api/v1/audit/evidence-requests/{hidden.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_client_can_upload_and_submit(self):
        up = self.api.post(self._url("attachments/"),
                           {"file": _f()}, format="multipart")
        self.assertEqual(up.status_code, 201, up.content)
        sub = self.api.post(self._url("submit/"), {}, format="json")
        self.assertEqual(sub.status_code, 200)
        self.assertEqual(sub.json()["status"], "submitted")

    def test_client_cannot_review(self):
        self.api.post(self._url("attachments/"), {"file": _f()}, format="multipart")
        self.api.post(self._url("submit/"), {}, format="json")
        resp = self.api.post(self._url("review/"), {"action": "accept"}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.req.refresh_from_db()
        self.assertNotEqual(self.req.status, _S.ACCEPTED)

    def test_client_cannot_create_or_assign(self):
        create = self.api.post("/api/v1/audit/evidence-requests/", {
            "engagement": str(self.eng.id), "gl_finding": str(self.finding.id),
            "title": "self-serve"}, format="json")
        self.assertEqual(create.status_code, 403)
        assign = self.api.post(self._url("assign/"),
                               {"assigned_client_user": str(self.client_user.id)},
                               format="json")
        self.assertEqual(assign.status_code, 403)

    def test_client_cannot_reach_other_organization(self):
        other = _org("OrgZ")
        oa, oc = _auditor(other, "z@e.com"), _client_user(other, "zc@e.com")
        oeng = _eng(other, code="Z-1")
        foreign = ev.create_evidence_request(
            engagement=oeng, actor=oa, title="foreign",
            gl_finding=_finding(oeng), assigned_client_user=oc)
        resp = self.api.get(f"/api/v1/audit/evidence-requests/{foreign.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_client_management_explanation_endpoint(self):
        resp = self.api.post(self._url("management-explanation/"),
                             {"management_explanation": "Explained."}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.req.refresh_from_db()
        self.assertEqual(self.req.management_explanation, "Explained.")

    def test_client_upload_rejects_bad_format_via_api(self):
        resp = self.api.post(self._url("attachments/"),
                             {"file": _f("bad.exe", b"data")}, format="multipart")
        self.assertEqual(resp.status_code, 400)


class AuditorApiTests(Fixture):
    def test_auditor_can_assign_client(self):
        req = self._make(assigned_client_user=None)
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.post(f"/api/v1/audit/evidence-requests/{req.id}/assign/",
                        {"assigned_client_user": str(self.client_user.id)},
                        format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        req.refresh_from_db()
        self.assertEqual(req.assigned_client_user_id, self.client_user.id)

    def test_assign_rejects_user_from_another_org(self):
        req = self._make()
        outsider = _client_user(_org("OrgQ"), "q@e.com")
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.post(f"/api/v1/audit/evidence-requests/{req.id}/assign/",
                        {"assigned_client_user": str(outsider.id)}, format="json")
        self.assertEqual(resp.status_code, 404)


class LedgerIsolationTests(Fixture):
    def test_client_collaboration_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        req = self._make()
        ev.add_attachment(request=req, actor=self.client_user, uploaded_file=_f())
        ev.record_management_explanation(request=req, actor=self.client_user,
                                         explanation="ctx")
        ev.submit_evidence(request=req, actor=self.client_user)
        ev.review_evidence_request(request=req, actor=self.auditor, action="under_review")
        ev.review_evidence_request(request=req, actor=self.auditor, action="accept")

        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
        # And the finding is still untouched by the collaboration flow.
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, _FS.NEEDS_EVIDENCE)
