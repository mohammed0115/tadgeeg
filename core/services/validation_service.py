"""
Validation Service — Phase 3

Orchestrates Phase 1 (NormalizationService) + Phase 2 (ValidationEngine)
and persists every failed ValidationResult as an AuditFinding via
AuditSessionService.add_finding().

Usage::

    from core.services.validation_service import ValidationService

    svc = ValidationService(session=audit_session, document=document_obj)
    result = svc.run(raw_extraction_dict)
    # result.normalized_doc  — NormalizedDocument
    # result.report          — ValidationReport
    # result.findings_created — list[AuditFinding]
    # result.has_critical     — bool
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from core.services.normalization_service import NormalizationService, NormalizedDocument
from core.services.validation_engine import ValidationEngine, ValidationReport

logger = logging.getLogger(__name__)


# ── Severity → AuditFinding.Severity mapping ─────────────────────────────────

def _map_severity(engine_severity: str) -> str:
    """Map ValidationEngine severity strings to AuditFinding.Severity values."""
    # Both use the same lowercase strings — import to ensure they match
    from apps.audit.models import AuditFinding
    mapping = {
        "critical": AuditFinding.Severity.CRITICAL,
        "high":     AuditFinding.Severity.HIGH,
        "medium":   AuditFinding.Severity.MEDIUM,
        "low":      AuditFinding.Severity.LOW,
        "info":     AuditFinding.Severity.LOW,  # "info" → LOW finding (rare)
    }
    return mapping.get(engine_severity.lower(), AuditFinding.Severity.MEDIUM)


def _map_category(rule_id: str) -> str:
    """Derive AuditFinding.Category from a rule ID."""
    from apps.audit.models import AuditFinding
    category_map = {
        "V001": AuditFinding.Category.AMOUNT_ANOMALY,
        "V002": AuditFinding.Category.COMPLIANCE,
        "V003": AuditFinding.Category.DATE_ANOMALY,
        "V004": AuditFinding.Category.COMPLIANCE,
        "V005": AuditFinding.Category.COMPLIANCE,
    }
    return category_map.get(rule_id, AuditFinding.Category.OTHER)


def _remediation(rule_id: str) -> str:
    """Return a human-readable remediation hint for each rule."""
    hints = {
        "V001": (
            "Review the line-item breakdown. Ensure subtotal + VAT = total. "
            "Re-scan or manually correct the amounts if the document was misread."
        ),
        "V002": (
            "Verify the Saudi Tax Registration Number (TRN) with ZATCA's taxpayer portal. "
            "A valid TRN is exactly 15 digits and begins with '3'."
        ),
        "V003": (
            "Confirm the invoice date printed on the document. "
            "Reject invoices dated in the future or older than 5 years."
        ),
        "V004": (
            "Request the supplier to provide the ZATCA-compliant QR code on the invoice. "
            "All B2C simplified invoices in Saudi Arabia require a QR code per ZATCA e-invoicing regulations."
        ),
        "V005": (
            "Check the currency field. Only SAR, AED, KWD, USD, EUR, GBP and other supported "
            "currencies are accepted. Contact the supplier to reissue in a supported currency."
        ),
    }
    return hints.get(rule_id, "Review and correct the flagged field.")


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ValidationServiceResult:
    normalized_doc:   NormalizedDocument
    report:           ValidationReport
    findings_created: list = field(default_factory=list)  # list[AuditFinding]

    @property
    def has_critical(self) -> bool:
        return self.report.has_critical_failures

    @property
    def summary(self) -> dict:
        return {
            **self.report.summary,
            "findings_persisted": len(self.findings_created),
            "has_critical": self.has_critical,
        }


# ── Service ───────────────────────────────────────────────────────────────────

class ValidationService:
    """
    End-to-end: normalize → validate → persist findings.

    :param session:  AuditSession instance (required for DB persistence).
    :param document: Optional Document instance to link findings to.
    :param invoice:  Optional Invoice instance to link findings to.
    :param persist:  Set to False to skip DB writes (useful in unit tests).
    """

    def __init__(
        self,
        session=None,
        document=None,
        invoice=None,
        persist: bool = True,
    ):
        self._session  = session
        self._document = document
        self._invoice  = invoice
        self._persist  = persist

        self._normalizer = NormalizationService()
        self._engine     = ValidationEngine()

    def run(self, raw: dict) -> ValidationServiceResult:
        """
        Execute the full normalize → validate → persist pipeline.

        :param raw:  Raw extraction dict from FinancialAIEngine.
        :returns:    ValidationServiceResult
        """
        # ── Phase 1: Normalize ────────────────────────────────────────────────
        normalized = self._normalizer.normalize(raw)
        logger.debug(
            "ValidationService: normalized doc — vendor=%s invoice=%s total=%s",
            normalized.vendor_name,
            normalized.invoice_number,
            normalized.total_amount,
        )

        # ── Phase 2: Validate ─────────────────────────────────────────────────
        report = self._engine.validate(normalized)
        logger.info(
            "ValidationService: %d rules, %d failed, %d critical",
            len(report.results),
            len(report.failed),
            len(report.critical_failures),
        )

        # ── Phase 3: Persist findings ─────────────────────────────────────────
        findings = []
        if self._persist and self._session is not None:
            findings = self._persist_findings(report)

        return ValidationServiceResult(
            normalized_doc=normalized,
            report=report,
            findings_created=findings,
        )

    # ── Private ───────────────────────────────────────────────────────────────

    def _persist_findings(self, report: ValidationReport) -> list:
        """Create AuditFinding records for every failed (non-skipped) rule."""
        from apps.audit.session_service import AuditSessionService

        svc = AuditSessionService(self._session)
        created = []

        for result in report.failed:
            # "Skipped" results are passed=True — this loop only gets truly failed
            try:
                finding = svc.add_finding(
                    rule_code=result.rule_id,
                    title=f"[{result.rule_id}] {result.rule_name}",
                    description=result.message,
                    category=_map_category(result.rule_id),
                    severity=_map_severity(result.severity),
                    invoice=self._invoice,
                    document=self._document,
                    evidence=result.details,
                    remediation=_remediation(result.rule_id),
                )
                created.append(finding)
                logger.debug(
                    "ValidationService: created finding %s for rule %s",
                    finding.id, result.rule_id,
                )
            except Exception as exc:
                logger.exception(
                    "ValidationService: failed to persist finding for rule %s: %s",
                    result.rule_id, exc,
                )

        return created
