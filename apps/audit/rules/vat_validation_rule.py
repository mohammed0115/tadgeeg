"""
R002 — VAT Validation Rule

Validates VAT calculation accuracy and ZATCA compliance.

Checks:
  - VAT rate matches country standard (15% for SA)
  - tax_amount = subtotal × vat_rate (±tolerance)
  - subtotal + tax_amount = total_amount (±tolerance)
  - Vendor VAT number present and correctly formatted
  - ZATCA QR code present (SA invoices)

Severity: MEDIUM (calculation errors) → HIGH (missing VAT number)
Applies to: invoice, vat_return
"""

from .base_rule import AuditRule, RuleResult, Severity


class VATValidationRule(AuditRule):
    """
    VAT compliance validation using the VATValidator service.
    """

    rule_id = "R002"
    rule_name = "VAT Calculation & Compliance Validation"
    severity = Severity.MEDIUM
    applies_to = {"invoice", "vat_return"}
    description = (
        "Validates VAT rate, calculation accuracy, and ZATCA compliance "
        "for invoices issued in GCC countries."
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

        # Use pre-computed compliance result if available
        comp_result = context.get("compliance_result")
        if comp_result is None:
            try:
                country = self._get_country(organization_id)
                from core.services.compliance.vat_validator import VATValidator
                validator = VATValidator(country_code=country)
                comp_result = validator.validate(document)
            except Exception as exc:
                return self._error(exc)

        compliance_score = float(comp_result.get("compliance_score", 1.0))
        issues = comp_result.get("issues", [])
        vat_valid = comp_result.get("vat_valid", True)
        checks = comp_result.get("checks", {})

        if not vat_valid or compliance_score < 0.70:
            severity = Severity.HIGH if compliance_score < 0.50 else Severity.MEDIUM
            self.severity = severity
            return self._fail(
                explanation=(
                    f"VAT compliance score: {compliance_score:.0%}. "
                    f"Issues: {'; '.join(issues[:5])}"
                ),
                details={
                    "compliance_score": compliance_score,
                    "vat_valid": vat_valid,
                    "issues": issues,
                    "checks": checks,
                },
            )

        if issues:
            self.severity = Severity.LOW
            return self._fail(
                explanation=f"Minor VAT compliance issues: {'; '.join(issues[:3])}",
                details={"compliance_score": compliance_score, "issues": issues},
            )

        return self._pass(
            details={"compliance_score": compliance_score, "vat_valid": vat_valid}
        )

    def _get_country(self, organization_id: int) -> str:
        if not organization_id:
            return "SA"
        try:
            from apps.authentication.models import Organization
            org = Organization.objects.get(pk=organization_id)
            return getattr(org, "country", "SA") or "SA"
        except Exception:
            return "SA"
