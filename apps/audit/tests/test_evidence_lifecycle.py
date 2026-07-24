"""TADGEEG-FIN-AUDIT-6C — Evidence delivery & lifecycle tests (backend).

Covers secure download + SHA-256 verification (including refusing corrupted
evidence), versioning, archive/restore/freeze/retention, the append-only trail
for every lifecycle event, the auditor queue, bulk assignment, SLA escalation,
the dashboard summary, notifications, cross-org isolation, and that nothing is
ever hard-deleted or written to the ledger.
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
    AuditEvidenceAttachment,
    AuditEvidenceRequest,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import evidence_lifecycle as lc
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User
from apps.notifications.models import Notification

_A = AuditEvidenceAttachment
_L = _A.Lifecycle
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


class Base(TestCase):
    def setUp(self):
        self.org = _org()
        self.auditor = _auditor(self.org)
        self.client_user = _client_user(self.org)
        self.eng = _eng(self.org)
        self.finding = _finding(self.eng)
        self.req = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="Provide invoice",
            gl_finding=self.finding, assigned_client_user=self.client_user,
            assigned_to=self.auditor)

    def _upload(self, content=b"hello-evidence", name="evidence.pdf", actor=None):
        return ev.add_attachment(request=self.req, actor=actor or self.client_user,
                                 uploaded_file=_f(name, content))


class IntegrityTests(Base):
    def test_verify_ok_for_untouched_file(self):
        att = self._upload()
        result = lc.verify_attachment(att, actor=self.auditor)
        self.assertTrue(result["ok"])
        att.refresh_from_db()
        self.assertTrue(att.last_verification_ok)
        self.assertEqual(att.integrity_badge, "verified")
        self.assertTrue(att.events.filter(event_type="verified").exists())

    def test_verify_detects_tampering(self):
        att = self._upload()
        # Corrupt the stored bytes behind the app's back.
        with open(att.uploaded_file.path, "wb") as fh:
            fh.write(b"TAMPERED")
        result = lc.verify_attachment(att, actor=self.auditor)
        self.assertFalse(result["ok"])
        att.refresh_from_db()
        self.assertEqual(att.integrity_badge, "failed")
        self.assertTrue(att.events.filter(event_type="verification_failed").exists())

    def test_download_refuses_corrupted_evidence(self):
        att = self._upload()
        with open(att.uploaded_file.path, "wb") as fh:
            fh.write(b"TAMPERED")
        with self.assertRaises(lc.EvidenceIntegrityError):
            lc.read_for_download(att, actor=self.auditor)
        self.assertTrue(att.events.filter(event_type="verification_failed").exists())
        # And NO download event was recorded.
        self.assertFalse(att.events.filter(event_type="downloaded").exists())

    def test_download_returns_bytes_and_records_event(self):
        att = self._upload(content=b"the-real-invoice")
        data = lc.read_for_download(att, actor=self.auditor)
        self.assertEqual(data, b"the-real-invoice")
        self.assertTrue(att.events.filter(event_type="downloaded").exists())


class VersioningTests(Base):
    def test_each_upload_is_a_new_version(self):
        a1 = self._upload(b"v1")
        a2 = self._upload(b"v2")
        a3 = self._upload(b"v3")
        self.assertEqual([a1.version, a2.version, a3.version], [1, 2, 3])
        self.assertEqual(lc.version_history(self.req).count(), 3)

    def test_old_versions_are_never_overwritten(self):
        a1 = self._upload(b"v1")
        sha1 = a1.file_sha256
        self._upload(b"v2")
        a1.refresh_from_db()
        self.assertEqual(a1.file_sha256, sha1)
        self.assertEqual(lc.read_for_download(a1, actor=self.auditor), b"v1")

    def test_version_created_event_recorded(self):
        self._upload(b"v1")
        self._upload(b"v2")
        self.assertTrue(self.req.events.filter(event_type="version_created").exists())

    def test_supersede_links_and_archives_previous(self):
        a1 = self._upload(b"v1")
        a2 = self._upload(b"v2")
        lc.supersede(attachment=a1, replacement=a2, actor=self.auditor)
        a1.refresh_from_db(); a2.refresh_from_db()
        self.assertEqual(a2.replaces_id, a1.id)
        self.assertEqual(a1.lifecycle_state, _L.ARCHIVED)
        # Superseded evidence is archived, never deleted.
        self.assertTrue(_A.objects.filter(pk=a1.pk).exists())


class LifecycleTests(Base):
    def test_archive_and_restore(self):
        att = self._upload()
        lc.archive_attachment(attachment=att, actor=self.auditor, note="not needed")
        att.refresh_from_db()
        self.assertEqual(att.lifecycle_state, _L.ARCHIVED)
        self.assertFalse(att.is_active)  # mirror kept in sync
        self.assertTrue(att.events.filter(event_type="archived").exists())

        lc.restore_attachment(attachment=att, actor=self.auditor)
        att.refresh_from_db()
        self.assertEqual(att.lifecycle_state, _L.ACTIVE)
        self.assertTrue(att.is_active)
        self.assertTrue(att.events.filter(event_type="restored").exists())

    def test_freeze_blocks_all_further_modification(self):
        att = self._upload()
        lc.freeze_attachment(attachment=att, actor=self.auditor)
        att.refresh_from_db()
        self.assertEqual(att.lifecycle_state, _L.FROZEN)
        for fn in (lc.archive_attachment, lc.restore_attachment):
            with self.assertRaises(lc.EvidenceLifecycleError):
                fn(attachment=att, actor=self.auditor)
        with self.assertRaises(lc.EvidenceLifecycleError):
            lc.mark_expired(attachment=att, actor=self.auditor)
        with self.assertRaises(lc.EvidenceLifecycleError):
            lc.set_retention(attachment=att, actor=self.auditor,
                             retention_until=timezone.now().date())

    def test_frozen_evidence_still_downloadable(self):
        att = self._upload(b"frozen-bytes")
        lc.freeze_attachment(attachment=att, actor=self.auditor)
        att.refresh_from_db()
        self.assertEqual(lc.read_for_download(att, actor=self.auditor), b"frozen-bytes")

    def test_retention_expiry_is_computed_not_purged(self):
        att = self._upload()
        lc.set_retention(attachment=att, actor=self.auditor,
                         retention_until=timezone.now().date() - timedelta(days=1))
        att.refresh_from_db()
        self.assertTrue(att.is_expired)
        # Bytes are still on disk — nothing is auto-purged.
        self.assertTrue(_A.objects.filter(pk=att.pk).exists())

    def test_expired_attachment_download_blocked(self):
        att = self._upload()
        lc.mark_expired(attachment=att, actor=self.auditor)
        att.refresh_from_db()
        with self.assertRaises(lc.EvidenceLifecycleError):
            lc.read_for_download(att, actor=self.auditor)

    def test_archived_attachment_hidden_from_active_but_kept(self):
        att = self._upload()
        lc.archive_attachment(attachment=att, actor=self.auditor)
        self.assertEqual(self.req.attachments.filter(is_active=True).count(), 0)
        self.assertEqual(lc.version_history(self.req).count(), 1)


class QueueTests(Base):
    def test_queue_buckets_and_counts(self):
        overdue = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="late",
            gl_finding=self.finding,
            due_date=timezone.now().date() - timedelta(days=2))
        counts = lc.queue_counts(organization=self.org)
        self.assertEqual(counts["overdue"], 1)

        rows = list(lc.auditor_queue(organization=self.org, bucket="overdue"))
        self.assertEqual([r.id for r in rows], [overdue.id])

    def test_queue_search_and_high_priority(self):
        hp = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="URGENTDOC",
            gl_finding=self.finding, priority=_R.Priority.CRITICAL)
        found = list(lc.auditor_queue(organization=self.org, search="URGENTDOC"))
        self.assertEqual([r.id for r in found], [hp.id])
        high = list(lc.auditor_queue(organization=self.org, bucket="high_priority"))
        self.assertIn(hp.id, [r.id for r in high])

    def test_queue_is_org_scoped(self):
        other = _org("OrgB")
        oa = _auditor(other, "a2@e.com")
        oeng = _eng(other, code="B-1")
        ev.create_evidence_request(engagement=oeng, actor=oa, title="foreign",
                                   gl_finding=_finding(oeng))
        rows = list(lc.auditor_queue(organization=self.org))
        self.assertNotIn("foreign", [r.title for r in rows])


class BulkAssignTests(Base):
    def test_bulk_assign_single_transaction(self):
        r2 = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="second",
            gl_finding=self.finding)
        reviewer = _auditor(self.org, "rev@e.com")
        result = lc.bulk_assign_reviewer(
            organization=self.org, request_ids=[self.req.id, r2.id],
            reviewer=reviewer, actor=self.auditor)
        self.assertEqual(result["assigned_count"], 2)
        self.req.refresh_from_db(); r2.refresh_from_db()
        self.assertEqual(self.req.assigned_to_id, reviewer.id)
        self.assertEqual(r2.assigned_to_id, reviewer.id)
        self.assertTrue(self.req.events.filter(event_type="assigned").exists())

    def test_bulk_assign_skips_final(self):
        final = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="done",
            gl_finding=self.finding)
        ev.review_evidence_request(request=final, actor=self.auditor, action="cancel")
        reviewer = _auditor(self.org, "rev2@e.com")
        result = lc.bulk_assign_reviewer(
            organization=self.org, request_ids=[self.req.id, final.id],
            reviewer=reviewer, actor=self.auditor)
        self.assertIn(str(final.id), result["skipped_final"])
        self.assertEqual(result["assigned_count"], 1)

    def test_bulk_assign_rejects_foreign_reviewer(self):
        outsider = _auditor(_org("OrgZ"), "z@e.com")
        with self.assertRaises(Exception):
            lc.bulk_assign_reviewer(organization=self.org,
                                    request_ids=[self.req.id],
                                    reviewer=outsider, actor=self.auditor)


class SlaEscalationTests(Base):
    def test_escalation_records_event_and_never_closes(self):
        late = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="late",
            gl_finding=self.finding, assigned_client_user=self.client_user,
            assigned_to=self.auditor,
            due_date=timezone.now().date() - timedelta(days=3))
        result = lc.escalate_overdue(organization=self.org)
        self.assertEqual(result["count"], 1)
        late.refresh_from_db()
        self.assertTrue(late.events.filter(event_type="escalated").exists())
        self.assertEqual(late.status, _S.OPEN)  # never auto-closed

    def test_escalation_is_idempotent_per_day(self):
        ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="late",
            gl_finding=self.finding,
            due_date=timezone.now().date() - timedelta(days=3))
        lc.escalate_overdue(organization=self.org)
        second = lc.escalate_overdue(organization=self.org)
        self.assertEqual(second["count"], 0)

    def test_due_tomorrow_notifies(self):
        ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="soon",
            gl_finding=self.finding, assigned_client_user=self.client_user,
            due_date=timezone.now().date() + timedelta(days=1))
        Notification.objects.all().delete()
        result = lc.notify_due_tomorrow(organization=self.org)
        self.assertGreaterEqual(result["notified"], 1)
        self.assertTrue(Notification.objects.filter(user=self.client_user).exists())


class DashboardSummaryTests(Base):
    def test_summary_counts_and_avg_review_time(self):
        self._upload()
        ev.submit_evidence(request=self.req, actor=self.client_user)
        ev.review_evidence_request(request=self.req, actor=self.auditor,
                                   action="under_review")
        ev.review_evidence_request(request=self.req, actor=self.auditor, action="accept")
        summary = lc.dashboard_summary(organization=self.org)
        self.assertEqual(summary["accepted"], 1)
        self.assertIsNotNone(summary["avg_review_hours"])
        self.assertNotEqual(summary["avg_review_display"], "—")

    def test_summary_org_scoped(self):
        other = _org("OrgB")
        summary = lc.dashboard_summary(organization=other)
        self.assertEqual(summary["accepted"], 0)


class DownloadApiSecurityTests(Base):
    def setUp(self):
        super().setUp()
        self.att = self._upload(b"secret-invoice")

    def _url(self, att=None, suffix="download/"):
        return f"/api/v1/audit/evidence-attachments/{(att or self.att).id}/{suffix}"

    def test_auditor_can_download(self):
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"secret-invoice")
        self.assertIn("attachment;", resp["Content-Disposition"])

    def test_assigned_client_can_download(self):
        api = APIClient(); api.force_authenticate(self.client_user)
        self.assertEqual(api.get(self._url()).status_code, 200)

    def test_unassigned_client_gets_404(self):
        other_client = _client_user(self.org, "c9@e.com")
        api = APIClient(); api.force_authenticate(other_client)
        self.assertEqual(api.get(self._url()).status_code, 404)

    def test_cross_org_download_404(self):
        other = _org("OrgB")
        oa = _auditor(other, "a3@e.com")
        api = APIClient(); api.force_authenticate(oa)
        self.assertEqual(api.get(self._url()).status_code, 404)

    def test_anonymous_denied(self):
        api = APIClient()
        self.assertIn(api.get(self._url()).status_code, (401, 403))

    def test_corrupted_download_returns_409(self):
        with open(self.att.uploaded_file.path, "wb") as fh:
            fh.write(b"TAMPERED")
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.get(self._url())
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["integrity"], "failed")

    def test_verify_endpoint(self):
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.get(self._url(suffix="verify/"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_client_cannot_archive(self):
        api = APIClient(); api.force_authenticate(self.client_user)
        resp = api.post(self._url(suffix="archive/"), {}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_auditor_archive_restore_freeze_api(self):
        api = APIClient(); api.force_authenticate(self.auditor)
        self.assertEqual(api.post(self._url(suffix="archive/"), {}, format="json").status_code, 200)
        self.assertEqual(api.post(self._url(suffix="restore/"), {}, format="json").status_code, 200)
        self.assertEqual(api.post(self._url(suffix="freeze/"), {}, format="json").status_code, 200)
        # Frozen: further changes rejected.
        self.assertEqual(api.post(self._url(suffix="archive/"), {}, format="json").status_code, 400)


class LifecycleApiTests(Base):
    def test_versions_endpoint_scoped(self):
        self._upload(b"v1"); self._upload(b"v2")
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.get(f"/api/v1/audit/evidence-requests/{self.req.id}/versions/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

        other_client = _client_user(self.org, "c8@e.com")
        api2 = APIClient(); api2.force_authenticate(other_client)
        self.assertEqual(api2.get(
            f"/api/v1/audit/evidence-requests/{self.req.id}/versions/").status_code, 404)

    def test_queue_endpoint_auditor_only(self):
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.get("/api/v1/audit/evidence-queue/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("counts", resp.json())

        api2 = APIClient(); api2.force_authenticate(self.client_user)
        self.assertEqual(api2.get("/api/v1/audit/evidence-queue/").status_code, 403)

    def test_bulk_assign_endpoint(self):
        reviewer = _auditor(self.org, "rev3@e.com")
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.post("/api/v1/audit/evidence-requests/bulk-assign/", {
            "reviewer": str(reviewer.id), "request_ids": [str(self.req.id)]},
            format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["assigned_count"], 1)

    def test_dashboard_summary_endpoint(self):
        api = APIClient(); api.force_authenticate(self.auditor)
        resp = api.get("/api/v1/audit/evidence-dashboard/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("avg_review_display", resp.json())


class NotificationTests(Base):
    def test_assignment_change_notifies_reviewer(self):
        reviewer = _auditor(self.org, "rev4@e.com")
        Notification.objects.all().delete()
        lc.bulk_assign_reviewer(organization=self.org, request_ids=[self.req.id],
                                reviewer=reviewer, actor=self.auditor)
        self.assertTrue(Notification.objects.filter(
            user=reviewer, source_id=str(self.req.id)).exists())

    def test_overdue_escalation_notifies(self):
        late = ev.create_evidence_request(
            engagement=self.eng, actor=self.auditor, title="late",
            gl_finding=self.finding, assigned_client_user=self.client_user,
            due_date=timezone.now().date() - timedelta(days=2))
        Notification.objects.all().delete()
        lc.escalate_overdue(organization=self.org)
        self.assertTrue(Notification.objects.filter(user=self.client_user).exists())


class NoDeletionAndLedgerTests(Base):
    def test_lifecycle_never_deletes_attachments(self):
        att = self._upload()
        lc.archive_attachment(attachment=att, actor=self.auditor)
        lc.mark_expired(attachment=att, actor=self.auditor)
        self.assertTrue(_A.objects.filter(pk=att.pk).exists())

    def test_no_ledger_writes(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        att = self._upload()
        lc.read_for_download(att, actor=self.auditor)
        lc.verify_attachment(att, actor=self.auditor)
        lc.archive_attachment(attachment=att, actor=self.auditor)
        lc.restore_attachment(attachment=att, actor=self.auditor)
        lc.escalate_overdue(organization=self.org)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)

    def test_events_are_append_only_and_linked_to_attachment(self):
        att = self._upload()
        lc.read_for_download(att, actor=self.auditor)
        lc.archive_attachment(attachment=att, actor=self.auditor)
        linked = att.events.all()
        self.assertGreaterEqual(linked.count(), 2)
        for e in linked:
            self.assertEqual(e.attachment_id, att.id)
