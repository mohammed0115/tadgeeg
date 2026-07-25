"""TADGEEG-FIN-AUDIT-9A — Financial Statements page tests."""
from __future__ import annotations

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.audit.engagement_models import AuditEngagement
from apps.audit.trial_balance_models import (
    AccountMapping,
    TrialBalanceImport,
    TrialBalanceRow,
)
from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService

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
        period_start="2025-01-01", period_end="2025-12-31")


def _tb(eng):
    imp = TrialBalanceImport.objects.create(
        engagement=eng, organization=eng.organization, source_format="csv",
        original_filename="tb.csv")
    rows = [("1000", "100000", "0", "cash_and_bank"),
            ("2000", "0", "40000", "accounts_payable"),
            ("3000", "0", "60000", "equity"),
            ("4000", "0", "200000", "revenue"),
            ("5000", "150000", "0", "cost_of_sales")]
    for code, d, c, cat in rows:
        _SEQ["n"] += 1
        TrialBalanceRow.objects.create(
            import_batch=imp, engagement=eng, organization=eng.organization,
            row_number=_SEQ["n"], account_code=code, account_name=code,
            closing_debit=Decimal(d), closing_credit=Decimal(c),
            closing_balance=Decimal(d) - Decimal(c))
        AccountMapping.objects.create(
            engagement=eng, organization=eng.organization, account_code=code,
            account_name=code, mapped_category=cat)
    return imp


class Base(TestCase):
    def setUp(self):
        self.org = _org(); self.auditor = _auditor(self.org); self.eng = _eng(self.org)
        _tb(self.eng)
        self.client.force_login(self.auditor)

    def _url(self, eng=None):
        base = reverse("frontend:financial_statements")
        return f"{base}?engagement={(eng or self.eng).id}"


class PageTests(Base):
    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("frontend:financial_statements")).status_code, 302)

    def test_junior_denied(self):
        self.client.force_login(_junior(self.org))
        self.assertEqual(self.client.get(reverse("frontend:financial_statements")).status_code, 403)

    def test_renders_statements(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-sec="balance-sheet"')
        self.assertContains(resp, 'data-sec="income-statement"')
        self.assertContains(resp, 'data-sec="ratios"')
        self.assertContains(resp, "150000")   # total assets

    def test_empty_engagement_state(self):
        empty = _eng(self.org, code="EMPTY")
        resp = self.client.get(self._url(empty))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No trial balance")

    def test_no_engagement_state(self):
        resp = self.client.get(reverse("frontend:financial_statements"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Choose an engagement")

    def test_cross_org_engagement_ignored(self):
        other = _eng(_org("OrgB"), code="B-1")
        resp = self.client.get(self._url(other))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Choose an engagement")  # foreign id → not resolved
