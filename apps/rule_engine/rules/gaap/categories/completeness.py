from apps.rule_engine.rules.gaap.base import GAAPRuleBase
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPCompletenessCoreFieldsRule(GAAPRuleBase):
    code = "GAAP-COMP-001"
    title = "Core Completeness Fields"
    description = "Validate essential accounting fields for auditable transactions."
    category = "completeness"
    severity = "high"
    applies_to = ("sales_invoice", "purchase_order", "expense", "bank_statement", "other")
    gaap_principle = "Full Disclosure"
    weight = 1.0

    def evaluate(self, record: dict, context: dict) -> GAAPRuleResult:
        required_fields = self.get_config(
            "required_fields",
            ["date", "amount", "account", "counterparty", "supporting_reference"],
        )
        missing: list[str] = []
        for field in required_fields:
            value = record.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(field)

        if missing:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="failed",
                severity=self.severity,
                observation=f"Missing required fields: {', '.join(missing)}",
                failure_reason="Core transaction fields are incomplete for GAAP-grade auditability.",
                recommendation="Complete all required accounting fields before final posting.",
                score_impact=float(self.get_config("failed_impact", 0.9)),
                metadata_json={"missing_fields": missing, "required_fields": required_fields},
            )

        return GAAPRuleResult(
            rule_code=self.code,
            title=self.title,
            status="passed",
            severity=self.severity,
            observation="All required completeness fields are present.",
            recommendation="",
            score_impact=0.0,
            metadata_json={"required_fields": required_fields},
        )
