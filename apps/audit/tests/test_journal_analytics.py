"""TADGEEG-FIN-AUDIT-7A — Journal Analytics foundation tests (backend).

Covers the engine, each of the eight deterministic rules, rule enable/disable,
summary aggregation, the dashboard and JSON report, API permissions, cross-org
isolation, determinism, and the guarantees that analytics never touch the 2B
finding pipeline or the ledger.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AuditEngagement,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
    GeneralLedgerRow,
    JournalAnalyticsResult,
    JournalAnalyticsRule,
    JournalAnalyticsRun,
    JournalAnalyticsSummary,
)
from apps.audit.services import journal_analytics as ja
from apps.authentication.models import Organization, User

_Run = JournalAnalyticsRun
PROFILE = {"overall_materiality": 100000, "performance_materiality": 75000,
           "clearly_trivial": 5000, "currency": "SAR"}


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _auditor(org, email="auditor@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Aud Itor",
        role=User.Role.SENIOR_AUDITOR, organization=org)


def _junior(org, email="junior@e.com"):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Jun Ior",
        role=User.Role.JUNIOR_AUDITOR, organization=org)


def _eng(org, code="AUD-1", materiality=None):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31",
        materiality=PROFILE if materiality is None else materiality)


def _imp(eng, *, period_end=None):
    return GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv",
        period_end=period_end or datetime.date(2025, 12, 31))


_ROW_SEQ = {"n": 0}


def _row(imp, *, journal="JV-1", account="6000", debit="0", credit="0",
         description="Purchase of stationery", date=None, entered_by="",
         source_system="", signed=None):
    _ROW_SEQ["n"] += 1
    debit_d, credit_d = Decimal(debit), Decimal(credit)
    return GeneralLedgerRow.objects.create(
        import_batch=imp, engagement=imp.engagement, organization=imp.organization,
        row_number=_ROW_SEQ["n"], journal_number=journal,
        transaction_date=date or datetime.date(2025, 6, 10),
        account_code=account, account_name="Acct",
        debit=debit_d, credit=credit_d,
        signed_amount=Decimal(signed) if signed is not None else (debit_d - credit_d),
        description=description, entered_by=entered_by, source_system=source_system)


class Base(TestCase):
    def setUp(self):
        self.org = _org()
        self.auditor = _auditor(self.org)
        self.eng = _eng(self.org)
        self.imp = _imp(self.eng)

    def _run(self, **kwargs):
        return ja.run_analytics(self.imp, actor=self.auditor, **kwargs)

    def _codes(self, run):
        return set(run.results.values_list("rule_code", flat=True))


class RuleRegistryTests(Base):
    def test_rules_are_seeded_idempotently(self):
        ja.ensure_rules(self.org)
        ja.ensure_rules(self.org)
        self.assertEqual(JournalAnalyticsRule.objects.filter(
            organization=self.org).count(), len(ja.RULES))

    def test_disable_rule_excludes_it_from_runs(self):
        _row(self.imp, debit="500000", description="")   # would trigger several
        ja.set_rule_enabled(organization=self.org, rule_code="JA-DESC", enabled=False)
        run = self._run()
        self.assertNotIn("JA-DESC", self._codes(run))
        self.assertNotIn("JA-DESC", run.rules_executed)

    def test_reenable_rule(self):
        ja.set_rule_enabled(organization=self.org, rule_code="JA-DESC", enabled=False)
        rule = ja.set_rule_enabled(organization=self.org, rule_code="JA-DESC", enabled=True)
        self.assertTrue(rule.is_enabled)

    def test_unknown_rule_rejected(self):
        with self.assertRaises(ja.AnalyticsError):
            ja.set_rule_enabled(organization=self.org, rule_code="NOPE", enabled=False)

    def test_rules_are_org_scoped(self):
        ja.ensure_rules(self.org)
        other = _org("OrgB")
        ja.ensure_rules(other)
        self.assertEqual(JournalAnalyticsRule.objects.filter(
            organization=other).count(), len(ja.RULES))
        ja.set_rule_enabled(organization=other, rule_code="JA-DESC", enabled=False)
        self.assertTrue(JournalAnalyticsRule.objects.get(
            organization=self.org, rule_code="JA-DESC").is_enabled)


class RuleBehaviourTests(Base):
    """One test per deterministic rule."""

    def test_round_amount(self):
        _row(self.imp, journal="JV-R", debit="50000")
        self.assertIn("JA-ROUND", self._codes(self._run(rule_codes=["JA-ROUND"])))

    def test_round_amount_not_triggered_for_odd_value(self):
        _row(self.imp, journal="JV-R", debit="1234.56")
        self.assertNotIn("JA-ROUND", self._codes(self._run(rule_codes=["JA-ROUND"])))

    def test_weekend_posting(self):
        # 2025-06-13 is a Friday (weekday 4) — in WEEKEND_WEEKDAYS.
        _row(self.imp, journal="JV-W", debit="100", date=datetime.date(2025, 6, 13))
        self.assertIn("JA-WEEKEND", self._codes(self._run(rule_codes=["JA-WEEKEND"])))

    def test_weekend_not_triggered_midweek(self):
        # 2025-06-10 is a Tuesday.
        _row(self.imp, journal="JV-M", debit="100", date=datetime.date(2025, 6, 10))
        self.assertNotIn("JA-WEEKEND", self._codes(self._run(rule_codes=["JA-WEEKEND"])))

    def test_period_end_posting(self):
        _row(self.imp, journal="JV-P", debit="100", date=datetime.date(2025, 12, 29))
        self.assertIn("JA-PERIODEND", self._codes(self._run(rule_codes=["JA-PERIODEND"])))

    def test_period_end_not_triggered_mid_year(self):
        _row(self.imp, journal="JV-P2", debit="100", date=datetime.date(2025, 6, 10))
        self.assertNotIn("JA-PERIODEND", self._codes(self._run(rule_codes=["JA-PERIODEND"])))

    def test_manual_journal_detection(self):
        _row(self.imp, journal="JV-MAN", debit="100",
             description="Month end adjustment reclass")
        self.assertIn("JA-MANUAL", self._codes(self._run(rule_codes=["JA-MANUAL"])))

    def test_missing_description(self):
        _row(self.imp, journal="JV-D", debit="100", description="")
        self.assertIn("JA-DESC", self._codes(self._run(rule_codes=["JA-DESC"])))

    def test_high_value_uses_materiality_profile(self):
        # performance materiality is 75,000 → 80,000 is high value.
        _row(self.imp, journal="JV-H", debit="80000")
        run = self._run(rule_codes=["JA-HIGHVALUE"])
        self.assertIn("JA-HIGHVALUE", self._codes(run))
        self.assertIn("3A", run.metadata["high_value_basis"])

    def test_high_value_not_triggered_below_threshold(self):
        _row(self.imp, journal="JV-L", debit="1000")
        self.assertNotIn("JA-HIGHVALUE", self._codes(self._run(rule_codes=["JA-HIGHVALUE"])))

    def test_high_value_falls_back_without_materiality(self):
        eng = _eng(self.org, code="NOMAT", materiality={})
        imp = _imp(eng)
        _row(imp, journal="JV-F", debit="150000")
        run = ja.run_analytics(imp, actor=self.auditor, rule_codes=["JA-HIGHVALUE"])
        self.assertIn("JA-HIGHVALUE", set(run.results.values_list("rule_code", flat=True)))
        self.assertIn("default threshold", run.metadata["high_value_basis"])

    def test_dormant_account_activity(self):
        _row(self.imp, journal="JV-A", account="7100", debit="100",
             date=datetime.date(2025, 1, 5))
        _row(self.imp, journal="JV-B", account="7100", debit="100",
             date=datetime.date(2025, 11, 20))  # ~319 days later
        codes = self._codes(self._run(rule_codes=["JA-DORMANT"]))
        self.assertIn("JA-DORMANT", codes)

    def test_dormant_not_triggered_for_regular_activity(self):
        _row(self.imp, journal="JV-A", account="7200", debit="100",
             date=datetime.date(2025, 1, 5))
        _row(self.imp, journal="JV-B", account="7200", debit="100",
             date=datetime.date(2025, 2, 5))
        self.assertNotIn("JA-DORMANT", self._codes(self._run(rule_codes=["JA-DORMANT"])))

    def test_sensitive_account_usage(self):
        from apps.audit.services.general_ledger_risk_analysis import SENSITIVE_CATEGORIES
        self.assertIn("cash_and_bank", SENSITIVE_CATEGORIES)
        row = _row(self.imp, journal="JV-S", account="1010", debit="60000")
        # Map the row to a sensitive category the same way 2B does.
        from apps.audit.trial_balance_models import AccountMapping
        mapping = AccountMapping.objects.create(
            engagement=self.eng, organization=self.org, account_code="1010",
            account_name="Bank", mapped_category="cash_and_bank")
        row.mapped_account = mapping
        row.save(update_fields=["mapped_account"])
        self.assertIn("JA-SENSITIVE", self._codes(self._run(rule_codes=["JA-SENSITIVE"])))

    def test_multiple_rules_can_trigger_for_one_journal(self):
        # Round + high value + weekend + missing description, all on one journal.
        _row(self.imp, journal="JV-MULTI", debit="500000", description="",
             date=datetime.date(2025, 6, 13))
        codes = self._codes(self._run())
        self.assertTrue({"JA-ROUND", "JA-HIGHVALUE", "JA-WEEKEND", "JA-DESC"} <= codes,
                        f"expected several rules, got {codes}")


class EngineTests(Base):
    def test_run_records_counters_and_status(self):
        _row(self.imp, journal="JV-1", debit="100")
        _row(self.imp, journal="JV-2", debit="200")
        run = self._run()
        self.assertEqual(run.status, _Run.Status.COMPLETED)
        self.assertEqual(run.rows_analyzed, 2)
        self.assertEqual(run.journals_analyzed, 2)
        self.assertGreaterEqual(len(run.rules_executed), 1)
        self.assertIsNotNone(run.completed_at)
        self.assertTrue(run.metadata["advisory_only"])

    def test_journals_group_rows(self):
        _row(self.imp, journal="JV-G", debit="100")
        _row(self.imp, journal="JV-G", credit="100")
        run = self._run()
        self.assertEqual(run.rows_analyzed, 2)
        self.assertEqual(run.journals_analyzed, 1)

    def test_blank_journal_number_becomes_synthetic(self):
        _row(self.imp, journal="", debit="100")
        run = self._run()
        self.assertEqual(run.journals_analyzed, 1)
        self.assertTrue(any(r.journal_number.startswith("ROW-")
                            for r in run.results.all()) or run.findings_count == 0)

    def test_engine_is_deterministic(self):
        _row(self.imp, journal="JV-1", debit="50000", description="")
        first = self._codes(self._run())
        second = self._codes(self._run())
        self.assertEqual(first, second)

    def test_empty_import_completes_cleanly(self):
        run = self._run()
        self.assertEqual(run.status, _Run.Status.COMPLETED)
        self.assertEqual(run.journals_analyzed, 0)
        self.assertEqual(run.findings_count, 0)

    def test_no_rules_enabled_warns(self):
        for spec in ja.RULES:
            ja.set_rule_enabled(organization=self.org, rule_code=spec.code, enabled=False)
        _row(self.imp, debit="100")
        run = self._run()
        self.assertEqual(run.findings_count, 0)
        self.assertTrue(any("no rules enabled" in w for w in run.warnings))

    def test_unknown_rule_code_warns(self):
        _row(self.imp, debit="100")
        run = self._run(rule_codes=["JA-ROUND", "NOT-A-RULE"])
        self.assertTrue(any("unknown rules" in w for w in run.warnings))

    def test_cross_tenant_import_rejected(self):
        other_eng = _eng(_org("OrgB"), code="B-1")
        bad = GeneralLedgerImport.objects.create(
            engagement=other_eng, organization=self.org, source_format="csv")
        with self.assertRaises(ValidationError):
            ja.run_analytics(bad, actor=self.auditor)

    def test_results_carry_full_rule_contract(self):
        _row(self.imp, journal="JV-C", debit="50000")
        run = self._run(rule_codes=["JA-ROUND"])
        r = run.results.first()
        self.assertTrue(r.rule_code and r.rule_name)
        self.assertIn(r.severity, dict(JournalAnalyticsResult.Severity.choices))
        self.assertGreater(r.score, 0)
        self.assertTrue(r.journal_number)
        self.assertTrue(r.description)
        self.assertTrue(r.recommendation)
        self.assertGreaterEqual(r.affected_rows, 1)
        self.assertIsNotNone(r.execution_ms)


class SummaryTests(Base):
    def test_summary_built_and_buckets_journals(self):
        _row(self.imp, journal="JV-1", debit="500000", description="")
        _row(self.imp, journal="JV-2", debit="123.45")
        run = self._run()
        summary = JournalAnalyticsSummary.objects.get(run=run)
        self.assertEqual(summary.total_journals, 2)
        self.assertGreaterEqual(summary.flagged_journals, 1)
        self.assertEqual(
            summary.high_risk_journals + summary.medium_risk_journals
            + summary.low_risk_journals, summary.flagged_journals)
        self.assertTrue(summary.by_rule)

    def test_summary_top_accounts_and_users(self):
        _row(self.imp, journal="JV-1", account="6100", debit="50000",
             entered_by="ahmed")
        run = self._run()
        summary = JournalAnalyticsSummary.objects.get(run=run)
        self.assertTrue(any(a["account_code"] == "6100" for a in summary.top_accounts))
        self.assertTrue(any(u["entered_by"] == "ahmed" for u in summary.top_users))


class DashboardAndReportTests(Base):
    def test_dashboard_without_runs(self):
        data = ja.dashboard(organization=self.org)
        self.assertFalse(data["has_data"])
        self.assertEqual(data["execution_history"], [])

    def test_dashboard_after_run(self):
        _row(self.imp, journal="JV-1", debit="500000", description="")
        self._run()
        data = ja.dashboard(organization=self.org)
        self.assertTrue(data["has_data"])
        self.assertTrue(data["advisory_only"])
        self.assertGreaterEqual(data["total_journals"], 1)
        self.assertTrue(data["top_rules"])
        self.assertEqual(len(data["execution_history"]), 1)

    def test_dashboard_org_scoped(self):
        _row(self.imp, journal="JV-1", debit="500000")
        self._run()
        self.assertFalse(ja.dashboard(organization=_org("OrgB"))["has_data"])

    def test_report_shape(self):
        _row(self.imp, journal="JV-1", debit="500000", description="")
        run = self._run()
        rep = ja.report(run=run)
        for key in ("summary", "rule_statistics", "charts", "top_findings",
                    "recommendations", "advisory_only"):
            self.assertIn(key, rep)
        self.assertTrue(rep["advisory_only"])
        self.assertIn("not audit findings", rep["note"])
        self.assertTrue(rep["rule_statistics"])
        self.assertIn("by_severity", rep["charts"])


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        _row(self.imp, journal="JV-1", debit="500000", description="")
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def test_run_create_and_detail(self):
        resp = self.api.post("/api/v1/audit/journal-analytics/runs/",
                             {"general_ledger_import": str(self.imp.id)}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        run_id = resp.json()["id"]
        self.assertTrue(resp.json()["advisory_only"])
        detail = self.api.get(f"/api/v1/audit/journal-analytics/runs/{run_id}/")
        self.assertEqual(detail.status_code, 200)

    def test_results_and_report_endpoints(self):
        run = self._run()
        res = self.api.get(f"/api/v1/audit/journal-analytics/runs/{run.id}/results/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["results"])
        rep = self.api.get(f"/api/v1/audit/journal-analytics/runs/{run.id}/report/")
        self.assertEqual(rep.status_code, 200)
        self.assertIn("rule_statistics", rep.json())

    def test_results_filter_by_rule(self):
        run = self._run()
        res = self.api.get(
            f"/api/v1/audit/journal-analytics/runs/{run.id}/results/?rule=JA-ROUND")
        self.assertTrue(all(r["rule_code"] == "JA-ROUND" for r in res.json()["results"]))

    def test_dashboard_and_rules_endpoints(self):
        self._run()
        dash = self.api.get("/api/v1/audit/journal-analytics/dashboard/")
        self.assertEqual(dash.status_code, 200)
        rules = self.api.get("/api/v1/audit/journal-analytics/rules/")
        self.assertEqual(len(rules.json()["rules"]), len(ja.RULES))
        toggle = self.api.post("/api/v1/audit/journal-analytics/rules/",
                               {"rule_code": "JA-ROUND", "is_enabled": False},
                               format="json")
        self.assertFalse(toggle.json()["is_enabled"])

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        for url in ("/api/v1/audit/journal-analytics/runs/",
                    "/api/v1/audit/journal-analytics/dashboard/",
                    "/api/v1/audit/journal-analytics/rules/"):
            self.assertEqual(api.get(url).status_code, 403, url)

    def test_cross_org_import_404(self):
        other_eng = _eng(_org("OrgB"), code="B-1")
        other_imp = _imp(other_eng)
        resp = self.api.post("/api/v1/audit/journal-analytics/runs/",
                             {"general_ledger_import": str(other_imp.id)}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_cross_org_run_404(self):
        other_org = _org("OrgC")
        other_eng = _eng(other_org, code="C-1")
        other_imp = _imp(other_eng)
        _row(other_imp, journal="X", debit="50000")
        foreign = ja.run_analytics(other_imp, actor=_auditor(other_org, "c@e.com"))
        for suffix in ("", "results/", "report/"):
            resp = self.api.get(
                f"/api/v1/audit/journal-analytics/runs/{foreign.id}/{suffix}")
            self.assertEqual(resp.status_code, 404, suffix)

    def test_run_list_excludes_other_org(self):
        self._run()
        other_org = _org("OrgD")
        other_imp = _imp(_eng(other_org, code="D-1"))
        _row(other_imp, journal="X", debit="50000")
        foreign = ja.run_analytics(other_imp, actor=_auditor(other_org, "d@e.com"))
        listing = self.api.get("/api/v1/audit/journal-analytics/runs/").json()["results"]
        self.assertNotIn(str(foreign.id), [r["id"] for r in listing])


class IsolationTests(Base):
    def test_analytics_never_creates_findings_or_touches_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        _row(self.imp, journal="JV-1", debit="500000", description="")
        findings_before = GeneralLedgerRiskFinding.objects.count()
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())

        self._run()

        # 2B finding pipeline untouched — analytics are advisory only.
        self.assertEqual(GeneralLedgerRiskFinding.objects.count(), findings_before)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)

    def test_analytics_does_not_modify_gl_rows(self):
        row = _row(self.imp, journal="JV-1", debit="500000", description="")
        before = (row.debit, row.credit, row.description, row.account_code)
        self._run()
        row.refresh_from_db()
        self.assertEqual((row.debit, row.credit, row.description, row.account_code), before)

    def test_results_are_scoped_to_their_run_and_org(self):
        _row(self.imp, journal="JV-1", debit="500000")
        run = self._run()
        self.assertTrue(all(r.organization_id == self.org.id
                            for r in JournalAnalyticsResult.objects.all()))
        self.assertTrue(all(r.run_id == run.id for r in run.results.all()))
