from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class GAAPClassificationRule(AccountingRule):
    code = "GAAP-CLS-001"
    title = "GAAP CAPEX/OPEX Classification"
    description = "Potential CAPEX should not be booked as OPEX without justification."
    standard = AccountingStandard.GAAP
    category = RuleCategory.CLASSIFICATION
    severity = RuleSeverity.MEDIUM
    applies_to = (EntityType.INVOICE, EntityType.EXPENSE, EntityType.VENDOR_BILL)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        amount = self.as_decimal(record.get("amount"))
        category = str(record.get("category") or "").lower()
        description = str(record.get("description") or "").lower()
        capex_threshold = self.as_decimal(self.config.get("capex_threshold", 5000))
        capex_hints = ["asset", "equipment", "machine", "server", "capital"]

        likely_capex = amount >= capex_threshold and any(hint in description for hint in capex_hints)
        is_opex = "opex" in category or category in {"expense", "operating"}

        if likely_capex and is_opex and not record.get("classification_justification"):
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="Potential CAPEX appears classified as OPEX without justification.",
                failure_reason="Classification pattern indicates possible treatment mismatch.",
                recommendation="Provide classification rationale or reclassify entry.",
                score_impact=0.6,
                related_fields=["category", "description", "amount"],
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="Classification check passed for available data.",
            related_fields=["category", "description", "amount"],
        )
