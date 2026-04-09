"""
apps/invoices/services/validation_service.py
=============================================
InvoiceValidationService — extracted from invoices/views.py

Owns:
  - Risk score calculation (_fallback_risk_score logic)
  - Risk level derivation from numeric score
  - Risk merging (AI score + validation score → final score)
  - Invoice revalidation (run all rules + persist + save)

Before this extraction, all this logic lived as private helper functions
inside invoices/views.py, making it untestable without an HTTP request
context and impossible to reuse from Celery tasks or the rule engine.

Usage:
    from apps.invoices.services.validation_service import InvoiceValidationService

    result = InvoiceValidationService.merge_risk_assessment(invoice, validation_result, risk_result)
    result = InvoiceValidationService.revalidate(invoice, acting_user)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.constants import (
    HIGH_RISK_THRESHOLD,
    MEDIUM_RISK_THRESHOLD,
    DUP_RISK_FLOOR,
    ANO_RISK_FLOOR,
    VAT_RISK_FLOOR,
)
from core.domain.result import ServiceResult

if TYPE_CHECKING:
    from apps.invoices.models import Invoice

logger = logging.getLogger("finai")


class InvoiceValidationService:
    """
    Domain service for invoice risk scoring and revalidation.

    All methods are static — this class has no state.
    """

    # ── Risk Score Helpers ────────────────────────────────────────────────────

    @staticmethod
    def to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError, ArithmeticError):
            return default

    @staticmethod
    def risk_level_from_score(score) -> str:
        """Map a numeric risk score (0–100) to a human-readable risk level."""
        numeric = max(0.0, min(100.0, InvoiceValidationService.to_float(score)))
        if numeric >= HIGH_RISK_THRESHOLD:
            return "high"
        if numeric >= MEDIUM_RISK_THRESHOLD:
            return "medium"
        return "low"

    @staticmethod
    def fallback_risk_score(validation_result: dict) -> float:
        """
        Calculate a risk score from rule validation results when the AI risk
        engine is unavailable or returns a score of 0.

        Applies floor bumps for high-signal rule failures:
          DUP-* (duplicate)  → score >= 78
          ANO-* (anomaly)    → score >= 72
          VAT-* (VAT error)  → score >= 58
        """
        validation_score = max(
            0.0,
            min(100.0, InvoiceValidationService.to_float(validation_result.get("validation_score"), 0.0)),
        )
        failed_codes = set(validation_result.get("failed_rule_codes") or [])
        fallback = round(100.0 - validation_score, 2)

        if any(code.startswith("DUP-") for code in failed_codes):
            fallback = max(fallback, DUP_RISK_FLOOR)
        elif any(code.startswith("ANO-") for code in failed_codes):
            fallback = max(fallback, ANO_RISK_FLOOR)
        elif any(code.startswith("VAT-") for code in failed_codes):
            fallback = max(fallback, VAT_RISK_FLOOR)

        return round(max(0.0, min(100.0, fallback)), 2)

    @staticmethod
    def merge_risk_assessment(invoice: "Invoice", validation_result: dict, risk_result: dict) -> dict:
        """
        Merge AI risk engine output with validation-based fallback score.

        Sets invoice fields:
          - risk_score    (final merged score)
          - risk_level    (low / medium / high)
          - ai_recommendations
          - ai_summary
          - is_duplicate
          - status (FLAGGED if high risk, VALIDATED otherwise)

        Does NOT call invoice.save() — caller is responsible.

        Returns:
            Dict with final scores and recommendations.
        """
        from apps.invoices.models import Invoice as InvoiceModel

        risk_result = risk_result or {}
        fallback = InvoiceValidationService.fallback_risk_score(validation_result)
        ai_score = max(0.0, min(100.0, InvoiceValidationService.to_float(risk_result.get("overall_risk_score"), 0.0)))
        final_score = max(ai_score, fallback)
        final_level = InvoiceValidationService.risk_level_from_score(final_score)

        invoice.risk_score = round(final_score, 2)
        invoice.risk_level = final_level
        invoice.ai_recommendations = risk_result.get("recommendations", [])
        if not invoice.ai_summary:
            invoice.ai_summary = str(risk_result.get("ai_summary", "") or "")

        invoice.is_duplicate = any(
            code in validation_result.get("failed_rule_codes", [])
            for code in ["DUP-001", "DUP-002", "DUP-003", "DUP-004"]
        )

        if invoice.status not in [InvoiceModel.Status.APPROVED, InvoiceModel.Status.REJECTED]:
            invoice.status = (
                InvoiceModel.Status.FLAGGED if invoice.risk_score >= HIGH_RISK_THRESHOLD
                else InvoiceModel.Status.VALIDATED
            )

        return {
            "overall_risk_score": invoice.risk_score,
            "risk_level": invoice.risk_level,
            "recommendations": invoice.ai_recommendations,
            "ai_summary": invoice.ai_summary,
        }

    # ── Revalidation ──────────────────────────────────────────────────────────

    @staticmethod
    def revalidate(invoice: "Invoice", acting_user, request=None) -> ServiceResult:
        """
        Re-run all validation rules against an existing invoice and persist
        the results.

        Returns ServiceResult.ok(data=validation_result) or ServiceResult.fail().
        """
        from core.services.invoice_validator import run_all_rules
        from core.services.invoice_ai_service import analyze_invoice_risk
        from core.services.validation_pipeline import ValidationPipelineService
        from apps.invoices.models import InvoiceAuditEvent

        try:
            file_hash = (invoice.extracted_data or {}).get("file_hash", "")
            validation_result = run_all_rules(
                invoice,
                organization=invoice.organization,
                file_hash=file_hash,
            )
            validation_result = ValidationPipelineService.persist_validation_result(
                invoice=invoice,
                validation_result=validation_result,
                created_by=acting_user,
            )

            risk_result = {}
            try:
                vendor_history = InvoiceValidationService._get_vendor_history(
                    invoice.organization, invoice.vendor_name
                )
                risk_result = analyze_invoice_risk(
                    invoice.extracted_data or {},
                    vendor_history,
                )
            except Exception as exc:
                logger.warning("AI risk re-analysis failed during revalidation: %s", exc)

            InvoiceValidationService.merge_risk_assessment(invoice, validation_result, risk_result)
            invoice.save(update_fields=[
                "risk_score", "risk_level", "ai_recommendations",
                "ai_summary", "is_duplicate", "status", "updated_at",
            ])

            InvoiceValidationService._save_audit_event(
                invoice=invoice,
                user=acting_user,
                event_type=InvoiceAuditEvent.EventType.REPROCESSED,
                description=(
                    f"Re-validated after manual review: "
                    f"score={validation_result.get('validation_score')}%"
                ),
                request=request,
            )

            return ServiceResult.ok(data=validation_result)

        except Exception as exc:
            logger.exception("Invoice revalidation failed for %s: %s", invoice.pk, exc)
            return ServiceResult.fail(str(exc), code="REVALIDATION_FAILED")

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_vendor_history(org, vendor_name: str) -> dict:
        """Delegates to the canonical implementation in processor."""
        from apps.invoices.services.processor import get_vendor_history
        return get_vendor_history(org, vendor_name)

    @staticmethod
    def _save_audit_event(invoice, user, event_type, description="", before=None, after=None, request=None):
        """Delegates to the canonical audit helper in core.utils.audit."""
        from core.utils.audit import record_invoice_event
        record_invoice_event(invoice, user, event_type, description, before, after, request)
