"""TADGEEG-FIN-AUDIT-9A — Financial Statements review tests (service + API).

Covers deriving the balance sheet / income statement from a trial balance and
account mappings, ratios, year-over-year, classification anomalies (equation
imbalance, negative equity, sign anomalies, unmapped accounts), org scoping,
auditor-only API access, and that nothing writes to the ledger.
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import financial_statements as fs
from apps.audit.trial_balance_models import (
    AccountMapping,
    TrialBalanceImport,
    TrialBalanceRow,
)
from apps.authentication.models import Organization, User

_SEQ = {"n": 0}


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


def _eng(org, code="AUD-1"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY25",
        period_start="2025-01-01", period_end="2025-12-31")


def _imp(eng, name="tb.csv"):
    return TrialBalanceImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv",
        original_filename=name)


def _row(imp, code, debit, credit, atype="", *, name=None):
    _SEQ["n"] += 1
    return TrialBalanceRow.objects.create(
        import_batch=imp, engagement=imp.engagement, organization=imp.organization,
        row_number=_SEQ["n"], account_code=code, account_name=name or code,
        account_type=atype, closing_debit=Decimal(debit), closing_credit=Decimal(credit),
        closing_balance=Decimal(debit) - Decimal(credit))


def _map(eng, code, category):
    return AccountMapping.objects.create(
        engagement=eng, organization=eng.organization, account_code=code,
        account_name=code, mapped_category=category)


def _balanced(eng, imp):
    """A small balanced set: Assets 150k = Liab 40k + Equity 60k + Profit 50k."""
    _row(imp, "1000", "100000", "0", "asset")     # cash
    _row(imp, "1100", "50000", "0", "asset")      # AR
    _row(imp, "2000", "0", "40000", "liability")  # AP
    _row(imp, "3000", "0", "60000", "equity")     # equity
    _row(imp, "4000", "0", "200000", "revenue")   # revenue
    _row(imp, "5000", "150000", "0", "expense")   # cost of sales
    for code, cat in [("1000", "cash_and_bank"), ("1100", "accounts_receivable"),
                      ("2000", "accounts_payable"), ("3000", "equity"),
                      ("4000", "revenue"), ("5000", "cost_of_sales")]:
        _map(eng, code, cat)


class BuildTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _eng(self.org); self.imp = _imp(self.eng)

    def test_no_trial_balance_raises(self):
        # An engagement with no trial-balance import at all.
        bare = _eng(self.org, code="BARE")
        with self.assertRaises(fs.FinancialStatementError):
            fs.build_financial_statements(bare)

    def test_balanced_statements(self):
        _balanced(self.eng, self.imp)
        data = fs.build_financial_statements(self.eng)
        bs = data["statements"]["balance_sheet"]
        is_ = data["statements"]["income_statement"]
        self.assertEqual(bs["total_assets"], Decimal("150000"))
        self.assertEqual(bs["total_liabilities"], Decimal("40000"))
        self.assertEqual(bs["total_equity"], Decimal("60000"))
        self.assertEqual(is_["total_revenue"], Decimal("200000"))
        self.assertEqual(is_["net_profit"], Decimal("50000"))
        # Accounting equation holds → no imbalance anomaly.
        self.assertEqual(bs["liabilities_plus_equity"], Decimal("150000"))
        kinds = {a["kind"] for a in data["anomalies"]}
        self.assertNotIn("equation_imbalance", kinds)

    def test_ratios(self):
        _balanced(self.eng, self.imp)
        r = fs.build_financial_statements(self.eng)["statements"]["ratios"]
        # current assets 150k / current liabilities 40k = 3.75
        self.assertAlmostEqual(r["current_ratio"], 3.75, places=2)
        # gross profit (200k - 150k) / 200k = 0.25
        self.assertAlmostEqual(r["gross_margin_pct"], 0.25, places=2)
        self.assertAlmostEqual(r["net_margin_pct"], 0.25, places=2)

    def test_equation_imbalance_flagged(self):
        # Assets without matching liabilities/equity.
        _row(self.imp, "1000", "100000", "0", "asset")
        _map(self.eng, "1000", "cash_and_bank")
        data = fs.build_financial_statements(self.eng)
        self.assertIn("equation_imbalance", {a["kind"] for a in data["anomalies"]})

    def test_negative_equity_flagged(self):
        _row(self.imp, "1000", "10000", "0", "asset")
        _row(self.imp, "2000", "0", "50000", "liability")
        _row(self.imp, "3000", "40000", "0", "equity")  # debit equity → negative
        _map(self.eng, "1000", "cash_and_bank")
        _map(self.eng, "2000", "accounts_payable")
        _map(self.eng, "3000", "equity")
        data = fs.build_financial_statements(self.eng)
        self.assertIn("negative_equity", {a["kind"] for a in data["anomalies"]})

    def test_sign_anomaly_flagged(self):
        # Revenue account with a DEBIT balance → abnormal.
        _row(self.imp, "4000", "5000", "0", "revenue")
        _map(self.eng, "4000", "revenue")
        data = fs.build_financial_statements(self.eng)
        self.assertIn("sign_anomaly", {a["kind"] for a in data["anomalies"]})

    def test_unmapped_accounts_flagged(self):
        _row(self.imp, "9999", "1000", "0", "asset")  # no mapping
        data = fs.build_financial_statements(self.eng)
        flags = {a["kind"]: a for a in data["anomalies"]}
        self.assertIn("unmapped_accounts", flags)
        self.assertIn("9999", flags["unmapped_accounts"]["accounts"])

    def test_year_over_year(self):
        prior = _imp(self.eng, "prior.csv")
        _row(prior, "4000", "0", "100000", "revenue")
        _map(self.eng, "4000", "revenue")
        current = _imp(self.eng, "current.csv")
        _row(current, "4000", "0", "150000", "revenue")
        data = fs.build_financial_statements(self.eng, tb_import=current)
        yoy = data["year_over_year"]
        self.assertIsNotNone(yoy)
        rev = next(r for r in yoy["rows"] if r["category"] == "revenue")
        self.assertEqual(rev["current"], Decimal("150000"))
        self.assertEqual(rev["prior"], Decimal("100000"))
        self.assertEqual(rev["delta"], Decimal("50000"))

    def test_yoy_none_with_single_import(self):
        _balanced(self.eng, self.imp)
        self.assertIsNone(fs.build_financial_statements(self.eng)["year_over_year"])


class ApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA"); self.auditor = _auditor(self.org)
        self.eng = _eng(self.org); self.imp = _imp(self.eng)
        _balanced(self.eng, self.imp)
        self.api = APIClient(); self.api.force_authenticate(self.auditor)

    def _url(self, eng=None):
        return f"/api/v1/audit/engagements/{(eng or self.eng).id}/financial-statements/"

    def test_returns_statements(self):
        resp = self.api.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body["advisory_only"])
        self.assertEqual(Decimal(body["statements"]["balance_sheet"]["total_assets"]),
                         Decimal("150000"))

    def test_no_tb_returns_400(self):
        empty = _eng(self.org, code="EMPTY")
        self.assertEqual(self.api.get(self._url(empty)).status_code, 400)

    def test_junior_denied(self):
        api = APIClient(); api.force_authenticate(_junior(self.org))
        self.assertEqual(api.get(self._url()).status_code, 403)

    def test_cross_org_404(self):
        other_eng = _eng(_org("OrgB"), code="B-1")
        self.assertEqual(self.api.get(self._url(other_eng)).status_code, 404)


class LedgerIsolationTests(TestCase):
    def test_never_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        org = _org(); eng = _eng(org); imp = _imp(eng)
        _balanced(eng, imp)
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        fs.build_financial_statements(eng)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
