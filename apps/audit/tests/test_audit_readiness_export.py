"""TADGEEG-FIN-AUDIT-5D — Audit Readiness export tests.

Covers the safe export layer over the 5A AuditReadinessWorkpaper:
  * structured export payload (all required sections + disclaimer);
  * ABSENCE of formal-opinion wording (EN + AR) in every format;
  * suggested direction is always "subject to auditor review";
  * source workpaper / SAD / items / findings are NOT modified by export;
  * JSON + HTML export render;
  * ISA-700 draft is sourced from the workpaper and is not a formal opinion;
  * API export is org-scoped, cross-org denied, and permission-gated;
  * no writes to ledger tables.
"""
from __future__ import annotations

import json
from decimal import Decimal

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
from apps.audit.services import audit_readiness_export as export
from apps.audit.services import audit_readiness_workpaper as readiness
from apps.authentication.models import Organization, User

_W = AuditReadinessWorkpaper
_MR = AuditDifferenceItem.ManagementResponse
_FS = GeneralLedgerRiskFinding.Status

PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}

# Phrases that would imply the system issued a formal opinion — must NOT appear.
UNSAFE_EN = [
    "in our opinion", "present fairly", "opinion issued",
    "unqualified opinion issued", "qualified opinion issued",
    "adverse opinion issued", "disclaimer issued",
]
UNSAFE_AR = ["في رأينا", "تعرض بعدالة", "تم إصدار رأي", "رأي صادر"]


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _user(org, email="a@e.com", role=None):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="T",
        role=role or User.Role.ADMIN, organization=org)


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


def _workpaper(org=None, amount=150000, *, unadjusted=True):
    org = org or _org()
    eng = _eng(org)
    imp = _imp(eng)
    _finding(eng, imp, amount)
    s = sad.recalculate_for_engagement(eng)
    if unadjusted:
        it = s.items.first()
        it.management_response_status = _MR.UNADJUSTED
        it.save(update_fields=["management_response_status"])
    wp = readiness.generate_for_engagement(eng)
    return org, eng, s, wp


class PayloadTests(TestCase):
    def setUp(self):
        self.org, self.eng, self.sad, self.wp = _workpaper()

    def test_payload_has_required_sections(self):
        p = export.build_export_payload(self.wp)
        for key in ("engagement", "sad_summary", "readiness_conclusion",
                    "suggested_direction", "management_response_summary",
                    "proposed_adjustment_summary", "unadjusted_summary",
                    "difference_counts", "open_evidence_requests",
                    "materiality", "disclaimer", "workpaper"):
            self.assertIn(key, p, f"missing export section: {key}")
        self.assertEqual(p["engagement"]["engagement_code"], self.eng.engagement_code)
        self.assertEqual(p["is_formal_opinion"], False)
        self.assertEqual(p["subject_to_auditor_review"], True)

    def test_disclaimer_present(self):
        p = export.build_export_payload(self.wp)
        self.assertIn("does not constitute a formal audit opinion", p["disclaimer"])
        self.assertIn("licensed auditor", p["disclaimer"].lower())

    def test_direction_subject_to_auditor_review(self):
        p = export.build_export_payload(self.wp)
        self.assertTrue(p["suggested_direction"]["subject_to_auditor_review"])
        self.assertIn("subject to auditor review",
                      p["suggested_direction"]["banner_en"].lower())
        self.assertIn("subject_to_auditor_review",
                      p["suggested_direction"]["code"])

    def test_no_unsafe_phrases_in_payload(self):
        blob = json.dumps(export.build_export_payload(self.wp), default=str)
        low = blob.lower()
        for phrase in UNSAFE_EN:
            self.assertNotIn(phrase, low, f"unsafe EN phrase: {phrase}")
        for phrase in UNSAFE_AR:
            self.assertNotIn(phrase, blob, f"unsafe AR phrase: {phrase}")

    def test_isa700_draft_sourced_from_workpaper(self):
        p = export.build_export_payload(self.wp)
        draft = p["isa700_draft"]
        self.assertEqual(draft["source"], "audit_readiness_workpaper")
        self.assertEqual(draft["source_workpaper_id"], str(self.wp.id))
        self.assertFalse(draft["is_formal_opinion"])
        self.assertTrue(draft["subject_to_auditor_review"])
        self.assertIn("subject to auditor review",
                      draft["opinion_paragraph"]["opinion_en"].lower())
        # Possible-modified workpaper direction → 'qualified' compat code.
        self.assertEqual(draft["opinion_type"], "qualified")


