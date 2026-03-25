from apps.rule_engine.rules.gaap.base import GAAPRuleBase
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPClassificationCapexOpexRule(GAAPRuleBase):
    code = "GAAP-CLS-001"
    title = "CAPEX vs OPEX Classification"
    description = "Detect likely CAPEX/OPEX misclassification without business justification."
    category = "classification"
    severity = "medium"
    applies_to = ("expense", "purchase_order", "fixed_asset", "sales_invoice", "other")
    gaap_principle = "Classification"
    weight = 1.0

    def evaluate(self, record: dict, context: dict) -> GAAPRuleResult:
        typed_data = record.get("typed_data", {})
        category = str(typed_data.get("category") or typed_data.get("expense_category") or "").lower()
        account_code = str(record.get("account") or "").lower()
        description = str(typed_data.get("description") or typed_data.get("purpose") or "").lower()
        amount = self._as_decimal(record.get("amount"))

        capex_keywords = self.get_config(
            "capex_keywords",
            ["asset", "equipment", "machine", "server", "capital", "furniture"],
        )
        capex_threshold = self._as_decimal(self.get_config("capex_threshold", "5000"))

        likely_capex = amount >= capex_threshold and any(k in description for k in capex_keywords)
        classified_as_opex = "opex" in category or account_code.startswith("5")

        if likely_capex and classified_as_opex:
            justification = typed_data.get("classification_justification") or typed_data.get("justification")
            if not justification:
                return GAAPRuleResult(
                    rule_code=self.code,
                    title=self.title,
                    status="warning",
                    severity=self.severity,
                    observation="Potential CAPEX item is classified as OPEX without justification.",
                    failure_reason="Classification pattern suggests accounting treatment mismatch.",
                    recommendation="Add explicit business justification or reclassify to fixed assets.",
                    score_impact=float(self.get_config("warning_impact", 0.6)),
                    metadata_json={
                        "amount": str(amount),
                        "capex_threshold": str(capex_threshold),
                        "category": category,
                        "account_code": account_code,
                    },
                )

        return GAAPRuleResult(
            rule_code=self.code,
            title=self.title,
            status="passed",
            severity=self.severity,
            observation="Classification appears reasonable for available transaction context.",
            recommendation="",
            score_impact=0.0,
            metadata_json={"amount": str(amount), "category": category, "account_code": account_code},
        )
