from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class IFRSDocumentationRule(AccountingRule):
    code = "IFRS-DOC-001"
    title = "IFRS Faithful Representation Support"
    description = "Sufficient evidence should support transactions for faithful representation."
    standard = AccountingStandard.IFRS
    category = RuleCategory.DOCUMENTATION
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.JOURNAL_ENTRY, EntityType.EXPENSE, EntityType.PAYMENT, EntityType.VENDOR_BILL, EntityType.DOCUMENT)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        amount = self.as_decimal(record.get("amount"))
        threshold = self.as_decimal(self.config.get("materiality_amount", 12000))
        support_level = str(record.get("support_level") or "").lower()
        has_support = bool(record.get("supporting_document") or record.get("reference"))

        if amount >= threshold and (not has_support or support_level in {"low", "none"}):
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.FAILED,
                severity=self.severity,
                observation="Material transaction lacks sufficient support for faithful representation.",
                failure_reason="Supporting evidence is missing or low quality for material amount.",
                recommendation="Attach stronger source evidence and reviewer notes before reporting.",
                score_impact=1.0,
                related_fields=["supporting_document", "reference", "support_level", "amount"],
            )

        if not has_support:
            return self.insufficient_data("IFRS documentation check needs supporting document or reference.", ["supporting_document", "reference"])

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="Supporting evidence appears sufficient for IFRS documentation expectation.",
        )
