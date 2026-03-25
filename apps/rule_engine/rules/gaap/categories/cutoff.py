from apps.rule_engine.rules.gaap.base import GAAPRuleBase
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPCutoffPeriodRule(GAAPRuleBase):
    code = "GAAP-CUT-001"
    title = "Cutoff and Accounting Period"
    description = "Ensure transaction posting is inside approved accounting period and date alignment."
    category = "cutoff"
    severity = "high"
    applies_to = ("sales_invoice", "purchase_order", "expense", "tax_return", "other")
    gaap_principle = "Cutoff"
    weight = 1.2

    def evaluate(self, record: dict, context: dict) -> GAAPRuleResult:
        txn_date = self._as_date(record.get("date"))
        posting_date = self._as_date(record.get("typed_data", {}).get("posting_date"))
        period_start = self._as_date(self.get_config("period_start") or record.get("org_context", {}).get("period_start"))
        period_end = self._as_date(self.get_config("period_end") or record.get("org_context", {}).get("period_end"))

        if not txn_date:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="not_applicable",
                severity=self.severity,
                observation="Transaction date is missing; cutoff check skipped.",
                recommendation="Ensure transaction date is always captured.",
                score_impact=0.0,
                metadata_json={},
            )

        failures: list[str] = []
        if period_start and txn_date < period_start:
            failures.append("transaction_date_before_period_start")
        if period_end and txn_date > period_end:
            failures.append("transaction_date_after_period_end")
        if posting_date and abs((posting_date - txn_date).days) > int(self.get_config("max_posting_gap_days", 7)):
            failures.append("posting_date_mismatch")

        if failures:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="failed",
                severity=self.severity,
                observation="Cutoff anomalies detected in transaction timing.",
                failure_reason="Posting/document dates are inconsistent with accounting period policy.",
                recommendation="Adjust posting to the correct accounting period or document the exception.",
                score_impact=float(self.get_config("failed_impact", 1.0)),
                metadata_json={
                    "failures": failures,
                    "transaction_date": str(txn_date),
                    "posting_date": str(posting_date) if posting_date else None,
                    "period_start": str(period_start) if period_start else None,
                    "period_end": str(period_end) if period_end else None,
                },
            )

        return GAAPRuleResult(
            rule_code=self.code,
            title=self.title,
            status="passed",
            severity=self.severity,
            observation="Transaction timing aligns with accounting period settings.",
            recommendation="",
            score_impact=0.0,
            metadata_json={},
        )
