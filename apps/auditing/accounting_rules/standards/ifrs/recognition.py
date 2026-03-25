from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class IFRSRevenueRecognitionRule(AccountingRule):
    code = "IFRS-REV-001"
    title = "IFRS Revenue Recognition"
    description = "Revenue recognition should be supported by an appropriate event/evidence trigger."
    standard = AccountingStandard.IFRS
    category = RuleCategory.RECOGNITION
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.DOCUMENT)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        rec_date = self.as_date(record.get("date"))
        trigger_date = self.as_date(record.get("delivery_date") or record.get("service_date") or record.get("recognition_event_date"))
        if not rec_date or not trigger_date:
            return self.insufficient_data("IFRS revenue recognition requires recognition date and trigger date.", ["date", "recognition_event_date"])

        if rec_date < trigger_date:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.FAILED,
                severity=self.severity,
                observation="Revenue recognized before IFRS trigger event.",
                failure_reason="Recognition precedes event evidence date.",
                recommendation="Recognize revenue when performance obligation evidence is met.",
                score_impact=1.0,
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="IFRS revenue recognition timing appears valid.",
        )


@AccountingRuleRegistry.register
class IFRSExpenseRecognitionRule(AccountingRule):
    code = "IFRS-EXP-001"
    title = "IFRS Expense Period Alignment"
    description = "Expense should align with the correct period and activity under accrual assumptions."
    standard = AccountingStandard.IFRS
    category = RuleCategory.RECOGNITION
    severity = RuleSeverity.MEDIUM
    applies_to = (EntityType.INVOICE, EntityType.EXPENSE, EntityType.VENDOR_BILL, EntityType.JOURNAL_ENTRY)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        date_a = self.as_date(record.get("date"))
        date_b = self.as_date(record.get("activity_date") or record.get("service_date"))
        if not date_a or not date_b:
            return self.insufficient_data("IFRS expense check requires date and activity date.", ["date", "activity_date"])
        max_gap = int(self.config.get("max_period_gap_days", 90))
        gap = abs((date_a - date_b).days)
        if gap > max_gap:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.WARNING,
                severity=self.severity,
                observation="Expense timing may not align with IFRS accrual period expectations.",
                failure_reason=f"Date gap ({gap}) exceeds configured tolerance ({max_gap}).",
                recommendation="Review accrual and period allocation basis.",
                score_impact=0.5,
                metadata_json={"gap_days": gap},
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="IFRS expense period alignment check passed.",
        )
