from apps.auditing.accounting_rules.base import AccountingRule
from apps.auditing.accounting_rules.enums import AccountingStandard, EntityType, RuleCategory, RuleSeverity, RuleStatus
from apps.auditing.accounting_rules.registry import AccountingRuleRegistry
from apps.auditing.accounting_rules.result import RuleResult


@AccountingRuleRegistry.register
class GAAPCutoffRule(AccountingRule):
    code = "GAAP-CUT-001"
    title = "GAAP Cutoff Period"
    description = "Posting and transaction dates must align to approved accounting period."
    standard = AccountingStandard.GAAP
    category = RuleCategory.CUTOFF
    severity = RuleSeverity.HIGH
    applies_to = (EntityType.INVOICE, EntityType.JOURNAL_ENTRY, EntityType.EXPENSE, EntityType.VENDOR_BILL)

    def evaluate(self, record: dict, context: dict) -> RuleResult:
        txn_date = self.as_date(record.get("date"))
        post_date = self.as_date(record.get("posting_date"))
        period_start = self.as_date(context.get("period_start") or self.config.get("period_start"))
        period_end = self.as_date(context.get("period_end") or self.config.get("period_end"))
        if not txn_date:
            return self.insufficient_data("Transaction date is required for GAAP cutoff.", ["date"])

        failures = []
        if period_start and txn_date < period_start:
            failures.append("before_period_start")
        if period_end and txn_date > period_end:
            failures.append("after_period_end")
        max_gap = int(self.config.get("max_posting_gap_days", 7))
        if post_date and abs((post_date - txn_date).days) > max_gap:
            failures.append("posting_gap_exceeded")

        if failures:
            return RuleResult(
                rule_code=self.code,
                title=self.title,
                standard=self.standard,
                category=self.category,
                status=RuleStatus.FAILED,
                severity=self.severity,
                observation="GAAP cutoff timing violation detected.",
                failure_reason="Transaction falls outside configured period or posting gap rules.",
                recommendation="Post transaction in the correct period or document approved exception.",
                score_impact=1.0,
                related_fields=["date", "posting_date"],
                metadata_json={"failures": failures},
            )

        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.PASSED,
            severity=self.severity,
            observation="GAAP cutoff checks passed.",
            related_fields=["date", "posting_date"],
        )
