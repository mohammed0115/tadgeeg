"""TADGEEG-FIN-AUDIT-8H — ISA 300 / 330 / 240 list-builder page tests.

Form + list-driven pages over the ISA 300 planning, ISA 330 response-mapping and
ISA 240 fraud-response engines. Tests assert access control, form render, that
submitting runs the underlying engine (including parallel-array row parsing and
risk escalation), and that no ledger write occurs (pages are stateless aids).
"""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService


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


class Base(TestCase):
    def setUp(self):
        self.org = _org()
        self.auditor = _auditor(self.org)
        self.client.force_login(self.auditor)

    PAGES = ("isa_planning", "isa_responses", "isa_fraud")


class AccessTests(Base):
    def test_pages_require_login(self):
        self.client.logout()
        for name in self.PAGES:
            self.assertEqual(
                self.client.get(reverse(f"frontend:{name}")).status_code, 302, name)

    def test_pages_denied_for_junior(self):
        self.client.force_login(_junior(self.org))
        for name in self.PAGES:
            self.assertEqual(
                self.client.get(reverse(f"frontend:{name}")).status_code, 403, name)

    def test_pages_render_for_auditor(self):
        for name in self.PAGES:
            resp = self.client.get(reverse(f"frontend:{name}"))
            self.assertEqual(resp.status_code, 200, name)
            self.assertContains(resp, "isa-hero")
            self.assertContains(resp, "isa-tabs")


# ── ISA 300 Planning ─────────────────────────────────────────────────────────
class PlanningTests(Base):
    def test_builds_strategy_and_plan(self):
        resp = self.client.post(reverse("frontend:isa_planning"), {
            "organization_name": "Acme LLC", "reporting_period": "FY2026",
            "industry": "retail", "revenue_base": "1000000",
            "risk_areas": "revenue recognition\ninventory valuation"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Acme LLC")            # scope echoes entity
        self.assertContains(resp, "Revenue (1%)")        # non-listed benchmark
        self.assertContains(resp, "revenue recognition")  # risk area threaded into direction
        self.assertContains(resp, "Bank confirmation")    # baseline procedure row

    def test_listed_entity_uses_pbt_benchmark_and_eqr(self):
        resp = self.client.post(reverse("frontend:isa_planning"), {
            "organization_name": "Listed Co", "reporting_period": "FY2026",
            "industry": "banking", "revenue_base": "9000000", "is_listed": "on"})
        self.assertContains(resp, "Profit before tax (5%)")
        self.assertContains(resp, "EQR partner")


# ── ISA 330 Responses ────────────────────────────────────────────────────────
class ResponsesTests(Base):
    def test_maps_multiple_rows(self):
        resp = self.client.post(reverse("frontend:isa_responses"), {
            "risk_name[]": ["Revenue cutoff", "Petty cash"],
            "assertion[]": ["cutoff", "existence"],
            "inherent_risk[]": ["high", "low"],
            "control_risk[]": ["high", "low"],
            "is_significant[]": ["no", "no"],
            "is_fraud[]": ["no", "no"]})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Revenue cutoff")
        self.assertContains(resp, "Petty cash")
        # High combined risk → increased extent; low → reduced.
        self.assertContains(resp, "increased")
        self.assertContains(resp, "reduced")

    def test_significant_risk_escalates(self):
        resp = self.client.post(reverse("frontend:isa_responses"), {
            "risk_name[]": ["Management override"],
            "assertion[]": ["occurrence"],
            "inherent_risk[]": ["medium"],
            "control_risk[]": ["medium"],
            "is_significant[]": ["yes"],
            "is_fraud[]": ["no"]})
        self.assertContains(resp, "test of details (substantive)")
        self.assertContains(resp, "ISA 330 §21")

    def test_empty_rows_error(self):
        resp = self.client.post(reverse("frontend:isa_responses"), {
            "risk_name[]": [""], "assertion[]": ["existence"],
            "inherent_risk[]": ["low"], "control_risk[]": ["low"],
            "is_significant[]": ["no"], "is_fraud[]": ["no"]})
        self.assertContains(resp, "at least one assessed risk")


# ── ISA 240 Fraud ────────────────────────────────────────────────────────────
class FraudTests(Base):
    def test_override_procedures_always_present_even_empty(self):
        resp = self.client.post(reverse("frontend:isa_fraud"), {
            "factor_name[]": [""], "description[]": [""], "severity[]": ["medium"],
            "assertions[]": [""], "detected_by[]": [""]})
        self.assertEqual(resp.status_code, 200)
        # §32 management-override procedures render regardless of factors.
        self.assertContains(resp, "ISA 240 §32")
        self.assertContains(resp, "Journal entry testing")

    def test_factor_pulls_catalogue_procedures(self):
        resp = self.client.post(reverse("frontend:isa_fraud"), {
            "factor_name[]": ["Duplicate payments"], "description[]": ["dupes"],
            "severity[]": ["high"], "assertions[]": ["existence, cutoff"],
            "detected_by[]": ["duplicate"]})
        self.assertContains(resp, "Duplicate payments")
        self.assertContains(resp, "High")                 # overall severity label
        self.assertContains(resp, "Vouch to original")     # catalogue procedure for 'duplicate'


# ── No ledger writes ─────────────────────────────────────────────────────────
class NoLedgerTests(Base):
    def test_pages_never_write_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        self.client.post(reverse("frontend:isa_planning"), {
            "organization_name": "X", "reporting_period": "FY", "industry": "retail",
            "revenue_base": "1"})
        self.client.post(reverse("frontend:isa_responses"), {
            "risk_name[]": ["R"], "assertion[]": ["existence"],
            "inherent_risk[]": ["high"], "control_risk[]": ["high"],
            "is_significant[]": ["no"], "is_fraud[]": ["no"]})
        self.client.post(reverse("frontend:isa_fraud"), {
            "factor_name[]": ["F"], "description[]": ["d"], "severity[]": ["high"],
            "assertions[]": ["existence"], "detected_by[]": ["duplicate"]})
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
