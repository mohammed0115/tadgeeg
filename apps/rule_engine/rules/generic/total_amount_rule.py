"""GEN-H05: Total Amount Present"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class TotalAmountPresentRule(AuditRuleBase):
    rule_code = "GEN-H05"
    rule_name_en = "Total Amount Present"
    rule_name_ar = "وجود المبلغ الإجمالي"
    default_severity = "high"
    rule_type = "validation"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        amount = doc.total_amount
        if amount is None:
            return self._fail(
                "Document is missing a total amount.",
                "المستند لا يحتوي على مبلغ إجمالي.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="total_amount",
                    field_name_ar="المبلغ الإجمالي",
                    expected_value="Non-null number",
                    actual_value=None,
                    description="Total amount is absent.",
                    description_ar="المبلغ الإجمالي مفقود.",
                )]
            )
        return self._pass(f"Total amount {amount} is present.", f"المبلغ الإجمالي {amount} موجود.")
