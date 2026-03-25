from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class GAAPConsistencyRule(AccountingRule):
    code = "GAAP-CONS-001"
    title = "GAAP Treatment Consistency"
    description = "Similar transactions should be treated consistently."
    standard = AccountingStandard.GAAP
    category = RuleCategory.CONSISTENCY
    severity = RuleSeverity.MEDIUM
    applies_to = (EntityType.INVOICE, EntityType.EXPENSE, EntityType.VENDOR_BILL, EntityType.JOURNAL_ENTRY)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        expected_account = record.get("expected_account_code")
        account = record.get("account")
        baseline_category = record.get("baseline_category")
        current_category = record.get("category")
        mismatches = []
        if expected_account and account and str(expected_account) != str(account):
            mismatches.append("account_mismatch")
        if baseline_category and current_category and str(baseline_category) != str(current_category):
            mismatches.append("category_mismatch")

        if mismatches:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="Consistency drift detected against baseline treatment.",
                failure_reason="Similar transactions appear to use different accounting treatment.",
                recommendation="Review policy consistency and document approved deviations.",
                score_impact=0.4,
                metadata_json={"mismatches": mismatches},
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="No consistency issues found in available pattern checks.",
        )
