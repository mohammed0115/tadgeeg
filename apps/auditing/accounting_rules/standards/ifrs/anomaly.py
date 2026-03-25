from decimal import Decimal

from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class IFRSAnomalyRule(AccountingRule):
    code = "IFRS-ANO-001"
    title = "IFRS Materiality and Unusual Pattern"
    description = "Identify unusual or materially significant transactions requiring reviewer attention."
    standard = AccountingStandard.IFRS
    category = RuleCategory.ANOMALY
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.EXPENSE, EntityType.PAYMENT, EntityType.VENDOR_BILL, EntityType.JOURNAL_ENTRY)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        amount = self.as_decimal(record.get("amount"))
        threshold = self.as_decimal(self.config.get("materiality_amount", 12000))
        rounded_step = self.as_decimal(self.config.get("rounded_step", 1000), Decimal("1000"))
        unusual_flag = bool(record.get("unusual_pattern_flag") or record.get("duplicate_flag"))
        rounded = bool(rounded_step > 0 and amount > 0 and amount % rounded_step == 0)

        if unusual_flag or (amount >= threshold and rounded):
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="IFRS anomaly/materiality signal detected.",
                failure_reason="Transaction exhibits unusual or material characteristics.",
                recommendation="Perform focused substantive review and disclosure assessment.",
                score_impact=0.6,
                related_fields=["amount", "duplicate_flag", "unusual_pattern_flag"],
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="IFRS anomaly check passed.",
        )
