"""GEN-H01: Document Number Present"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class DocumentNumberRule(AuditRuleBase):
    rule_code = "GEN-H01"
    rule_name_en = "Document Number Present"
    rule_name_ar = "وجود رقم المستند"
    default_severity = "high"
    rule_type = "validation"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        number = doc.document_number
        if not number or not str(number).strip():
            return self._fail(
                "Document is missing a unique identifier number.",
                "المستند لا يحتوي على رقم مرجعي فريد.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="document_number",
                    field_name_ar="رقم المستند",
                    expected_value="Non-empty string",
                    actual_value=number,
                    description="Document number field is absent or blank.",
                    description_ar="حقل رقم المستند مفقود أو فارغ.",
                )]
            )
        return self._pass(
            f"Document number '{number}' is present.",
            f"رقم المستند '{number}' موجود.",
        )
