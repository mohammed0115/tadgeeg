"""
R003 — Missing Critical Fields Rule

Checks that all mandatory financial fields are present.

Required fields (by document type):
  invoice:         invoice_number, date, vendor_name, total_amount, currency, vendor_vat_number
  bank_statement:  date, total_amount, currency
  expense_report:  date, vendor_name, total_amount
  receipt:         date, total_amount
  payroll:         date, total_amount, vendor_name (employee)
  vat_return:      date, tax_amount, currency
  purchase_order:  document_number, date, vendor_name, total_amount

Severity: HIGH (critical financial identity fields)
"""

from .base_rule import AuditRule, RuleResult, Severity

REQUIRED_FIELDS_BY_TYPE: dict[str, list[str]] = {
    "invoice": [
        "document_number", "date", "vendor_name", "total_amount",
        "currency", "vendor_vat_number",
    ],
    "purchase_order": [
        "document_number", "date", "vendor_name", "total_amount",
    ],
    "bank_statement": ["date", "total_amount", "currency"],
    "receipt": ["date", "total_amount"],
    "expense_report": ["date", "vendor_name", "total_amount"],
    "payroll": ["date", "total_amount", "vendor_name"],
    "vat_return": ["date", "tax_amount", "currency"],
    "other": ["date", "total_amount"],
}

# Fields that are CRITICAL (their absence is HIGH severity)
CRITICAL_FIELDS = {"document_number", "vendor_name", "total_amount", "date"}


class MissingFieldsRule(AuditRule):
    """
    Validates that all mandatory fields are populated.

    Severity escalation:
      Any critical field missing → HIGH
      Only non-critical fields missing → MEDIUM
    """

    rule_id = "R003"
    rule_name = "Missing Critical Fields"
    severity = Severity.HIGH
    applies_to = set()   # Applies to all document types
    description = (
        "Ensures all mandatory financial fields are present based on the "
        "document type. Missing critical identity fields (invoice number, "
        "vendor, date, total) are flagged as HIGH severity."
    )

    def evaluate(
        self,
        document: dict,
        organization_id: int = None,
        context: dict = None,
    ) -> RuleResult:
        doc_type = (document.get("document_type") or "other").lower()
        required = REQUIRED_FIELDS_BY_TYPE.get(doc_type, REQUIRED_FIELDS_BY_TYPE["other"])

        missing = []
        for field_name in required:
            value = document.get(field_name)
            if not value or (isinstance(value, (int, float)) and value == 0 and field_name == "document_number"):
                missing.append(field_name)

        if not missing:
            return self._pass(details={"required_fields": required})

        # Determine severity
        critical_missing = [f for f in missing if f in CRITICAL_FIELDS]
        self.severity = Severity.HIGH if critical_missing else Severity.MEDIUM

        return self._fail(
            explanation=(
                f"Missing required fields for {doc_type}: "
                f"{', '.join(missing)}"
            ),
            details={
                "missing_fields": missing,
                "critical_missing": critical_missing,
                "required_fields": required,
            },
        )
