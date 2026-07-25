"""TADGEEG-FIN-AUDIT-8B/8C/8D/8G — audit module page tests.

These pages surface existing services (1A–5D). Tests assert access control,
engagement scoping, that the pages render and correctly trigger the underlying
services (analyze / review / recalculate / generate), cross-org 404, and that
nothing writes to the ledger.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.audit_difference_models import AuditDifferenceSummary
from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import (
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
    GeneralLedgerRow,
)
from apps.audit.services import journal_analytics as _ja  # noqa: F401 (import guard)
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

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
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31", materiality=PROFILE)


def _imp(eng):
    return GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv",
        period_end=datetime.date(2025, 12, 31), original_filename="gl.csv")


def _row(imp, *, journal="JV-1", debit="500000", description=""):
    _SEQ["n"] += 1
    return GeneralLedgerRow.objects.create(
        import_batch=imp, engagement=imp.engagement, organization=imp.organization,
        row_number=_SEQ["n"], journal_number=journal,
        transaction_date=datetime.date(2025, 6, 10), account_code="6000",
        account_name="Acct", debit=Decimal(debit), credit=Decimal("0"),
        signed_amount=Decimal(debit), description=description, is_valid=True)


def _finding(eng, imp, *, status=_FS.CANDIDATE, amount="30000"):
    return GeneralLedgerRiskFinding.objects.create(
        engagement=eng, organization=eng.organization, general_ledger_import=imp,
        risk_code="GL-RISK-ROUND", risk_title="Round amount",
        risk_category=GeneralLedgerRiskFinding.Category.ROUND_AMOUNT,
        severity=GeneralLedgerRiskFinding.Severity.MEDIUM, score=50,
        amount_impact=Decimal(amount), account_code="6000", status=status)


class Base(TestCase):
    def setUp(self):
        self.org = _org()
        self.auditor = _auditor(self.org)
        self.eng = _eng(self.org)
        self.imp = _imp(self.eng)
        self.client.force_login(self.auditor)

    PAGES = ("trial_balance", "general_ledger", "sad_dashboard", "readiness_generate")

    def _url(self, name, eng=None):
        base = reverse(f"frontend:{name}")
        e = eng or self.eng
        return f"{base}?engagement={e.id}"


class AccessTests(Base):
    def test_all_pages_require_login(self):
        self.client.logout()
        for name in self.PAGES:
            self.assertEqual(self.client.get(reverse(f"frontend:{name}")).status_code, 302, name)

    def test_all_pages_denied_for_junior(self):
        self.client.force_login(_junior(self.org))
        for name in self.PAGES:
            self.assertEqual(self.client.get(reverse(f"frontend:{name}")).status_code, 403, name)

    def test_all_pages_render_for_auditor(self):
        for name in self.PAGES:
            self.assertEqual(self.client.get(self._url(name)).status_code, 200, name)

    def test_pages_render_without_engagement(self):
        for name in self.PAGES:
            self.assertEqual(self.client.get(reverse(f"frontend:{name}")).status_code, 200, name)


class GeneralLedgerPageTests(Base):
    def test_run_risk_analysis_from_ui(self):
        _row(self.imp)  # a round 500000 journal → will produce findings
        resp = self.client.post(reverse("frontend:general_ledger"), {
            "engagement": str(self.eng.id), "action": "analyze",
            "import": str(self.imp.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(GeneralLedgerRiskFinding.objects.filter(engagement=self.eng).exists())

    def test_findings_listed_and_reviewable(self):
        _finding(self.eng, self.imp, status=_FS.CANDIDATE)
        resp = self.client.get(self._url("general_ledger"))
        self.assertContains(resp, 'data-sec="findings"')
        self.assertContains(resp, "GL-RISK-ROUND")

    def test_review_finding_from_ui(self):
        f = _finding(self.eng, self.imp, status=_FS.CANDIDATE)
        resp = self.client.post(reverse("frontend:general_ledger"), {
            "engagement": str(self.eng.id), "action": "review",
            "finding": str(f.id), "to_status": _FS.ACCEPTED, "reason": "other"})
        self.assertEqual(resp.status_code, 200)
        f.refresh_from_db()
        self.assertEqual(f.status, _FS.ACCEPTED)

    def test_cross_org_import_not_analyzed(self):
        other = _org("OrgB")
        other_imp = _imp(_eng(other, code="B-1"))
        _row(other_imp)
        resp = self.client.post(reverse("frontend:general_ledger"), {
            "engagement": str(self.eng.id), "action": "analyze",
            "import": str(other_imp.id)})
        self.assertContains(resp, "Import not found")


class SadPageTests(Base):
    def test_recalculate_creates_summary(self):
        _finding(self.eng, self.imp, status=_FS.ACCEPTED, amount="30000")
        resp = self.client.post(reverse("frontend:sad_dashboard"), {
            "engagement": str(self.eng.id), "action": "recalculate"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AuditDifferenceSummary.objects.filter(engagement=self.eng).exists())

    def test_summary_and_items_rendered(self):
        from apps.audit.services import audit_difference_summary as sad
        _finding(self.eng, self.imp, status=_FS.ACCEPTED, amount="30000")
        sad.recalculate_for_engagement(self.eng)
        resp = self.client.get(self._url("sad_dashboard"))
        self.assertContains(resp, 'data-sec="summary"')


class ReadinessPageTests(Base):
    def test_generate_workpaper_from_ui(self):
        from apps.audit.services import audit_difference_summary as sad
        _finding(self.eng, self.imp, status=_FS.ACCEPTED, amount="30000")
        sad.recalculate_for_engagement(self.eng)
        resp = self.client.post(reverse("frontend:readiness_generate"), {
            "engagement": str(self.eng.id), "action": "generate"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.eng.readiness_workpapers.exists())
        # Export links present + safe wording.
        self.assertContains(resp, "/export/?format=pdf")
        self.assertNotContains(resp, "In our opinion")


class ScopingTests(Base):
    def test_cross_org_engagement_shows_no_data(self):
        other = _org("OrgC")
        foreign = _eng(other, code="C-1")
        # Foreign engagement id is not resolvable in this org → treated as no engagement.
        resp = self.client.get(reverse("frontend:sad_dashboard"),
                               {"engagement": str(foreign.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Choose an engagement")


class LedgerIsolationTests(Base):
    def test_module_actions_never_write_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        _row(self.imp)
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        self.client.post(reverse("frontend:general_ledger"), {
            "engagement": str(self.eng.id), "action": "analyze", "import": str(self.imp.id)})
        self.client.post(reverse("frontend:sad_dashboard"), {
            "engagement": str(self.eng.id), "action": "recalculate"})
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
