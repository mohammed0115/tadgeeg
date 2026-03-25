from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class IFRSCompletenessRule(AccountingRule):
    code = "IFRS-COMP-001"
    title = "IFRS Core Completeness"
    description = "Required fields must be complete for IFRS-aligned evaluation."
    standard = AccountingStandard.IFRS
    category = RuleCategory.COMPLETENESS
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.JOURNAL_ENTRY, EntityType.EXPENSE, EntityType.PAYMENT, EntityType.VENDOR_BILL, EntityType.DOCUMENT)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        required_fields = self.config.get("required_fields", ["date", "amount", "account", "counterparty", "reference"])
        missing = [field for field in required_fields if not record.get(field)]
        if missing:
            return self.insufficient_data("Missing required fields for IFRS completeness checks.", missing)

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="All required IFRS completeness fields are present.",
            related_fields=required_fields,
        )
