from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.features import feature_decision
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org


class FeatureEntitlementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def _activate(self, code):
        org = make_org(f"{code}-org")
        plan = Plan.objects.get(code=code)
        sub = SubscriptionService().create_pending_paid_subscription(org, plan)
        return org, SubscriptionService().activate_subscription(sub)

    def test_starter_does_not_include_whatsapp_or_api(self):
        org, _ = self._activate(PlanCode.STARTER)
        assert feature_decision(org, "whatsapp").enabled is False
        assert feature_decision(org, "api").enabled is False

    def test_professional_includes_whatsapp_but_only_read_api(self):
        org, _ = self._activate(PlanCode.PROFESSIONAL)
        assert feature_decision(org, "whatsapp").enabled is True
        assert feature_decision(org, "api").tier == "read"
        assert feature_decision(org, "api", minimum_tier="full").enabled is False

    def test_subscription_keeps_capabilities_it_was_sold(self):
        org, subscription = self._activate(PlanCode.PROFESSIONAL)
        plan = subscription.plan
        plan.feature_tiers = {"whatsapp": False}
        plan.save(update_fields=["feature_tiers"])

        decision = feature_decision(org, "whatsapp")
        assert decision.enabled is True
        assert decision.source == "subscription_snapshot"