class ImmutabilityTests(TestCase):
    def setUp(self):
        self.org, self.eng, self.sad, self.wp = _workpaper()

    def test_export_does_not_modify_workpaper_or_sad(self):
        before_wp = (self.wp.status, self.wp.readiness_conclusion,
                     self.wp.suggested_opinion_direction, self.wp.updated_at)
        before_items = list(self.sad.items.values_list(
            "id", "amount_impact", "management_response_status"))
        before_sad = (self.sad.conclusion_status, self.sad.total_absolute_impact)

        export.build_export_payload(self.wp)
        export.render_html(self.wp)

        self.wp.refresh_from_db(); self.sad.refresh_from_db()
        self.assertEqual(
            (self.wp.status, self.wp.readiness_conclusion,
             self.wp.suggested_opinion_direction, self.wp.updated_at), before_wp)
        self.assertEqual(
            list(self.sad.items.values_list("id", "amount_impact",
                                            "management_response_status")),
            before_items)
        self.assertEqual(
            (self.sad.conclusion_status, self.sad.total_absolute_impact), before_sad)


class HtmlExportTests(TestCase):
    def setUp(self):
        self.org, self.eng, self.sad, self.wp = _workpaper()

    def test_html_renders_with_disclaimer_and_labels(self):
        html = export.render_html(self.wp)
        self.assertIn("Audit Readiness Report", html)
        self.assertIn("Subject to Auditor Review", html)
        self.assertIn("Licensed Auditor Approval", html)
        self.assertIn("does not constitute a formal audit opinion", html)

    def test_html_has_no_unsafe_phrases(self):
        html = export.render_html(self.wp)
        low = html.lower()
        for phrase in UNSAFE_EN:
            self.assertNotIn(phrase, low, f"unsafe EN phrase in HTML: {phrase}")
        for phrase in UNSAFE_AR:
            self.assertNotIn(phrase, html, f"unsafe AR phrase in HTML: {phrase}")


class ApiExportTests(TestCase):
    def setUp(self):
        self.org, self.eng, self.sad, self.wp = _workpaper(_org("OrgA"))
        self.user = _user(self.org)
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def test_json_export_by_engagement(self):
        resp = self.client.get(
            f"/api/v1/audit/engagements/{self.eng.id}/audit-readiness/export/")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertFalse(data["is_formal_opinion"])
        self.assertIn("does not constitute a formal audit opinion", data["disclaimer"])

    def test_json_export_by_workpaper_id(self):
        resp = self.client.get(
            f"/api/v1/audit/audit-readiness/{self.wp.id}/export/?format=json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["subject_to_auditor_review"])

    def test_html_export(self):
        resp = self.client.get(
            f"/api/v1/audit/audit-readiness/{self.wp.id}/export/?format=html")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp["Content-Type"])
        self.assertIn(b"Audit Readiness Report", resp.content)

    def test_pdf_export(self):
        try:
            import weasyprint  # noqa: F401
        except Exception:
            self.skipTest("WeasyPrint not available")
        resp = self.client.get(
            f"/api/v1/audit/audit-readiness/{self.wp.id}/export/?format=pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_export_other_org_denied(self):
        _, other_eng, _, other_wp = _workpaper(_org("OrgB"), amount=1000, unadjusted=False)
        # By engagement path.
        r1 = self.client.get(
            f"/api/v1/audit/engagements/{other_eng.id}/audit-readiness/export/")
        self.assertEqual(r1.status_code, 404)
        # By workpaper id path.
        r2 = self.client.get(
            f"/api/v1/audit/audit-readiness/{other_wp.id}/export/")
        self.assertEqual(r2.status_code, 404)

    def test_export_requires_auditor_role(self):
        junior = _user(self.org, email="junior@e.com", role=User.Role.JUNIOR_AUDITOR)
        c = APIClient(); c.force_authenticate(junior)
        resp = c.get(f"/api/v1/audit/audit-readiness/{self.wp.id}/export/")
        self.assertEqual(resp.status_code, 403)


class LedgerIsolationTests(TestCase):
    def test_export_writes_nothing_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        org, eng, s, wp = _workpaper()
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        export.build_export_payload(wp)
        export.render_html(wp)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
