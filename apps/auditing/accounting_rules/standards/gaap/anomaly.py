from decimal import Decimal

from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class GAAPAnomalyRule(AccountingRule):
    code = "GAAP-ANO-001"
    title = "GAAP Materiality and Anomaly"
    description = "Detect unusual amounts, duplicate-like behavior, and suspicious rounded patterns."
    standard = AccountingStandard.GAAP
    category = RuleCategory.ANOMALY
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.EXPENSE, EntityType.PAYMENT, EntityType.VENDOR_BILL)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        amount = self.as_decimal(record.get("amount"))
        threshold = self.as_decimal(self.config.get("materiality_amount", 10000))
        rounded_step = self.as_decimal(self.config.get("rounded_step", 1000), Decimal("1000"))
        duplicate = bool(record.get("duplicate_flag"))
        rounded_pattern = bool(rounded_step > 0 and amount > 0 and amount % rounded_step == 0)

        signals = []
        if amount >= threshold:
            signals.append("material_amount")
        if duplicate:
            signals.append("duplicate_like")
        if rounded_pattern and amount >= threshold:
            signals.append("rounded_pattern")

        if signals:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="Anomaly indicators detected for GAAP review.",
                failure_reason="One or more anomaly/materiality signals were triggered.",
                recommendation="Escalate for manual review and corroborating evidence.",
                score_impact=0.6,
                related_fields=["amount", "duplicate_flag"],
                metadata_json={"signals": signals},
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="No GAAP anomaly indicators were triggered.",
        )
