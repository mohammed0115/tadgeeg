"""TADGEEG-FIN-AUDIT-2B — General Ledger risk analysis tests.

Covers each deterministic rule, scoring/severity mapping, idempotency (incl.
reviewer-decision preservation), org-scoped API run/list/detail, cross-org
denial, and that nothing is written to the ledger.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit.models import (
    AccountMapping,
    AuditEngagement,
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
    GeneralLedgerRow,
)
from apps.audit.services import general_ledger_risk_analysis as risk
from apps.authentication.models import Organization, User

_F = GeneralLedgerRiskFinding


def _org(name="Acme"):
    return Organization.objects.create(name=name, country=Organization.Country.SAUDI_ARABIA)


def _user(org, email="a@e.com", role=None):
    return User.objects.create_user(
        email=email, password="StrongPass123!", full_name="Tester",
        role=role or User.Role.ADMIN, organization=org)


def _engagement(org, code="AUD-2026-001"):
    return AuditEngagement.objects.create(
        organization=org, engagement_code=code, title="FY2025 Audit",
        period_start=datetime.date(2025, 1, 1), period_end=datetime.date(2025, 12, 31))


def _gl_import(eng, **kw):
    return GeneralLedgerImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv", **kw)


def _row(imp, **kw):
    eng = imp.engagement
    defaults = dict(
        import_batch=imp, engagement=eng, organization=eng.organization,
        row_number=imp.rows.count() + 1,
        account_code="6000", account_name="Misc Expense",
        description="Normal monthly expense entry",
        debit=Decimal("100"), credit=Decimal("0"),
        signed_amount=Decimal("100"), is_valid=True,
    )
    defaults.update(kw)
    if "signed_amount" not in kw:
        defaults["signed_amount"] = defaults["debit"] - defaults["credit"]
    return GeneralLedgerRow.objects.create(**defaults)


def _codes(imp):
    return set(imp.risk_findings.values_list("risk_code", flat=True))


class RiskRuleTests(TestCase):
    def setUp(self):
        self.org = _org()
        self.eng = _engagement(self.org)

    def test_missing_description(self):
        imp = _gl_import(self.eng)
        _row(imp, description="", account_code="6000")
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-DESC", _codes(imp))

    def test_unmapped_account(self):
        imp = _gl_import(self.eng)
        _row(imp, account_code="6000", mapped_account=None)
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-UNMAPPED", _codes(imp))

    def test_round_amount(self):
        imp = _gl_import(self.eng)
        _row(imp, debit=Decimal("50000"), credit=0)
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-ROUND", _codes(imp))

    def test_period_end(self):
        imp = _gl_import(self.eng)
        _row(imp, posting_date=datetime.date(2025, 12, 30), debit=Decimal("300"))
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-PERIODEND", _codes(imp))

    def test_weekend(self):
        imp = _gl_import(self.eng)
        friday = datetime.date(2025, 1, 3)
        self.assertIn(friday.weekday(), {4, 5})
        _row(imp, transaction_date=friday)
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-WEEKEND", _codes(imp))

    def test_manual_entry_english(self):
        imp = _gl_import(self.eng)
        _row(imp, description="Manual adjustment to accrual")
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-MANUAL", _codes(imp))

    def test_manual_entry_arabic(self):
        imp = _gl_import(self.eng)
        _row(imp, description="قيد يدوي لتسوية المخصص")
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-MANUAL", _codes(imp))

    def test_sensitive_account(self):
        imp = _gl_import(self.eng)
        m = AccountMapping.objects.create(
            engagement=self.eng, organization=self.org, account_code="1000",
            mapped_category=AccountMapping.Category.CASH_AND_BANK)
        _row(imp, account_code="1000", mapped_account=m, debit=Decimal("25000"))
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-SENSITIVE", _codes(imp))

    def test_threshold_avoidance(self):
        imp = _gl_import(self.eng)
        _row(imp, debit=Decimal("9800"))  # within 5% below 10,000
        risk.analyze_import(imp)
        self.assertIn("GL-RISK-THRESHOLD", _codes(imp))

    def test_duplicate_entry(self):
        imp = _gl_import(self.eng)
        d = datetime.date(2025, 6, 1)
        _row(imp, account_code="7000", debit=Decimal("500"), transaction_date=d)
        _row(imp, account_code="7000", debit=Decimal("500"), transaction_date=d)
        risk.analyze_import(imp)
        dup = imp.risk_findings.filter(risk_code="GL-RISK-DUP")
        self.assertEqual(dup.count(), 2)  # both lines flagged

    def test_unbalanced_journal(self):
        imp = _gl_import(self.eng)
        _row(imp, journal_number="JV-9", debit=Decimal("1000"), credit=0)
        _row(imp, journal_number="JV-9", debit=0, credit=Decimal("700"))
        risk.analyze_import(imp)
        f = imp.risk_findings.filter(risk_code="GL-RISK-UNBALANCED")
        self.assertEqual(f.count(), 1)
        self.assertEqual(f.first().amount_impact, Decimal("300.0000"))


class ScoringTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _engagement(self.org)

    def test_severity_mapping_and_cap(self):
        # Large unbalanced journal → high/critical; score capped at 100.
        imp = _gl_import(self.eng)
        _row(imp, journal_number="JV-1", debit=Decimal("200000"), credit=0)
        _row(imp, journal_number="JV-1", debit=0, credit=Decimal("60000"))
        risk.analyze_import(imp)
        f = imp.risk_findings.get(risk_code="GL-RISK-UNBALANCED")
        self.assertLessEqual(f.score, 100)
        self.assertIn(f.severity, {_F.Severity.HIGH, _F.Severity.CRITICAL})

    def test_low_severity_for_small_missing_desc(self):
        imp = _gl_import(self.eng)
        m = AccountMapping.objects.create(
            engagement=self.eng, organization=self.org, account_code="6000",
            mapped_category=AccountMapping.Category.OPERATING_EXPENSE)
        _row(imp, description="", debit=Decimal("50"), account_code="6000", mapped_account=m)
        risk.analyze_import(imp)
        f = imp.risk_findings.get(risk_code="GL-RISK-DESC")
        self.assertEqual(f.severity, _F.Severity.LOW)


class IdempotencyTests(TestCase):
    def setUp(self):
        self.org = _org(); self.eng = _engagement(self.org)
        self.imp = _gl_import(self.eng)
        _row(self.imp, description="", debit=Decimal("50000"))  # several rules

    def test_rerun_does_not_duplicate(self):
        s1 = risk.analyze_import(self.imp)
        n1 = self.imp.risk_findings.count()
        s2 = risk.analyze_import(self.imp)
        n2 = self.imp.risk_findings.count()
        self.assertEqual(n1, n2)
        self.assertEqual(s1["created"], s2["created"])

    def test_reviewer_decisions_preserved(self):
        risk.analyze_import(self.imp)
        f = self.imp.risk_findings.first()
        f.status = _F.Status.ACCEPTED
        f.save(update_fields=["status"])
        # Re-run: the accepted finding must survive and not be duplicated.
        risk.analyze_import(self.imp)
        still = self.imp.risk_findings.filter(pk=f.pk).first()
        self.assertIsNotNone(still)
        self.assertEqual(still.status, _F.Status.ACCEPTED)
        same_fp = self.imp.risk_findings.filter(fingerprint=f.fingerprint)
        self.assertEqual(same_fp.count(), 1)


class ModelTests(TestCase):
    def test_clean_rejects_cross_tenant(self):
        eng = _engagement(_org("A"))
        imp = _gl_import(eng)
        f = GeneralLedgerRiskFinding(
            engagement=eng, organization=_org("B"), general_ledger_import=imp,
            risk_code="X", risk_title="x", risk_category=_F.Category.OTHER,
            severity=_F.Severity.LOW)
        with self.assertRaises(ValidationError):
            f.clean()

    def test_service_rejects_cross_tenant(self):
        eng = _engagement(_org("A"))
        imp = GeneralLedgerImport.objects.create(
            engagement=eng, organization=_org("B"), source_format="csv")
        with self.assertRaises(ValidationError):
            risk.analyze_import(imp)


class ApiTests(TestCase):
    def setUp(self):
        self.org = _org("OrgA")
        self.user = _user(self.org, "a@e.com")
        self.eng = _engagement(self.org)
        self.imp = _gl_import(self.eng)
        _row(self.imp, description="", debit=Decimal("50000"))
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def test_analyze_list_detail_org_scoped(self):
        url = f"/api/v1/audit/general-ledger/imports/{self.imp.id}/analyze-risks/"
        resp = self.client.post(url, {}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertGreater(resp.json()["created"], 0)

        lst = self.client.get("/api/v1/audit/general-ledger/risk-findings/")
        self.assertEqual(lst.status_code, 200)
        self.assertGreater(len(lst.json()), 0)
        fid = lst.json()[0]["id"]
        detail = self.client.get(f"/api/v1/audit/general-ledger/risk-findings/{fid}/")
        self.assertEqual(detail.status_code, 200)

    def test_analyze_other_org_denied(self):
        other_imp = _gl_import(_engagement(_org("OrgB"), code="OTHER-1"))
        url = f"/api/v1/audit/general-ledger/imports/{other_imp.id}/analyze-risks/"
        resp = self.client.post(url, {}, format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(other_imp.risk_findings.count(), 0)

    def test_findings_list_is_org_scoped(self):
        # Our findings.
        self.client.post(
            f"/api/v1/audit/general-ledger/imports/{self.imp.id}/analyze-risks/",
            {}, format="json")
        # Another org's finding directly.
        other_eng = _engagement(_org("OrgB"), code="OTHER-2")
        other_imp = _gl_import(other_eng)
        GeneralLedgerRiskFinding.objects.create(
            engagement=other_eng, organization=other_eng.organization,
            general_ledger_import=other_imp, risk_code="X", risk_title="x",
            risk_category=_F.Category.OTHER, severity=_F.Severity.LOW)
        lst = self.client.get("/api/v1/audit/general-ledger/risk-findings/").json()
        orgs = {row["organization"] for row in lst}
        self.assertEqual(orgs, {str(self.org.id)})


class LedgerIsolationTests(TestCase):
    def test_no_writes_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        eng = _engagement(_org())
        imp = _gl_import(eng)
        _row(imp, description="", debit=Decimal("50000"))
        risk.analyze_import(imp)
        self.assertGreater(imp.risk_findings.count(), 0)
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
