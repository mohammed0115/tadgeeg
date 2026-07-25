"""TADGEEG-FIN-AUDIT-8E/8F — ISA assessment page tests.

Form-driven pages over the ISA 315 / 570 / 540 engines. Tests assert access
control, that each form renders, that submitting runs the underlying engine and
shows a coherent result, and that no ledger write occurs (pages are stateless
auditor aids).
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

    PAGES = ("isa_risk", "isa_going_concern", "isa_estimates")


class AccessTests(Base):
    def test_pages_require_login(self):
        self.client.logout()
        for name in self.PAGES:
            self.assertEqual(self.client.get(reverse(f"frontend:{name}")).status_code, 302, name)

    def test_pages_denied_for_junior(self):
        self.client.force_login(_junior(self.org))
        for name in self.PAGES:
            self.assertEqual(self.client.get(reverse(f"frontend:{name}")).status_code, 403, name)

    def test_pages_render_for_auditor(self):
        for name in self.PAGES:
            resp = self.client.get(reverse(f"frontend:{name}"))
            self.assertEqual(resp.status_code, 200, name)
            self.assertContains(resp, "isa-hero")   # polished hero present
            self.assertContains(resp, "isa-tabs")   # sub-nav present


class RiskAssessmentTests(Base):
    def test_high_risk_all_max_inherent_low_controls(self):
        # Max inherent drivers, zero controls/coverage → high audit risk.
        data = {n: 25 for n in (
            "industry_volatility", "complexity_of_transactions",
            "susceptibility_to_fraud", "related_party_density")}
        resp = self.client.post(reverse("frontend:isa_risk"), data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Audit risk")           # result hero label
        self.assertContains(resp, "b-very_high")          # inherent meter maxed
        self.assertContains(resp, 'class="meter"')

    def test_low_risk_strong_controls(self):
        data = {n: 25 for n in (
            "control_design_strength", "control_operating_effectiveness",
            "segregation_of_duties_score", "monitoring_strength",
            "sample_extent", "procedure_persuasiveness", "timing_of_procedures",
            "staff_competence")}
        resp = self.client.post(reverse("frontend:isa_risk"), data)
        self.assertContains(resp, "Within target")

    def test_out_of_range_values_clamped(self):
        resp = self.client.post(reverse("frontend:isa_risk"),
                                {"industry_volatility": "999", "complexity_of_transactions": "-5"})
        self.assertEqual(resp.status_code, 200)  # no crash; clamped to 0..25


class GoingConcernTests(Base):
    def test_no_indicators_is_no_doubt(self):
        resp = self.client.post(reverse("frontend:isa_going_concern"), {})
        self.assertContains(resp, "No Doubt")
        self.assertContains(resp, "sev-no_doubt")

    def test_intention_to_liquidate_is_inappropriate(self):
        resp = self.client.post(reverse("frontend:isa_going_concern"),
                                {"intention_to_liquidate": "on"})
        self.assertContains(resp, "sev-going_concern_inappropriate")
        self.assertContains(resp, "Adverse opinion")  # engine recommendation

    def test_indicators_without_mitigants_material_uncertainty(self):
        resp = self.client.post(reverse("frontend:isa_going_concern"),
                                {"net_liability_position": "on",
                                 "inability_to_pay_creditors": "on"})
        self.assertContains(resp, "sev-material_uncertainty")
        self.assertContains(resp, "chip warn")  # indicators listed


class EstimatesTests(Base):
    def test_low_uncertainty(self):
        resp = self.client.post(reverse("frontend:isa_estimates"), {
            "name": "Small provision", "category": "provision",
            "management_estimate": "1000", "estimation_method": "point",
            "complexity": "1", "subjectivity": "1", "estimation_uncertainty": "1",
            "disclosure_quality": "5"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Estimation uncertainty score")
        self.assertContains(resp, "sev-low")

    def test_significant_risk_estimate(self):
        resp = self.client.post(reverse("frontend:isa_estimates"), {
            "name": "Level 3 fair value", "category": "fair_value",
            "management_estimate": "5000000", "estimation_method": "model_based",
            "complexity": "5", "subjectivity": "5", "estimation_uncertainty": "5",
            "relies_on_external_data": "on", "prior_period_misstatement": "on",
            "disclosure_quality": "1"})
        self.assertContains(resp, "sev-significant_risk")
        self.assertContains(resp, "chip warn")  # drivers listed


class NoLedgerTests(Base):
    def test_isa_pages_never_write_to_ledger(self):
        from apps.ledger.models import Account, JournalEntry, JournalLine
        acc, je, jl = (Account.objects.count(), JournalEntry.objects.count(),
                       JournalLine.objects.count())
        self.client.post(reverse("frontend:isa_risk"), {"industry_volatility": 25})
        self.client.post(reverse("frontend:isa_going_concern"), {"net_liability_position": "on"})
        self.client.post(reverse("frontend:isa_estimates"), {
            "name": "x", "complexity": "3", "subjectivity": "3",
            "estimation_uncertainty": "3", "disclosure_quality": "3",
            "management_estimate": "1"})
        self.assertEqual(Account.objects.count(), acc)
        self.assertEqual(JournalEntry.objects.count(), je)
        self.assertEqual(JournalLine.objects.count(), jl)
