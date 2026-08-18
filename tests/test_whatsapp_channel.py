from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.authentication.models import OrganizationSettings
from apps.billing.choices import PlanCode
from apps.billing.models import Plan
from apps.billing.services.subscription_service import SubscriptionService
from apps.billing.tests._factories import make_org
from core.services.whatsapp import (
    WhatsAppTemplate,
    WhatsAppUnavailable,
    organization_whatsapp_enabled,
    send_template,
)


class WhatsAppChannelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_billing_plans", stdout=StringIO())

    def _professional_org(self):
        org = make_org("WhatsApp Org")
        plan = Plan.objects.get(code=PlanCode.PROFESSIONAL)
        subscription = SubscriptionService().create_pending_paid_subscription(org, plan)
        SubscriptionService().activate_subscription(subscription)
        return org

    def test_package_and_opt_in_are_both_required(self):
        org = self._professional_org()
        assert organization_whatsapp_enabled(org) is False
        settings_obj, _ = OrganizationSettings.objects.get_or_create(organization=org)
        settings_obj.notifications = {"whatsapp": {"enabled": True, "template_alerts": True}}
        settings_obj.save(update_fields=["notifications"])
        assert organization_whatsapp_enabled(org) is True

    @override_settings(WHATSAPP_ACCESS_TOKEN="", WHATSAPP_PHONE_NUMBER_ID="")
    def test_unconfigured_provider_fails_closed(self):
        with self.assertRaises(WhatsAppUnavailable):
            send_template(to="+966501234567", template=WhatsAppTemplate("invoice_alert"))

    @override_settings(WHATSAPP_ACCESS_TOKEN="token", WHATSAPP_PHONE_NUMBER_ID="123")
    @patch("core.services.whatsapp.requests.post")
    def test_meta_delivery_uses_template_and_timeout(self, post):
        response = Mock(ok=True)
        response.json.return_value = {"messages": [{"id": "wamid.1"}]}
        post.return_value = response
        result = send_template(to="+966501234567", template=WhatsAppTemplate("invoice_alert"))
        assert result["messages"][0]["id"] == "wamid.1"
        assert post.call_args.kwargs["json"]["type"] == "template"
        assert post.call_args.kwargs["timeout"] == 10
