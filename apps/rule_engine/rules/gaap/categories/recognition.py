from apps.rule_engine.rules.gaap.base import GAAPRuleBase
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPRevenueRecognitionRule(GAAPRuleBase):
    code = "GAAP-REV-001"
    title = "Revenue Recognition Timing"
    description = "Revenue should not be recognized before underlying delivery/service event."
    category = "recognition"
    severity = "high"
    applies_to = ("sales_invoice", "sales_receipt", "other")
    gaap_principle = "Revenue Recognition"
    weight = 1.3

    def evaluate(self, record: dict, context: dict) -> GAAPRuleResult:
        typed_data = record.get("typed_data", {})
        invoice_date = self._as_date(record.get("date") or typed_data.get("invoice_date"))
        event_date = self._as_date(typed_data.get("delivery_date") or typed_data.get("service_date"))

        if not invoice_date or not event_date:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="not_applicable",
                severity=self.severity,
                observation="Insufficient event dates to evaluate revenue timing.",
                recommendation="Capture delivery/service dates for robust revenue recognition checks.",
                score_impact=0.0,
                metadata_json={"invoice_date": str(invoice_date) if invoice_date else None, "event_date": str(event_date) if event_date else None},
            )

        if invoice_date < event_date:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="failed",
                severity=self.severity,
                observation="Revenue appears recognized before performance obligation was fulfilled.",
                failure_reason="Invoice date is earlier than delivery/service date.",
                recommendation="Defer revenue recognition until delivery/service completion evidence exists.",
                score_impact=float(self.get_config("failed_impact", 1.0)),
                metadata_json={"invoice_date": str(invoice_date), "event_date": str(event_date)},
            )

        return GAAPRuleResult(
            rule_code=self.code,
            title=self.title,
            status="passed",
            severity=self.severity,
            observation="Revenue timing is aligned with supporting performance event.",
            recommendation="",
            score_impact=0.0,
            metadata_json={"invoice_date": str(invoice_date), "event_date": str(event_date)},
        )


class GAAPExpenseMatchingRule(GAAPRuleBase):
    code = "GAAP-EXP-001"
    title = "Expense Matching"
    description = "Expense recognition should align with related period or business activity."
    category = "recognition"
    severity = "medium"
    applies_to = ("expense", "purchase_order", "sales_invoice", "other")
    gaap_principle = "Matching Principle"
    weight = 1.0

    def evaluate(self, record: dict, context: dict) -> GAAPRuleResult:
        typed_data = record.get("typed_data", {})
        doc_date = self._as_date(record.get("date"))
        expense_date = self._as_date(typed_data.get("expense_date") or typed_data.get("service_date"))
        max_gap_days = int(self.get_config("max_period_gap_days", 90))

        if not doc_date or not expense_date:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="not_applicable",
                severity=self.severity,
                observation="Insufficient dates for period matching validation.",
                recommendation="Provide expense/service date and transaction date.",
                score_impact=0.0,
                metadata_json={},
            )

        gap_days = abs((doc_date - expense_date).days)
        if gap_days > max_gap_days:
            return GAAPRuleResult(
                rule_code=self.code,
                title=self.title,
                status="warning",
                severity=self.severity,
                observation="Expense posting period appears distant from related activity period.",
                failure_reason=f"Date gap ({gap_days} days) exceeds configured tolerance ({max_gap_days} days).",
                recommendation="Validate matching rationale or adjust accrual period.",
                score_impact=float(self.get_config("warning_impact", 0.45)),
                metadata_json={"doc_date": str(doc_date), "expense_date": str(expense_date), "gap_days": gap_days},
            )

        return GAAPRuleResult(
            rule_code=self.code,
            title=self.title,
            status="passed",
            severity=self.severity,
            observation="Expense timing is within matching tolerance.",
            recommendation="",
            score_impact=0.0,
            metadata_json={"gap_days": gap_days},
        )
