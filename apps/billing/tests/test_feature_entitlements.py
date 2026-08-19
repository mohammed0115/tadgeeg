from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from datetime import timedelta

from django.utils import timezone

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
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

    def test_api_tiers_follow_the_package_matrix(self):
        business, _ = self._activate(PlanCode.BUSINESS)
        professional, _ = self._activate(PlanCode.PROFESSIONAL)
        enterprise = make_org("enterprise-api-org")
        enterprise_plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
        now = timezone.now()
        OrganizationSubscription.objects.create(
            organization=enterprise,
            plan=enterprise_plan,
            status=SubscriptionStatus.ACTIVE,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=29),
            invoice_limit=enterprise_plan.invoice_limit,
            user_limit=enterprise_plan.user_limit,
        )

        assert feature_decision(business, "api").tier == "limited"
        assert feature_decision(business, "api", minimum_tier="full").enabled is False
        assert feature_decision(professional, "whatsapp").enabled is True
        assert feature_decision(professional, "api").tier == "full"
        assert feature_decision(enterprise, "api", minimum_tier="full").enabled is True

    def test_subscription_keeps_capabilities_it_was_sold(self):
        org, subscription = self._activate(PlanCode.PROFESSIONAL)
        plan = subscription.plan
        plan.feature_tiers = {"whatsapp": False}
        plan.save(update_fields=["feature_tiers"])

        decision = feature_decision(org, "whatsapp")
        assert decision.enabled is True
        assert decision.source == "subscription_snapshot"

    def test_fraud_detection_tier_is_ordered(self):
        starter, _ = self._activate(PlanCode.STARTER)
        professional, _ = self._activate(PlanCode.PROFESSIONAL)

        assert feature_decision(starter, "fraud_detection", minimum_tier="advanced").enabled is False
        assert feature_decision(professional, "fraud_detection", minimum_tier="advanced").enabled is True
