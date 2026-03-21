"""GEN-H07: Total Amount > Zero"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class TotalGreaterZeroRule(AuditRuleBase):
    rule_code = "GEN-H07"
    rule_name_en = "Total Amount Greater Than Zero"
    rule_name_ar = "المبلغ الإجمالي أكبر من صفر"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        # Skip for tax returns which may have zero net VAT
        return doc.document_type not in ("tax_return",) and doc.total_amount is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        amount = float(doc.total_amount)
        if amount <= 0:
            return self._fail(
                f"Total amount {amount} must be greater than zero.",
                f"المبلغ الإجمالي {amount} يجب أن يكون أكبر من صفر.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="total_amount",
                    field_name_ar="المبلغ الإجمالي",
                    expected_value="> 0",
                    actual_value=amount,
                    description=f"Total amount is {amount}, must be > 0.",
                    description_ar=f"المبلغ الإجمالي {amount}، يجب أن يكون أكبر من الصفر.",
                )]
            )
        return self._pass(f"Total amount {amount} > 0.", f"المبلغ الإجمالي {amount} أكبر من الصفر.")
