from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class GAAPRevenueRecognitionRule(AccountingRule):
    code = "GAAP-REV-001"
    title = "GAAP Revenue Recognition"
    description = "Revenue should not be recognized before supporting performance event."
    standard = AccountingStandard.GAAP
    category = RuleCategory.RECOGNITION
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.DOCUMENT)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        invoice_date = self.as_date(record.get("date"))
        event_date = self.as_date(record.get("delivery_date") or record.get("service_date"))
        if not invoice_date or not event_date:
            return self.insufficient_data("Revenue recognition requires both invoice date and delivery/service date.", ["date", "delivery_date|service_date"])

        if invoice_date < event_date:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.FAILED,
                severity=self.severity,
                observation="Revenue appears recognized before fulfillment event.",
                failure_reason="Invoice date is earlier than service/delivery date.",
                recommendation="Defer recognition until performance obligation is fulfilled.",
                score_impact=1.0,
                related_fields=["date", "delivery_date", "service_date"],
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="Revenue recognition timing aligns with supporting event.",
        )


@AccountingRuleRegistry.register
class GAAPExpenseRecognitionRule(AccountingRule):
    code = "GAAP-EXP-001"
    title = "GAAP Expense Matching and Accrual"
    description = "Expenses should align with related period/activity for matching and accrual basis."
    standard = AccountingStandard.GAAP
    category = RuleCategory.RECOGNITION
    severity = RuleSeverity.MEDIUM
    applies_to = (EntityType.INVOICE, EntityType.EXPENSE, EntityType.VENDOR_BILL, EntityType.JOURNAL_ENTRY)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        txn_date = self.as_date(record.get("date"))
        activity_date = self.as_date(record.get("activity_date") or record.get("service_date"))
        if not txn_date or not activity_date:
            return self.insufficient_data("Expense recognition requires transaction date and activity/service date.", ["date", "activity_date|service_date"])

        max_gap = int(self.config.get("max_period_gap_days", 90))
        gap = abs((txn_date - activity_date).days)
        if gap > max_gap:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="Expense timing appears distant from related activity period.",
                failure_reason=f"Gap of {gap} days exceeds configured tolerance {max_gap}.",
                recommendation="Validate accrual basis and matching period treatment.",
                score_impact=0.5,
                related_fields=["date", "activity_date", "service_date"],
                metadata_json={"gap_days": gap},
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="Expense recognition appears aligned with matching/accrual expectations.",
            metadata_json={"gap_days": gap},
        )
