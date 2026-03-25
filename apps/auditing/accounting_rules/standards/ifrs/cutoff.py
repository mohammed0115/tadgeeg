from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class IFRSCutoffRule(AccountingRule):
    code = "IFRS-CUT-001"
    title = "IFRS Period Alignment"
    description = "Recognition/recording should fall in the appropriate financial reporting period."
    standard = AccountingStandard.IFRS
    category = RuleCategory.CUTOFF
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.JOURNAL_ENTRY, EntityType.EXPENSE, EntityType.VENDOR_BILL)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        txn_date = self.as_date(record.get("date"))
        period_start = self.as_date(context.get("period_start") or self.config.get("period_start"))
        period_end = self.as_date(context.get("period_end") or self.config.get("period_end"))
        if not txn_date:
            return self.insufficient_data("IFRS cutoff requires transaction date.", ["date"])

        if (period_start and txn_date < period_start) or (period_end and txn_date > period_end):
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.FAILED,
                severity=self.severity,
                observation="Transaction date is outside reporting period for IFRS alignment.",
                failure_reason="Period alignment check failed.",
                recommendation="Adjust reporting period assignment or document rationale.",
                score_impact=1.0,
                related_fields=["date"],
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="IFRS period alignment check passed.",
        )
