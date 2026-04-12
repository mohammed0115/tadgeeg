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

        # Build rule_results JSON array from rule details
        rule_results_array = []
        for code in passed_rule_codes:
            rule_results_array.append({
                "rule_code": code,
                "rule_name": rule_details.get(code, {}).get("description", code),
                "group": code.split("-")[0],
                "severity": rule_details.get(code, {}).get("severity", "medium"),
                "passed": True,
                "detail": rule_details.get(code, {}).get("detail", "")
            })
        for code in failed_rule_codes:
            rule_results_array.append({
                "rule_code": code,
                "rule_name": rule_details.get(code, {}).get("description", code),
                "group": code.split("-")[0],
                "severity": rule_details.get(code, {}).get("severity", "medium"),
                "passed": False,
                "detail": rule_details.get(code, {}).get("detail", "")
            })

        InvoiceValidationResult.objects.update_or_create(
            invoice=invoice,
            defaults={
                "rule_results": rule_results_array,
                "total_rules": len(rule_results_array),
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
