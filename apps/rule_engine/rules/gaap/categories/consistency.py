from apps.rule_engine.rules.gaap.base import GAAPRuleBase
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPConsistencyTreatmentRule(GAAPRuleBase):
    code = "GAAP-CONS-001"
    title = "Accounting Treatment Consistency"
    description = "Detect inconsistent accounting treatment for similar transaction patterns."
    category = "consistency"
    severity = "medium"
    applies_to = ("sales_invoice", "purchase_order", "expense", "bank_statement", "other")
    gaap_principle = "Consistency"
    weight = 0.9

    def evaluate(self, record: dict, context: dict) -> GAAPRuleResult:
        typed_data = record.get("typed_data", {})
        expected_account = typed_data.get("expected_account_code")
        account_code = record.get("account")
        baseline_category = typed_data.get("baseline_category")
        current_category = typed_data.get("category") or typed_data.get("expense_category")

        mismatches: list[str] = []
        if expected_account and account_code and str(expected_account) != str(account_code):
            mismatches.append("account_code_mismatch")
        if baseline_category and current_category and str(baseline_category) != str(current_category):
            mismatches.append("category_mismatch")

        if mismatches:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="warning",
                severity=self.severity,
                observation="Inconsistent accounting treatment detected for a similar transaction type.",
                failure_reason="Current classification differs from configured baseline behavior.",
                recommendation="Review consistency policy and document approved treatment changes.",
                score_impact=float(self.get_config("warning_impact", 0.4)),
                metadata_json={
                    "mismatches": mismatches,
                    "expected_account": expected_account,
                    "account_code": account_code,
                    "baseline_category": baseline_category,
                    "current_category": current_category,
                },
            )

        return GAAPRuleResult(
            rule_code=self.code,
            title=self.title,
            status="passed",
            severity=self.severity,
            observation="No consistency deviations detected for configured baseline checks.",
            recommendation="",
            score_impact=0.0,
            metadata_json={},
        )
