from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class IFRSClassificationRule(AccountingRule):
    code = "IFRS-CLS-001"
    title = "IFRS Classification and Presentation"
    description = "Accounting classification should align with transaction substance and presentation logic."
    standard = AccountingStandard.IFRS
    category = RuleCategory.CLASSIFICATION
    severity = RuleSeverity.MEDIUM
    applies_to = (EntityType.INVOICE, EntityType.JOURNAL_ENTRY, EntityType.EXPENSE, EntityType.PAYMENT, EntityType.VENDOR_BILL)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        account = str(record.get("account") or "")
        expected_account = str(record.get("expected_account_code") or "")
        presentation = str(record.get("presentation_class") or "").lower()
        nature = str(record.get("nature") or "").lower()
        if not account:
            return self.insufficient_data("IFRS classification requires account code.", ["account"])

        if expected_account and account != expected_account:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="Classification differs from expected account mapping.",
                failure_reason="Account assignment is inconsistent with expected presentation mapping.",
                recommendation="Review chart-of-accounts mapping and presentation class.",
                score_impact=0.5,
                related_fields=["account", "expected_account_code", "presentation_class"],
            )

        if presentation and nature and presentation != nature:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="Presentation class appears inconsistent with transaction nature.",
                failure_reason="Possible IFRS presentation inconsistency.",
                recommendation="Align presentation with economic substance.",
                score_impact=0.4,
                related_fields=["presentation_class", "nature"],
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="IFRS classification checks passed.",
        )
