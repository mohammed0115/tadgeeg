"""Shared validation pipeline for invoices."""

from __future__ import annotations

from apps.audit.services.findings import AuditFindingService
from apps.invoices.models import InvoiceValidationResult
from core.services.invoice_validator import run_all_rules


class ValidationPipelineService:
    """Run invoice validation and persist both rollup and findings."""

    @staticmethod
    def _normalized_rule_payload(validation_result: dict) -> tuple[list, list, dict]:
        rule_details = validation_result.get("rule_details") or validation_result.get("validation_details") or {}
        failed_rule_codes = list(validation_result.get("failed_rule_codes") or [])
        passed_rule_codes = validation_result.get("passed_rule_codes")

        if passed_rule_codes is None:
            passed_rule_codes = [
                code for code, detail in rule_details.items()
                if detail.get("passed") is True
            ]

        if not failed_rule_codes:
            failed_rule_codes = [
                code for code, detail in rule_details.items()
                if detail.get("passed") is False
            ]

        return list(passed_rule_codes), failed_rule_codes, rule_details

    @classmethod
    def validate_invoice(cls, *, invoice, organization, file_hash: str = "", created_by=None, document=None) -> dict:
        result = run_all_rules(invoice, organization=organization, file_hash=file_hash)
        return cls.persist_validation_result(
            invoice=invoice,
            validation_result=result,
            created_by=created_by,
            document=document,
        )

    @classmethod
    def persist_validation_result(cls, *, invoice, validation_result: dict, created_by=None, document=None) -> dict:
        passed_rule_codes, failed_rule_codes, rule_details = cls._normalized_rule_payload(validation_result)
        validation_result.setdefault("passed_rule_codes", passed_rule_codes)
        validation_result.setdefault("failed_rule_codes", failed_rule_codes)
        validation_result.setdefault("rule_details", rule_details)

        InvoiceValidationResult.objects.update_or_create(
            invoice=invoice,
            defaults={
                "has_invoice_number": "INV-001" in passed_rule_codes,
                "has_invoice_date": "INV-002" in passed_rule_codes,
                "has_vendor_name": "INV-003" in passed_rule_codes,
                "has_vendor_vat": "INV-004" in passed_rule_codes,
                "has_total_amount": "INV-005" in passed_rule_codes,
                "has_currency": "INV-006" in passed_rule_codes,
                "total_greater_zero": "INV-007" in passed_rule_codes,
                "no_vat_without_base": "INV-008" in passed_rule_codes,
                "duplicate_invoice_number": "DUP-001" in failed_rule_codes,
                "duplicate_vendor_and_number": "DUP-002" in failed_rule_codes,
                "duplicate_vendor_amount_date": "DUP-003" in failed_rule_codes,
                "duplicate_file_hash": "DUP-004" in failed_rule_codes,
                "duplicate_across_months": "DUP-005" in failed_rule_codes,
                "vat_rate_correct": "VAT-001" in passed_rule_codes,
                "vat_calculation_correct": "VAT-002" in passed_rule_codes,
                "vat_subtotal_correct": "VAT-003" in passed_rule_codes,
                "vat_number_present": "VAT-004" in passed_rule_codes,
                "qr_code_valid": "VAT-005" in passed_rule_codes,
                "amount_unusually_high": "ANO-001" in failed_rule_codes,
                "new_unknown_vendor": "ANO-002" in failed_rule_codes,
                "many_invoices_same_day": "ANO-003" in failed_rule_codes,
                "sudden_price_change": "ANO-004" in failed_rule_codes,
                "many_invoices_year_end": "ANO-005" in failed_rule_codes,
                "vendor_dominates_invoices": "ANO-006" in failed_rule_codes,
                "has_cost_center": "CTL-001" in passed_rule_codes,
                "has_account_code": "CTL-002" in passed_rule_codes,
                "has_approver": "CTL-005" in passed_rule_codes,
                "document_is_clear": "DOC-001" in passed_rule_codes,
                "appears_genuine": "DOC-002" in passed_rule_codes,
                "no_alterations": "DOC-003" in passed_rule_codes,
                "has_qr_code": "DOC-004" in passed_rule_codes,
                "rules_passed": validation_result["rules_passed"],
                "rules_failed": validation_result["rules_failed"],
                "validation_score": validation_result["validation_score"],
                "failed_rule_codes": failed_rule_codes,
                "validation_details": rule_details,
            },
        )

        findings_summary = AuditFindingService.persist_validation_findings(
            invoice=invoice,
            validation_result=validation_result,
            audit_session=invoice.audit_session,
            document=document,
            created_by=created_by,
        )
        validation_result["findings_summary"] = findings_summary
        return validation_result
