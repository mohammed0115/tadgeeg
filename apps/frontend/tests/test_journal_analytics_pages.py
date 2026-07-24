"""TADGEEG-FIN-AUDIT-7A — Journal Analytics frontend tests.

Every 7A backend capability must have a UI entry point: the analytics dashboard
(with charts), runs/execution history, per-run results with filters, and the
rule registry with enable/disable — plus auditor-only permissions and
cross-organization isolation.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import GeneralLedgerImport, GeneralLedgerRow
from apps.audit.journal_analytics_models import JournalAnalyticsRule
from apps.audit.services import journal_analytics as ja
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

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


def _row(imp, *, journal="JV-1", debit="500000", description="", account="6000"):
    _SEQ["n"] += 1
    return GeneralLedgerRow.objects.create(
        import_batch=imp, engagement=imp.engagement, organization=imp.organization,
        row_number=_SEQ["n"], journal_number=journal,
        transaction_date=datetime.date(2025, 6, 10),
        account_code=account, account_name="Acct",
        debit=Decimal(debit), credit=Decimal("0"),
        signed_amount=Decimal(debit), description=description)


class Base(TestCase):
    def setUp(self):
        self.org = _org()
        self.auditor = _auditor(self.org)
        self.eng = _eng(self.org)
        self.imp = _imp(self.eng)
        _row(self.imp)
        self.client.force_login(self.auditor)

    PAGES = ("analytics_dashboard", "analytics_runs", "analytics_rules")


class AccessTests(Base):
    def test_pages_require_login(self):
        self.client.logout()
        for name in self.PAGES:
            resp = self.client.get(reverse(f"frontend:{name}"))
            self.assertEqual(resp.status_code, 302, name)

    def test_pages_denied_for_junior(self):
        self.client.force_login(_junior(self.org))
        for name in self.PAGES:
            resp = self.client.get(reverse(f"frontend:{name}"))
            self.assertEqual(resp.status_code, 403, name)

    def test_pages_render_for_auditor(self):
        for name in self.PAGES:
            resp = self.client.get(reverse(f"frontend:{name}"))
            self.assertEqual(resp.status_code, 200, name)


class DashboardPageTests(Base):
    def test_empty_state_before_any_run(self):
        resp = self.client.get(reverse("frontend:analytics_dashboard"))
        self.assertContains(resp, "No completed analytics run")
        self.assertContains(resp, "Advisory only")

    def test_dashboard_after_run_shows_metrics_and_charts(self):
        ja.run_analytics(self.imp, actor=self.auditor)
        resp = self.client.get(reverse("frontend:analytics_dashboard"))
        self.assertEqual(resp.status_code, 200)
        # Assert on non-translated markers (UI labels may render in Arabic).
        self.assertContains(resp, 'class="kpis"')         # KPI tiles rendered
        self.assertContains(resp, 'id="sev-chart"')       # charts present
        self.assertContains(resp, 'id="rule-chart"')
        self.assertContains(resp, "analytics-charts")     # chart data payload
        self.assertContains(resp, "JA-")                  # a rule code in the table

    def test_dashboard_excludes_other_org(self):
        other = _org("OrgB")
        oimp = _imp(_eng(other, code="B-1"))
        _row(oimp, journal="FOREIGNJV")
        ja.run_analytics(oimp, actor=_auditor(other, "b@e.com"))
        resp = self.client.get(reverse("frontend:analytics_dashboard"))
        self.assertNotContains(resp, "FOREIGNJV")


class RunsPageTests(Base):
    def test_runs_page_lists_imports(self):
        resp = self.client.get(reverse("frontend:analytics_runs"))
        self.assertContains(resp, "gl.csv")
        self.assertContains(resp, "Run analytics")

    def test_run_from_ui_redirects_to_detail(self):
        resp = self.client.post(reverse("frontend:analytics_runs"),
                                {"general_ledger_import": str(self.imp.id)})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/audit/analytics/runs/", resp["Location"])

    def test_run_requires_valid_import(self):
        other_imp = _imp(_eng(_org("OrgC"), code="C-1"))
        resp = self.client.post(reverse("frontend:analytics_runs"),
                                {"general_ledger_import": str(other_imp.id)})
        self.assertContains(resp, "Choose a general ledger import")

    def test_history_lists_runs(self):
        ja.run_analytics(self.imp, actor=self.auditor)
        resp = self.client.get(reverse("frontend:analytics_runs"))
        self.assertContains(resp, "Execution history")
        self.assertContains(resp, "completed")


class RunDetailPageTests(Base):
    def setUp(self):
        super().setUp()
        self.run = ja.run_analytics(self.imp, actor=self.auditor)

    def _url(self, run=None):
        return reverse("frontend:analytics_run_detail", args=[(run or self.run).id])

    def test_detail_shows_results_and_chart(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "JV-1")
        self.assertContains(resp, 'id="rule-chart"')
        self.assertContains(resp, "Advisory only")
        self.assertContains(resp, "JSON report")   # report entry point

    def test_filter_by_rule(self):
        resp = self.client.get(self._url(), {"rule": "JA-ROUND"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Round Amount")

    def test_filter_with_no_matches_shows_empty_state(self):
        resp = self.client.get(self._url(), {"journal": "NO-SUCH-JOURNAL"})
        self.assertContains(resp, "No results match")

    def test_cross_org_run_404(self):
        other = _org("OrgD")
        oimp = _imp(_eng(other, code="D-1"))
        _row(oimp)
        foreign = ja.run_analytics(oimp, actor=_auditor(other, "d@e.com"))
        self.assertEqual(self.client.get(self._url(foreign)).status_code, 404)


class RulesPageTests(Base):
    def test_rules_listed_with_descriptions(self):
        resp = self.client.get(reverse("frontend:analytics_rules"))
        self.assertEqual(resp.status_code, 200)
        for spec in ja.RULES:
            self.assertContains(resp, spec.code)

    def test_disable_and_enable_from_ui(self):
        resp = self.client.post(reverse("frontend:analytics_rules"),
                                {"rule_code": "JA-ROUND", "is_enabled": "0"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(JournalAnalyticsRule.objects.get(
            organization=self.org, rule_code="JA-ROUND").is_enabled)

        self.client.post(reverse("frontend:analytics_rules"),
                         {"rule_code": "JA-ROUND", "is_enabled": "1"})
        self.assertTrue(JournalAnalyticsRule.objects.get(
            organization=self.org, rule_code="JA-ROUND").is_enabled)

    def test_unknown_rule_shows_error(self):
        resp = self.client.post(reverse("frontend:analytics_rules"),
                                {"rule_code": "NOPE", "is_enabled": "0"})
        self.assertContains(resp, "unknown rule")


class NavigationTests(Base):
    def test_sidebar_links_to_analytics(self):
        resp = self.client.get(reverse("frontend:analytics_dashboard"))
        self.assertContains(resp, reverse("frontend:analytics_runs"))
        self.assertContains(resp, reverse("frontend:analytics_rules"))
