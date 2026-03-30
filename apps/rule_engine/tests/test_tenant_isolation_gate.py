from django.test import TestCase

from apps.authentication.models import Organization, User
from apps.rule_engine.models import RuleAssignment, RuleDefinition
from apps.rule_engine.selectors.rule_selector import RuleSelector


class RuleSelectorTenantIsolationTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A")
        self.org_b = Organization.objects.create(name="Org B")

        self.user_a = User.objects.create_user(
            email="orga@example.com",
            password="test12345",
            full_name="Org A Admin",
            organization=self.org_a,
        )
        self.user_b = User.objects.create_user(
            email="orgb@example.com",
            password="test12345",
            full_name="Org B Admin",
            organization=self.org_b,
        )

        self.rule_global = RuleDefinition.objects.create(
            rule_code="TEN-ISO-001",
            category="data_integrity",
            rule_type="validation",
            scope="generic",
            default_severity="medium",
            implementation_class="apps.rule_engine.rules.generic.document_number_rule.DocumentNumberRule",
            is_active=True,
            is_system_rule=False,
        )
        self.rule_org_b_only = RuleDefinition.objects.create(
            rule_code="TEN-ISO-002",
            category="data_integrity",
            rule_type="validation",
            scope="generic",
            default_severity="medium",
            implementation_class="apps.rule_engine.rules.generic.document_date_rule.DocumentDateRule",
            is_active=True,
            is_system_rule=False,
        )

        RuleAssignment.objects.create(
            rule=self.rule_global,
            document_type="sales_invoice",
            organization=None,
            status="active",
            applicability="full",
        )
        RuleAssignment.objects.create(
            rule=self.rule_org_b_only,
            document_type="sales_invoice",
            organization=self.org_b,
            status="active",
            applicability="full",
        )

    def test_selector_does_not_leak_other_tenant_assignments(self):
        selector = RuleSelector()
        org_a_rules = selector.get_applicable_rules("sales_invoice", str(self.org_a.id))
        org_a_codes = {a.rule.rule_code for a in org_a_rules}

        self.assertIn("TEN-ISO-001", org_a_codes)
        self.assertNotIn("TEN-ISO-002", org_a_codes)

    def test_org_specific_override_applies_only_to_owner_tenant(self):
        selector = RuleSelector()
        org_b_rules = selector.get_applicable_rules("sales_invoice", str(self.org_b.id))
        org_b_codes = {a.rule.rule_code for a in org_b_rules}

        self.assertIn("TEN-ISO-001", org_b_codes)
        self.assertIn("TEN-ISO-002", org_b_codes)
