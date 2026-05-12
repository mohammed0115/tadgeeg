"""Tests #1–#5 from the spec: the seed command produces exactly the
right catalogue."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.billing.choices import PlanCode
from apps.billing.models import Plan


class SeedBillingPlansTests(TestCase):
    def setUp(self):
        call_command("seed_billing_plans", stdout=StringIO())

    def test_creates_four_plans(self):
        self.assertEqual(Plan.objects.count(), 4)
        codes = set(Plan.objects.values_list("code", flat=True))
        self.assertEqual(codes, {
            PlanCode.FREE_TRIAL.value,
            PlanCode.STARTER.value,
            PlanCode.BUSINESS.value,
            PlanCode.PROFESSIONAL.value,
        })

    def test_free_trial_has_20_invoices_at_zero(self):
        p = Plan.objects.get(code=PlanCode.FREE_TRIAL)
        self.assertEqual(p.invoice_limit, 20)
        self.assertEqual(p.price, Decimal("0.00"))
        self.assertTrue(p.is_free)
        self.assertTrue(p.is_trial)
        self.assertEqual(p.duration_days, 30)

    def test_starter_has_100_invoices_at_350(self):
        p = Plan.objects.get(code=PlanCode.STARTER)
        self.assertEqual(p.invoice_limit, 100)
        self.assertEqual(p.price, Decimal("350.00"))
        self.assertFalse(p.is_free)
        self.assertFalse(p.is_trial)

    def test_business_has_500_invoices_at_550(self):
        p = Plan.objects.get(code=PlanCode.BUSINESS)
        self.assertEqual(p.invoice_limit, 500)
        self.assertEqual(p.price, Decimal("550.00"))

    def test_professional_has_1000_invoices_at_890(self):
        p = Plan.objects.get(code=PlanCode.PROFESSIONAL)
        self.assertEqual(p.invoice_limit, 1000)
        self.assertEqual(p.price, Decimal("890.00"))

    def test_idempotent_on_second_run(self):
        call_command("seed_billing_plans", stdout=StringIO())
        call_command("seed_billing_plans", stdout=StringIO())
        self.assertEqual(Plan.objects.count(), 4)
