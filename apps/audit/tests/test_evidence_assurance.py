"""TADGEEG-FIN-AUDIT-6D — Evidence assurance & reporting tests (backend).

Covers the deterministic integrity sweep, the exception report, coverage
analysis, the immutable evidence index, engagement retention policy (metadata
only), readiness-export integration (informational, conclusion unchanged),
the assurance dashboard, auditor-only notifications, permissions, cross-org
isolation and the guarantee that nothing is deleted or written to the ledger.
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
    AuditEvidenceRetentionPolicy,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import audit_difference_summary as sad
from apps.audit.services import audit_readiness_export as export
from apps.audit.services import audit_readiness_workpaper as readiness
from apps.audit.services import evidence_assurance as assurance
from apps.audit.services import evidence_lifecycle as lc
from apps.audit.services import evidence_request as ev
from apps.authentication.models import Organization, User
from apps.notifications.models import Notification

_A = AuditEvidenceAttachment
_L = _A.Lifecycle
_VR = _A.VerificationResult
_R = AuditEvidenceRequest
_P = AuditEvidenceRetentionPolicy
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


def _finding(eng, *, status=_FS.NEEDS_EVIDENCE, code="GL-RISK-DESC", amount="20000"):
    imp = GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv")
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code=code, risk_title="t",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal(amount), account_code="6000", status=status)


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

    def _upload(self, content=b"hello-evidence", request=None):
        return ev.add_attachment(request=request or self.req, actor=self.client_user,
                                 uploaded_file=_f(content=content))

    def _accept(self, request=None):
        req = request or self.req
        ev.submit_evidence(request=req, actor=self.client_user)
        ev.review_evidence_request(request=req, actor=self.auditor, action="under_review")
        ev.review_evidence_request(request=req, actor=self.auditor, action="accept")
        return req


class IntegritySweepTests(Base):
    def test_sweep_marks_clean_attachment_ok(self):
        att = self._upload()
        stats = assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        self.assertEqual(stats["checked"], 1)
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(stats["failed"], 0)
        att.refresh_from_db()
        self.assertEqual(att.verification_result, _VR.OK)
        self.assertIsNotNone(att.verification_duration_ms)
        self.assertEqual(att.verification_error, "")

    def test_sweep_detects_hash_mismatch_and_never_repairs(self):
        att = self._upload(b"original")
        with open(att.uploaded_file.path, "wb") as fh:
            fh.write(b"TAMPERED")
        stats = assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        self.assertEqual(stats["failed"], 1)
        att.refresh_from_db()
        self.assertEqual(att.verification_result, _VR.HASH_MISMATCH)
        self.assertTrue(att.verification_error)
        # File contents are NOT repaired.
        with open(att.uploaded_file.path, "rb") as fh:
            self.assertEqual(fh.read(), b"TAMPERED")

    def test_sweep_detects_missing_file(self):
        att = self._upload()
        import os
        os.remove(att.uploaded_file.path)
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        att.refresh_from_db()
        self.assertIn(att.verification_result, (_VR.MISSING_FILE, _VR.UNREADABLE))
        self.assertEqual(att.integrity_badge, "failed")

    def test_sweep_skips_archived_attachments(self):
        att = self._upload()
        lc.archive_attachment(attachment=att, actor=self.auditor)
        stats = assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        self.assertEqual(stats["checked"], 0)

    def test_sweep_is_org_scoped(self):
        self._upload()
        other = _org("OrgB")
        oa, oc = _auditor(other, "a2@e.com"), _client_user(other, "c2@e.com")
        oeng = _eng(other, code="B-1")
        oreq = ev.create_evidence_request(engagement=oeng, actor=oa, title="x",
                                          gl_finding=_finding(oeng),
                                          assigned_client_user=oc)
        ev.add_attachment(request=oreq, actor=oc, uploaded_file=_f())
        stats = assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        self.assertEqual(stats["checked"], 1)

    def test_sweep_records_append_only_events(self):
        att = self._upload()
        before = att.events.count()
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        self.assertGreater(att.events.count(), before)


class IntegrityReportTests(Base):
    def test_report_buckets_and_statistics(self):
        good = self._upload(b"good")
        bad = self._upload(b"bad")
        with open(bad.uploaded_file.path, "wb") as fh:
            fh.write(b"TAMPERED")
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)

        report = assurance.integrity_exception_report(organization=self.org)
        self.assertEqual(report["counts"]["hash_mismatch"], 1)
        self.assertEqual(report["statistics"]["verified"], 1)
        self.assertEqual(report["statistics"]["failed"], 1)
        self.assertEqual(report["statistics"]["integrity_percent"], 50.0)
        self.assertIn("no evidence was modified", report["note"].lower())

    def test_report_includes_lifecycle_buckets(self):
        a1 = self._upload(b"a")
        a2 = self._upload(b"b")
        lc.archive_attachment(attachment=a1, actor=self.auditor)
        lc.freeze_attachment(attachment=a2, actor=self.auditor)
        report = assurance.integrity_exception_report(organization=self.org)
        self.assertEqual(report["counts"]["archived"], 1)
        self.assertEqual(report["counts"]["frozen"], 1)

    def test_pending_verification_bucket(self):
        self._upload()
        report = assurance.integrity_exception_report(organization=self.org)
        self.assertEqual(report["counts"]["pending_verification"], 1)

    def test_report_org_scoped(self):
        self._upload()
        other = _org("OrgC")
        report = assurance.integrity_exception_report(organization=other)
        self.assertEqual(report["statistics"]["total"], 0)


class CoverageTests(Base):
    def test_coverage_zero_when_nothing_accepted(self):
        self._upload()
        cov = assurance.evidence_coverage(organization=self.org)
        row = next(r for r in cov["findings"] if r["id"] == str(self.finding.id))
        self.assertEqual(row["required"], 1)
        self.assertEqual(row["uploaded"], 1)
        self.assertEqual(row["accepted"], 0)
        self.assertEqual(row["coverage_percent"], 0.0)
        self.assertEqual(row["coverage_status"], "none")

    def test_coverage_complete_when_accepted(self):
        self._upload()
        self._accept()
        cov = assurance.evidence_coverage(organization=self.org)
        row = next(r for r in cov["findings"] if r["id"] == str(self.finding.id))
        self.assertEqual(row["coverage_percent"], 100.0)
        self.assertEqual(row["coverage_status"], "complete")

    def test_coverage_partial_50_percent(self):
        self._upload()
        self._accept()
        # Second request on the SAME finding, left open → 1 of 2 accepted.
        ev.create_evidence_request(engagement=self.eng, actor=self.auditor,
                                   title="second", gl_finding=self.finding)
        cov = assurance.evidence_coverage(organization=self.org)
        row = next(r for r in cov["findings"] if r["id"] == str(self.finding.id))
        self.assertEqual(row["required"], 2)
        self.assertEqual(row["coverage_percent"], 50.0)
        self.assertEqual(row["coverage_status"], "partial")

    def test_finding_without_requests_is_no_requests(self):
        other_finding = _finding(self.eng, code="GL-OTHER")
        cov = assurance.evidence_coverage(organization=self.org)
        row = next(r for r in cov["findings"] if r["id"] == str(other_finding.id))
        self.assertEqual(row["required"], 0)
        self.assertEqual(row["coverage_status"], "no_requests")

    def test_rejected_and_pending_counted(self):
        self._upload()
        ev.submit_evidence(request=self.req, actor=self.client_user)
        ev.review_evidence_request(request=self.req, actor=self.auditor,
                                   action="under_review")
        ev.review_evidence_request(request=self.req, actor=self.auditor,
                                   action="reject", note="insufficient")
        cov = assurance.evidence_coverage(organization=self.org)
        row = next(r for r in cov["findings"] if r["id"] == str(self.finding.id))
        self.assertEqual(row["rejected"], 1)
        self.assertEqual(row["coverage_percent"], 0.0)

    def test_sad_item_coverage(self):
        _finding(self.eng, status=_FS.ACCEPTED, code="GL-ACC", amount="30000")
        summary = sad.recalculate_for_engagement(self.eng)
        item = summary.items.first()
        req = ev.create_evidence_request(engagement=self.eng, actor=self.auditor,
                                         title="SAD support", sad_item=item,
                                         assigned_client_user=self.client_user)
        self._upload(request=req)
        self._accept(req)
        cov = assurance.evidence_coverage(organization=self.org)
        row = next(r for r in cov["sad_items"] if r["id"] == str(item.id))
        self.assertEqual(row["coverage_percent"], 100.0)

    def test_coverage_org_scoped(self):
        self._upload()
        other = _org("OrgD")
        cov = assurance.evidence_coverage(organization=other)
        self.assertEqual(cov["summary"]["total_required"], 0)


class EvidenceIndexTests(Base):
    def test_index_rows_have_required_columns_and_no_urls(self):
        self._upload()
        self._accept()
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        index = assurance.evidence_index(organization=self.org)
        self.assertEqual(len(index), 1)
        row = index[0]
        for key in ("evidence_number", "finding", "sad_item", "filename", "version",
                    "sha256", "integrity", "status", "reviewer", "review_date",
                    "retention_until", "lifecycle_state"):
            self.assertIn(key, row)
        self.assertTrue(row["evidence_number"].startswith("EV-"))
        # No download URLs anywhere in the index.
        blob = " ".join(str(v) for v in row.values())
        self.assertNotIn("/download/", blob)
        self.assertNotIn("http", blob)

    def test_index_includes_archived_versions(self):
        a1 = self._upload(b"v1")
        self._upload(b"v2")
        lc.archive_attachment(attachment=a1, actor=self.auditor)
        index = assurance.evidence_index(organization=self.org)
        self.assertEqual(len(index), 2)

    def test_index_org_scoped(self):
        self._upload()
        self.assertEqual(assurance.evidence_index(organization=_org("OrgE")), [])


class RetentionPolicyTests(Base):
    def test_set_and_apply_7_years(self):
        att = self._upload()
        policy = assurance.set_retention_policy(
            engagement=self.eng, actor=self.auditor, policy=_P.Policy.YEARS_7,
            reason="statutory")
        self.assertEqual(policy.years, 7)
        result = assurance.apply_retention_policy(policy_obj=policy, actor=self.auditor)
        self.assertEqual(result["marked"], 1)
        att.refresh_from_db()
        self.assertEqual(att.retention_until.year, att.uploaded_at.year + 7)

    def test_forever_policy_clears_expiry(self):
        att = self._upload()
        policy = assurance.set_retention_policy(
            engagement=self.eng, actor=self.auditor, policy=_P.Policy.FOREVER)
        self.assertIsNone(policy.years)
        assurance.apply_retention_policy(policy_obj=policy, actor=self.auditor)
        att.refresh_from_db()
        self.assertIsNone(att.retention_until)

    def test_custom_years_requires_value(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            assurance.set_retention_policy(
                engagement=self.eng, actor=self.auditor, policy=_P.Policy.CUSTOM)

    def test_custom_years_applied(self):
        att = self._upload()
        policy = assurance.set_retention_policy(
            engagement=self.eng, actor=self.auditor, policy=_P.Policy.CUSTOM,
            custom_years=3)
        assurance.apply_retention_policy(policy_obj=policy, actor=self.auditor)
        att.refresh_from_db()
        self.assertEqual(att.retention_until.year, att.uploaded_at.year + 3)

    def test_apply_never_deletes_and_skips_frozen(self):
        att = self._upload()
        lc.freeze_attachment(attachment=att, actor=self.auditor)
        policy = assurance.set_retention_policy(
            engagement=self.eng, actor=self.auditor, policy=_P.Policy.YEARS_10)
        result = assurance.apply_retention_policy(policy_obj=policy, actor=self.auditor)
        self.assertEqual(result["skipped_frozen"], 1)
        self.assertTrue(_A.objects.filter(pk=att.pk).exists())
        self.assertIn("no evidence was deleted", result["note"].lower())

    def test_policy_is_one_per_engagement(self):
        assurance.set_retention_policy(engagement=self.eng, actor=self.auditor,
                                       policy=_P.Policy.YEARS_7)
        assurance.set_retention_policy(engagement=self.eng, actor=self.auditor,
                                       policy=_P.Policy.YEARS_10)
        self.assertEqual(_P.objects.filter(engagement=self.eng).count(), 1)


class ReadinessIntegrationTests(Base):
    def _workpaper(self):
        _finding(self.eng, status=_FS.ACCEPTED, code="GL-ACC2", amount="30000")
        sad.recalculate_for_engagement(self.eng)
        return readiness.generate_for_engagement(self.eng)

    def test_export_payload_includes_evidence_sections(self):
        self._upload()
        wp = self._workpaper()
        payload = export.build_export_payload(wp)
        self.assertIn("evidence_assurance", payload)
        self.assertIn("evidence_index", payload)
        ea = payload["evidence_assurance"]
        for key in ("coverage_percent", "integrity_summary", "pending_requests",
                    "open_reviews", "rejected_evidence", "expired_evidence",
                    "frozen_evidence"):
            self.assertIn(key, ea)
        self.assertTrue(ea["informational_only"])

    def test_evidence_does_not_change_readiness_conclusion(self):
        wp = self._workpaper()
        before = (wp.readiness_conclusion, wp.suggested_opinion_direction)
        self._upload()
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        export.build_export_payload(wp)
        wp.refresh_from_db()
        self.assertEqual((wp.readiness_conclusion, wp.suggested_opinion_direction), before)

    def test_export_can_omit_evidence(self):
        wp = self._workpaper()
        payload = export.build_export_payload(wp, include_evidence=False)
        self.assertNotIn("evidence_assurance", payload)

    def test_html_export_renders_evidence_and_stays_safe(self):
        self._upload()
        wp = self._workpaper()
        html = export.render_html(wp)
        self.assertIn("Evidence Assurance", html)
        self.assertIn("Evidence Index", html)
        self.assertNotIn("In our opinion", html)


class AssuranceDashboardTests(Base):
    def test_dashboard_aggregates(self):
        self._upload()
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        dash = assurance.assurance_dashboard(organization=self.org)
        self.assertEqual(dash["total"], 1)
        self.assertEqual(dash["verified"], 1)
        self.assertEqual(dash["integrity_percent"], 100.0)
        self.assertEqual(dash["verification_status"], "clean")
        self.assertIn("coverage_percent", dash)

    def test_dashboard_flags_failures(self):
        att = self._upload()
        with open(att.uploaded_file.path, "wb") as fh:
            fh.write(b"X")
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        dash = assurance.assurance_dashboard(organization=self.org)
        self.assertEqual(dash["verification_status"], "failures")

    def test_dashboard_org_scoped(self):
        self._upload()
        dash = assurance.assurance_dashboard(organization=_org("OrgF"))
        self.assertEqual(dash["total"], 0)


class NotificationTests(Base):
    def test_integrity_failure_notifies_auditor_not_client(self):
        att = self._upload()
        with open(att.uploaded_file.path, "wb") as fh:
            fh.write(b"TAMPERED")
        Notification.objects.all().delete()
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        self.assertTrue(Notification.objects.filter(user=self.auditor).exists())
        self.assertFalse(Notification.objects.filter(user=self.client_user).exists())

    def test_verification_completed_notifies_auditor(self):
        self._upload()
        Notification.objects.all().delete()
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        self.assertTrue(Notification.objects.filter(
            user=self.auditor, source_id="sweep").exists())
        self.assertFalse(Notification.objects.filter(user=self.client_user).exists())

    def test_coverage_below_threshold_notifies_auditor_only(self):
        self._upload()  # required=1, accepted=0 → 0% coverage
        Notification.objects.all().delete()
        result = assurance.check_coverage_threshold(organization=self.org)
        self.assertTrue(result["below_threshold"])
        self.assertTrue(Notification.objects.filter(
            user=self.auditor, source_id="coverage").exists())
        self.assertFalse(Notification.objects.filter(user=self.client_user).exists())

    def test_expired_evidence_notifies_auditor_only(self):
        att = self._upload()
        att.retention_until = timezone.now().date() - timedelta(days=1)
        att.save(update_fields=["retention_until"])
        Notification.objects.all().delete()
        result = assurance.notify_expired_evidence(organization=self.org)
        self.assertEqual(result["expired_count"], 1)
        self.assertTrue(Notification.objects.filter(
            user=self.auditor, source_id="retention").exists())
        self.assertFalse(Notification.objects.filter(user=self.client_user).exists())
        # Nothing purged.
        self.assertTrue(_A.objects.filter(pk=att.pk).exists())


class AssuranceApiTests(Base):
    def setUp(self):
        super().setUp()
        self._upload()
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_sweep_endpoint(self):
        resp = self.api.post("/api/v1/audit/evidence-assurance/sweep/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["checked"], 1)

    def test_integrity_report_endpoint(self):
        resp = self.api.get("/api/v1/audit/evidence-assurance/integrity-report/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("statistics", resp.json())

    def test_coverage_endpoint(self):
        resp = self.api.get("/api/v1/audit/evidence-assurance/coverage/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("summary", resp.json())

    def test_index_endpoint(self):
        resp = self.api.get("/api/v1/audit/evidence-assurance/index/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["index"]), 1)

    def test_dashboard_endpoint(self):
        resp = self.api.get("/api/v1/audit/evidence-assurance/dashboard/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("integrity_percent", resp.json())

    def test_retention_policy_endpoints(self):
        url = f"/api/v1/audit/engagements/{self.eng.id}/retention-policy/"
        self.assertIsNone(self.api.get(url).json()["policy"])
        resp = self.api.post(url, {"policy": "years_10", "apply": True}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["years"], 10)
        self.assertEqual(resp.json()["applied"]["marked"], 1)

    def test_client_denied_on_every_assurance_endpoint(self):
        api = APIClient(); api.force_authenticate(self.client_user)
        for url in ("/api/v1/audit/evidence-assurance/integrity-report/",
                    "/api/v1/audit/evidence-assurance/coverage/",
                    "/api/v1/audit/evidence-assurance/index/",
                    "/api/v1/audit/evidence-assurance/dashboard/"):
            self.assertEqual(api.get(url).status_code, 403, url)
        self.assertEqual(api.post("/api/v1/audit/evidence-assurance/sweep/", {},
                                  format="json").status_code, 403)

    def test_cross_org_engagement_404(self):
        other_eng = _eng(_org("OrgG"), code="G-1")
        resp = self.api.get(
            f"/api/v1/audit/engagements/{other_eng.id}/retention-policy/")
        self.assertEqual(resp.status_code, 404)

    def test_cross_org_filter_404(self):
        other_eng = _eng(_org("OrgH"), code="H-1")
        resp = self.api.get(
            f"/api/v1/audit/evidence-assurance/coverage/?engagement={other_eng.id}")
        self.assertEqual(resp.status_code, 404)


class NoLedgerWritesTests(Base):
    def test_assurance_never_writes_to_ledger_or_deletes(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        att = self._upload()
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        assurance.sweep_attachments(organization=self.org, actor=self.auditor)
        assurance.integrity_exception_report(organization=self.org)
        assurance.evidence_coverage(organization=self.org)
        assurance.evidence_index(organization=self.org)
        policy = assurance.set_retention_policy(
            engagement=self.eng, actor=self.auditor, policy=_P.Policy.YEARS_7)
        assurance.apply_retention_policy(policy_obj=policy, actor=self.auditor)
        assurance.assurance_dashboard(organization=self.org)

        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
        self.assertTrue(_A.objects.filter(pk=att.pk).exists())
        # The linked finding is untouched by assurance reporting.
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, _FS.NEEDS_EVIDENCE)
