from decimal import Decimal

from apps.rule_engine.rules.gaap.base import GAAPRuleBase
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPAnomalyPatternRule(GAAPRuleBase):
    code = "GAAP-ANO-001"
    title = "Materiality and Anomaly Pattern"
    description = "Flag unusual values, duplicate indicators, and suspicious rounding patterns."
    category = "anomaly"
    severity = "high"
    applies_to = ("sales_invoice", "purchase_order", "expense", "bank_statement", "sales_receipt", "other")
    gaap_principle = "Materiality"
    weight = 1.2

    def evaluate(self, record: dict, context: dict) -> GAAPRuleResult:
        typed_data = record.get("typed_data", {})
        amount = self._as_decimal(record.get("amount"))
        materiality_amount = self._as_decimal(self.get_config("materiality_amount", "50000"))
        duplicate_flag = bool(
            typed_data.get("is_duplicate")
            or typed_data.get("duplicate_invoice_number")
            or typed_data.get("duplicate_file_hash")
            or typed_data.get("duplicate_claims")
        )

        rounded_step = self._as_decimal(self.get_config("rounded_step", "1000"), Decimal("1000"))
        rounded_pattern = False
        if rounded_step > 0 and amount > 0:
            rounded_pattern = (amount % rounded_step) == 0

        failures: list[str] = []
        if amount >= materiality_amount:
            failures.append("material_amount")
        if duplicate_flag:
            failures.append("duplicate_pattern")
        if rounded_pattern and amount >= materiality_amount:
            failures.append("repeated_rounding_pattern")

        if failures:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="warning",
                severity=self.severity,
                observation="Potential anomaly indicators detected.",
                failure_reason="Transaction meets one or more anomaly/materiality signals.",
                recommendation="Perform manual review and corroborate with supporting documents.",
                score_impact=float(self.get_config("warning_impact", 0.55)),
                metadata_json={
                    "signals": failures,
                    "amount": str(amount),
                    "materiality_amount": str(materiality_amount),
                    "duplicate_flag": duplicate_flag,
                    "rounded_step": str(rounded_step),
                },
            )

        return GAAPRuleResult(
            rule_code=self.code,
            title=self.title,
            status="passed",
            severity=self.severity,
            observation="No anomaly indicators triggered by configured thresholds.",
            recommendation="",
            score_impact=0.0,
            metadata_json={"amount": str(amount), "materiality_amount": str(materiality_amount)},
        )
