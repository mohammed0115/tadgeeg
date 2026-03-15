"""
R001 — Duplicate Invoice Detection Rule

Triggers when the same invoice number + vendor combination, or the same
file content, already exists in the organisation's records.

Severity: HIGH
Applies to: invoice, receipt, purchase_order
"""

from .base_rule import AuditRule, RuleResult, Severity


class DuplicateInvoiceRule(AuditRule):
    """
    Detect duplicate invoices using the DuplicateDetector service.

    Thresholds:
      duplicate_score ≥ 0.90 → CRITICAL
      duplicate_score ≥ 0.70 → HIGH (default)
      duplicate_score ≥ 0.50 → MEDIUM (informational warning)
    """

    rule_id = "R001"
    rule_name = "Duplicate Invoice Detection"
    severity = Severity.HIGH
    applies_to = {"invoice", "receipt", "purchase_order"}
    description = (
        "Detects invoices that appear to be duplicates of existing records "
        "based on invoice number, vendor name, amount, date, or file hash."
    )

    def evaluate(
        self,
        document: dict,
        organization_id: int = None,
        context: dict = None,
    ) -> RuleResult:
        context = context or {}

        if not self.is_applicable(document):
            return self._skip()

        # Use pre-computed duplicate result if available (from FinancialAIEngine)
        dup_result = context.get("duplicate_result")
        if dup_result is None:
            try:
                from core.services.detection.duplicate_detector import DuplicateDetector
                detector = DuplicateDetector(organization_id=organization_id)
                dup_result = detector.detect(document)
            except Exception as exc:
                return self._error(exc)

        dup_score = float(dup_result.get("duplicate_score", 0.0))
        reasons = dup_result.get("duplicate_reasons", [])
        matched_ids = dup_result.get("matched_document_ids", [])

        if dup_score >= 0.90:
            # Override severity to CRITICAL for near-certain duplicates
            self.severity = Severity.CRITICAL
            return self._fail(
                explanation=(
                    f"Near-certain duplicate detected (score={dup_score:.2f}). "
                    f"Matched documents: {matched_ids[:5]}. "
                    f"Reasons: {'; '.join(reasons[:3])}"
                ),
                details={
                    "duplicate_score": dup_score,
                    "matched_ids": matched_ids,
                    "reasons": reasons,
                },
            )

        if dup_score >= 0.70:
            self.severity = Severity.HIGH
            return self._fail(
                explanation=(
                    f"Likely duplicate (score={dup_score:.2f}). "
                    f"Reasons: {'; '.join(reasons[:3])}"
                ),
                details={
                    "duplicate_score": dup_score,
                    "matched_ids": matched_ids,
                    "reasons": reasons,
                },
            )

        if dup_score >= 0.50:
            self.severity = Severity.MEDIUM
            return self._fail(
                explanation=f"Possible duplicate detected (score={dup_score:.2f}).",
                details={"duplicate_score": dup_score, "reasons": reasons},
            )

        return self._pass(
            details={"duplicate_score": dup_score}
        )
