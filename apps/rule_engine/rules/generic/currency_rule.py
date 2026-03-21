"""GEN-H06: Currency Present"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

VALID_CURRENCIES = {"SAR", "AED", "USD", "EUR", "GBP", "KWD", "QAR", "OMR", "BHD"}

class CurrencyRule(AuditRuleBase):
    rule_code = "GEN-H06"
    rule_name_en = "Currency Present and Valid"
    rule_name_ar = "وجود رمز العملة وصحته"
    default_severity = "medium"
    rule_type = "validation"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        currency = doc.currency
        if not currency:
            return self._fail(
                "Document is missing a currency code.",
                "المستند لا يحتوي على رمز العملة.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="currency",
                    field_name_ar="العملة",
                    expected_value="3-letter ISO code",
                    actual_value=None,
                    description="Currency field is absent.",
                    description_ar="حقل العملة مفقود.",
                )]
            )
        if currency.upper() not in VALID_CURRENCIES:
            return self._warning(
                f"Currency '{currency}' is not in the known GCC currency list.",
                f"العملة '{currency}' غير معرّفة ضمن قائمة عملات دول الخليج.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="currency",
                    field_name_ar="العملة",
                    expected_value=list(VALID_CURRENCIES),
                    actual_value=currency,
                    description=f"Currency '{currency}' not in known list.",
                    description_ar=f"العملة '{currency}' غير موجودة في القائمة المعتمدة.",
                )]
            )
        return self._pass(f"Currency '{currency}' is valid.", f"العملة '{currency}' صحيحة.")
