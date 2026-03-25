from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class IFRSConsistencyRule(AccountingRule):
    code = "IFRS-CONS-001"
    title = "IFRS Accounting Consistency"
    description = "Similar transactions should receive consistent IFRS treatment over time."
    standard = AccountingStandard.IFRS
    category = RuleCategory.CONSISTENCY
    severity = RuleSeverity.MEDIUM
    applies_to = (EntityType.INVOICE, EntityType.JOURNAL_ENTRY, EntityType.EXPENSE, EntityType.PAYMENT, EntityType.VENDOR_BILL)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        baseline_method = record.get("baseline_method")
        current_method = record.get("current_method")
        if baseline_method and current_method and baseline_method != current_method:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="Inconsistent accounting method detected for similar transaction type.",
                failure_reason="Method differs from baseline historical treatment.",
                recommendation="Document policy change and obtain approval for method shift.",
                score_impact=0.4,
                related_fields=["baseline_method", "current_method"],
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="IFRS consistency check passed.",
        )
