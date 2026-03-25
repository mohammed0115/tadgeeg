from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class IFRSDisclosureRule(AccountingRule):
    code = "IFRS-DISC-001"
    title = "IFRS Disclosure Readiness"
    description = "Material or sensitive transactions should include sufficient disclosure support fields."
    standard = AccountingStandard.IFRS
    category = RuleCategory.DISCLOSURE
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.JOURNAL_ENTRY, EntityType.EXPENSE, EntityType.PAYMENT, EntityType.VENDOR_BILL, EntityType.DOCUMENT)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        amount = self.as_decimal(record.get("amount"))
        threshold = self.as_decimal(self.config.get("materiality_amount", 12000))
        sensitive = bool(record.get("sensitive_flag"))
        disclosure_fields = ["disclosure_note", "management_assertion", "supporting_document"]

        if amount < threshold and not sensitive:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.NOT_APPLICABLE,
                severity=self.severity,
                observation="Transaction below disclosure sensitivity threshold.",
            )

        missing = [field for field in disclosure_fields if not record.get(field)]
        if missing:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.INSUFFICIENT_DATA,
                severity=self.severity,
                observation="Insufficient data to support IFRS disclosure review.",
                failure_reason="Required disclosure support fields are missing.",
                recommendation="Provide disclosure note, management assertion, and supporting document.",
                score_impact=0.0,
                confidence=0.0,
                related_fields=missing,
                metadata_json={"missing_fields": missing},
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="Disclosure support appears sufficient for IFRS review.",
            related_fields=disclosure_fields,
        )
