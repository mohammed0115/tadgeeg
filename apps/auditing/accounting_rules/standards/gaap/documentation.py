from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class GAAPDocumentationRule(AccountingRule):
    code = "GAAP-DOC-001"
    title = "GAAP Supporting Documentation"
    description = "Material transactions must have valid supporting documents."
    standard = AccountingStandard.GAAP
    category = RuleCategory.DOCUMENTATION
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.JOURNAL_ENTRY, EntityType.EXPENSE, EntityType.VENDOR_BILL, EntityType.DOCUMENT)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        amount = self.as_decimal(record.get("amount"))
        threshold = self.as_decimal(self.config.get("materiality_amount", 10000))
        if amount < threshold:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.NOT_APPLICABLE,
                severity=self.severity,
                observation="Amount below materiality threshold.",
                metadata_json={"materiality_amount": str(threshold)},
            )

        if not record.get("supporting_document") and not record.get("reference"):
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.FAILED,
                severity=self.severity,
                observation="Material transaction missing support evidence.",
                failure_reason="No supporting document or valid supporting reference found.",
                recommendation="Attach supporting document before approval.",
                score_impact=1.0,
                related_fields=["supporting_document", "reference", "amount"],
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="Supporting evidence exists for material transaction.",
            related_fields=["supporting_document", "reference"],
        )
