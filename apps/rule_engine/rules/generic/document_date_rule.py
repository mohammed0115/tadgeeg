"""GEN-H02: Document Date Present"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class DocumentDateRule(AuditRuleBase):
    rule_code = "GEN-H02"
    rule_name_en = "Document Date Present"
    rule_name_ar = "وجود تاريخ المستند"
    default_severity = "high"
    rule_type = "validation"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        date = doc.document_date
        if not date:
            return self._fail(
                "Document is missing a date.",
                "المستند لا يحتوي على تاريخ.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="document_date",
                    field_name_ar="تاريخ المستند",
                    expected_value="Valid date",
                    actual_value=None,
                    description="Document date field is absent.",
                    description_ar="حقل تاريخ المستند مفقود.",
                )]
            )
        return self._pass(f"Document date '{date}' is present.", f"تاريخ المستند '{date}' موجود.")
