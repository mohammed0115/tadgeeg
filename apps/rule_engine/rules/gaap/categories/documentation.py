from apps.rule_engine.rules.gaap.base import GAAPRuleBase
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPDocumentationSupportRule(GAAPRuleBase):
    code = "GAAP-DOC-001"
    title = "Supporting Documentation"
    description = "Require valid support documents for material transactions."
    category = "documentation"
    severity = "high"
    applies_to = ("sales_invoice", "purchase_order", "expense", "fixed_asset", "other")
    gaap_principle = "Verifiability"
    weight = 1.1

    def evaluate(self, record: dict, context: dict) -> GAAPRuleResult:
        materiality_threshold = self._as_decimal(self.get_config("materiality_amount", "10000"))
        amount = self._as_decimal(record.get("amount"))
        typed_data = record.get("typed_data", {})
        has_support = bool(
            typed_data.get("supporting_document")
            or typed_data.get("has_attachment")
            or typed_data.get("has_receipt")
            or typed_data.get("receipt_attached")
            or record.get("supporting_reference")
        )

        if amount < materiality_threshold:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="not_applicable",
                severity=self.severity,
                observation=f"Amount below materiality threshold ({materiality_threshold}).",
                recommendation="",
                score_impact=0.0,
                metadata_json={"materiality_amount": str(materiality_threshold), "amount": str(amount)},
            )

        if not has_support:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="failed",
                severity=self.severity,
                observation="Material transaction has no valid supporting document.",
                failure_reason="Support evidence is required for high-value postings.",
                recommendation="Attach an approved supporting document before final approval.",
                score_impact=float(self.get_config("failed_impact", 0.95)),
                metadata_json={"materiality_amount": str(materiality_threshold), "amount": str(amount)},
            )

        return GAAPRuleResult(
            rule_code=self.code,
            title=self.title,
            status="passed",
            severity=self.severity,
            observation="Supporting documentation is available for this material transaction.",
            recommendation="",
            score_impact=0.0,
            metadata_json={"materiality_amount": str(materiality_threshold), "amount": str(amount)},
        )
