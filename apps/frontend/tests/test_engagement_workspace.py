"""TADGEEG-FIN-AUDIT-8A — Engagement Workspace frontend tests.

The workspace surfaces existing 1A–7A capabilities in one hub. These tests
assert access control, organization scoping, the lifecycle rail, aggregation of
real data (GL findings, SAD, evidence, analytics, readiness, materiality), the
stage-change action, and cross-organization 404 — without touching any backend
logic those phases already own.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import (
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
    GeneralLedgerRow,
)
from apps.audit.services import audit_difference_summary as sad
from apps.audit.services import audit_readiness_workpaper as readiness
from apps.audit.services import evidence_request as ev
from apps.audit.services import journal_analytics as ja
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

_Eng = AuditEngagement
_FS = GeneralLedgerRiskFinding.Status
PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}
_SEQ = {"n": 0}


def _activate_subscription(org):
    if not Plan.objects.filter(code=PlanCode.BUSINESS).exists():
        call_command("seed_billing_plans", stdout=StringIO())
    svc = SubscriptionService()
    svc.activate_subscription(
        svc.create_pending_paid_subscription(org, Plan.objects.get(code=PlanCode.BUSINESS)))


def _org(name="Acme"):
    org = Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)
    _activate_subscription(org)
    return org


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
        organization=org, engagement_code=code, title="FY25 Statutory Audit",
        period_start="2025-01-01", period_end="2025-12-31", materiality=PROFILE,
        engagement_partner=None)


def _imp(eng):
    return GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv",
        period_end=datetime.date(2025, 12, 31))


def _finding(eng, imp, *, status=_FS.NEEDS_EVIDENCE, amount="20000"):
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-DESC", risk_title="t",
        risk_category=GeneralLedgerRiskFinding.Category.OTHER,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal(amount), account_code="6000", status=status)


def _row(imp, *, journal="JV-1", debit="500000", description=""):
    _SEQ["n"] += 1
    return GeneralLedgerRow.objects.create(
        import_batch=imp, engagement=imp.engagement, organization=imp.organization,
        row_number=_SEQ["n"], journal_number=journal,
        transaction_date=datetime.date(2025, 6, 10), account_code="6000",
        account_name="Acct", debit=Decimal(debit), credit=Decimal("0"),
        signed_amount=Decimal(debit), description=description)


class Base(TestCase):
    def setUp(self):
        self.org = _org()
        self.auditor = _auditor(self.org)
        self.eng = _eng(self.org)
        self.imp = _imp(self.eng)
        self.client.force_login(self.auditor)

    def _url(self, eng=None):
        return reverse("frontend:engagement_workspace", args=[(eng or self.eng).id])


class AccessTests(Base):
    def test_list_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("frontend:engagement_list"))
        self.assertEqual(resp.status_code, 302)

    def test_pages_denied_for_junior(self):
        self.client.force_login(_junior(self.org))
        self.assertEqual(self.client.get(reverse("frontend:engagement_list")).status_code, 403)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_pages_render_for_auditor(self):
        self.assertEqual(self.client.get(reverse("frontend:engagement_list")).status_code, 200)
        self.assertEqual(self.client.get(self._url()).status_code, 200)


class ListTests(Base):
    def test_list_shows_engagement_and_stage(self):
        resp = self.client.get(reverse("frontend:engagement_list"))
        self.assertContains(resp, "AUD-1")
        self.assertContains(resp, 'class="stg acceptance"')

    def test_list_stage_filter(self):
        resp = self.client.get(reverse("frontend:engagement_list"), {"stage": "reporting"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "AUD-1")  # engagement is in acceptance

    def test_list_excludes_other_org(self):
        other = _org("OrgB")
        _eng(other, code="OTHER-ENG")
        resp = self.client.get(reverse("frontend:engagement_list"))
        self.assertNotContains(resp, "OTHER-ENG")

    def test_g9_list_rows_bulk_open_counts_correct(self):
        # G9 — the bulk GL query returns correct per-engagement open counts.
        from apps.frontend.engagement_workspace_views import _list_rows
        e2 = _eng(self.org, code="AUD-2")
        _finding(self.eng, self.imp, status=_FS.NEEDS_EVIDENCE)
        _finding(self.eng, self.imp, status=_FS.ESCALATED)
        _finding(self.eng, self.imp, status=_FS.ACCEPTED)  # not "open"
        rows = _list_rows([self.eng, e2], self.org)
        by = {r["e"].id: r["overview"]["gl_findings"]["open"] for r in rows}
        self.assertEqual(by[self.eng.id], 2)   # candidate/needs_evidence/escalated only
        self.assertEqual(by[e2.id], 0)

    def test_g9_list_path_skips_heavy_overview_sections(self):
        # G9 — the list path must NOT fan out into the full ~15-section overview
        # (materiality/SAD/substantive/confirmations/risks/planning/analytics…).
        # It touches only what the list renders: open GL findings + assurance.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.frontend.engagement_workspace_views import _list_rows
        engs = [self.eng] + [_eng(self.org, code=f"AUD-{i}") for i in range(2, 6)]
        with CaptureQueriesContext(connection) as ctx:
            _list_rows(engs, self.org)
        sql = " ".join(q["sql"].lower() for q in ctx.captured_queries)
        # These overview sections are eliminated from the list path (the full
        # overview queried them per row; the light path does not touch them).
        for heavy in ("audit_assessed_risks", "audit_procedures",
                      "audit_substantive_test_items", "audit_engagement_planning_records"):
            self.assertNotIn(heavy, sql, f"list path must not query {heavy}")

    def test_g9_open_gl_findings_is_one_bulk_query(self):
        # The open-GL-findings count for ALL rows is a single grouped query
        # (isolated from the assurance service, which is called separately).
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.frontend.engagement_workspace_views import _list_rows
        from apps.audit.services import evidence_assurance as ea
        engs = [self.eng] + [_eng(self.org, code=f"AUD-{i}") for i in range(2, 6)]
        # Stub assurance so we measure only the list path's own GL aggregation.
        orig = ea.assurance_dashboard
        ea.assurance_dashboard = lambda **kw: {"coverage_percent": 0}
        try:
            with CaptureQueriesContext(connection) as ctx:
                _list_rows(engs, self.org)
        finally:
            ea.assurance_dashboard = orig
        gl_group = [q for q in ctx.captured_queries
                    if "gl_risk_finding" in q["sql"].lower() and "group by" in q["sql"].lower()]
        self.assertEqual(len(gl_group), 1, "open GL findings must be one bulk query for N rows")


class WorkspaceAggregationTests(Base):
    def test_lifecycle_rail_marks_current_stage(self):
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-current="acceptance"')
        self.assertContains(resp, 'step current')  # acceptance stage marked current

    def test_materiality_surfaced(self):
        resp = self.client.get(self._url())
        self.assertContains(resp, "100000")  # overall materiality from profile

    def test_gl_findings_counts_surfaced(self):
        _finding(self.eng, self.imp, status=_FS.NEEDS_EVIDENCE)
        _finding(self.eng, self.imp, status=_FS.ESCALATED)
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-sec="gl"')  # section always present

    def test_sad_surfaced(self):
        _finding(self.eng, self.imp, status=_FS.ACCEPTED, amount="30000")
        sad.recalculate_for_engagement(self.eng)
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-sec="sad"')

    def test_evidence_and_coverage_surfaced(self):
        f = _finding(self.eng, self.imp)
        ev.create_evidence_request(engagement=self.eng, actor=self.auditor,
                                   title="Provide invoice", gl_finding=f)
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-sec="evidence"')
        self.assertContains(resp, reverse("frontend:evidence_queue"))
        # deep link to coverage filtered by engagement
        self.assertContains(resp, f"engagement={self.eng.id}")

    def test_analytics_surfaced_and_linked(self):
        _row(self.imp)
        ja.run_analytics(self.imp, actor=self.auditor)
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-sec="analytics"')
        self.assertContains(resp, reverse("frontend:analytics_dashboard"))

    def test_readiness_surfaced_with_deep_link(self):
        _finding(self.eng, self.imp, status=_FS.ACCEPTED, amount="30000")
        sad.recalculate_for_engagement(self.eng)
        wp = readiness.generate_for_engagement(self.eng)
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-sec="readiness"')
        self.assertContains(resp, reverse(
            "frontend:readiness_evidence_summary", args=[wp.id]))
        # Safe wording preserved.
        self.assertNotContains(resp, "In our opinion")

    def test_workspace_survives_empty_engagement(self):
        # A brand-new engagement with no data must still render (defensive reads).
        empty = _eng(self.org, code="EMPTY")
        resp = self.client.get(self._url(empty))
        self.assertEqual(resp.status_code, 200)

    def test_newer_modules_surfaced_with_deep_links(self):
        # 9I: substantive/confirmations/management-letter + planning-records
        # sections and their engagement-filtered deep links are present.
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-sec="substantive"')
        self.assertContains(resp, 'data-sec="planning-records"')
        self.assertContains(resp, reverse("frontend:substantive_testing"))
        self.assertContains(resp, reverse("frontend:confirmations"))
        self.assertContains(resp, reverse("frontend:management_letter"))
        self.assertContains(resp, reverse("frontend:isa_planning"))

    def test_planning_records_count_surfaced(self):
        from apps.audit.services import planning_records as pr
        pr.save_record(engagement=self.eng, actor=self.auditor,
                       kind="audit_plan", payload={"strategy": {}})
        resp = self.client.get(self._url())
        self.assertContains(resp, 'data-sec="planning-records"')
        self.assertContains(resp, "Audit plan (300)")


class StageActionTests(Base):
    def test_set_stage(self):
        resp = self.client.post(self._url(), {"action": "set_stage", "stage": "planning"})
        self.assertEqual(resp.status_code, 200)
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.stage, _Eng.Stage.PLANNING)

    def test_invalid_stage_rejected(self):
        resp = self.client.post(self._url(), {"action": "set_stage", "stage": "nope"})
        self.assertContains(resp, "Invalid stage")
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.stage, _Eng.Stage.ACCEPTANCE)

    def test_locked_engagement_cannot_change_stage(self):
        from django.utils import timezone
        self.eng.locked_at = timezone.now()
        self.eng.stage = _Eng.Stage.ARCHIVED
        self.eng.save(update_fields=["locked_at", "stage"])
        resp = self.client.post(self._url(), {"action": "set_stage", "stage": "planning"})
        self.assertContains(resp, "archived")
        self.eng.refresh_from_db()
        self.assertEqual(self.eng.stage, _Eng.Stage.ARCHIVED)


class ScopingTests(Base):
    def test_cross_org_workspace_404(self):
        other = _org("OrgC")
        foreign = _eng(other, code="C-1")
        self.assertEqual(self.client.get(self._url(foreign)).status_code, 404)

    def test_cross_org_stage_change_404(self):
        other = _org("OrgD")
        foreign = _eng(other, code="D-1")
        resp = self.client.post(self._url(foreign), {"action": "set_stage", "stage": "planning"})
        self.assertEqual(resp.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.stage, _Eng.Stage.ACCEPTANCE)


class LedgerIsolationTests(Base):
    def test_workspace_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        _finding(self.eng, self.imp)
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        self.client.get(self._url())
        self.client.post(self._url(), {"action": "set_stage", "stage": "fieldwork"})
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
