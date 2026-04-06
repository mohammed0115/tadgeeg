"""
legacy_audit_adapter.py — Compatibility shims for legacy audit engine interfaces.

This module is the single integration point for migrating from three parallel
legacy engines to AuditPipelineV2. Each adapter accepts the OLD call signature
and internally routes to run_audit_compat, producing the canonical AuditRun.

Legacy engines covered
----------------------
  1. apps.audit.audit_engine.AuditEngine / run_audit
       Interface: evaluate(document: dict, invoice_id, context) → AuditReport
       Callers:   apps/audit/tasks.py (audit_high_risk_documents)

  2. apps.auditing.services.audit_processing_service.AuditProcessingService
       Interface: process(doc: AuditDocument) → AuditDocument
       Callers:   apps/auditing/views/upload.py

  3. apps.audit_engine.services.orchestrator.AuditOrchestrator
       Interface: run(audit_job: AuditJob) → AuditResult
       Callers:   apps/audit_engine/tasks.py

All three adapters delegate to run_audit_compat which routes to V2 (or V1
during shadow rollout) based on AUDIT_ENGINE_VERSION in Django settings.

SOLID alignment
---------------
  Single Responsibility: each adapter does one thing — translate old → new.
  Open/Closed:           add new adapters here without touching old code.
  Liskov Substitution:   adapters accept original types and return compatible objects.
  Interface Segregation: each adapter exposes only the methods callers need.
  Dependency Inversion:  all adapters depend on run_audit_compat (abstraction),
                         not on any concrete engine implementation.
"""
from __future__ import annotations

import logging
import warnings
from typing import Optional

logger = logging.getLogger("rule_engine.pipeline")


# ── Adapter 1: apps.audit.audit_engine.AuditEngine ────────────────────────────

class LegacyAuditEngineAdapter:
    """
    Drop-in replacement for apps.audit.audit_engine.AuditEngine.

    Accepts the original evaluate() signature and routes to AuditPipelineV2.
    Returns a thin AuditRunResult wrapper that satisfies existing consumers
    (primarily apps/audit/tasks.py::audit_high_risk_documents).

    Usage (replace existing AuditEngine instantiation):

        # Before:
        engine = AuditEngine(organization_id=org.id)
        report = engine.evaluate(document, invoice_id=inv.id, context={...})

        # After:
        engine = LegacyAuditEngineAdapter(organization_id=org.id)
        report = engine.evaluate(document, invoice_id=inv.id, context={...})
    """

    def __init__(self, organization_id=None):
        self.organization_id = str(organization_id) if organization_id else None
        warnings.warn(
            "LegacyAuditEngineAdapter wraps the deprecated AuditEngine interface. "
            "Migrate callers to AuditPipelineV2 directly.",
            DeprecationWarning,
            stacklevel=2,
        )

    def evaluate(
        self,
        document: dict,
        invoice_id=None,
        context: Optional[dict] = None,
    ):
        """
        Evaluate a financial document. Routes to AuditPipelineV2 internally.

        Returns an AuditRunResult with the same attributes that AuditReport
        exposed (risk_score, risk_level, escalate, failed/passed counts) so
        existing callers need no changes.
        """
        if not invoice_id:
            raise ValueError("LegacyAuditEngineAdapter.evaluate() requires invoice_id")
        if not self.organization_id:
            raise ValueError("LegacyAuditEngineAdapter requires organization_id")

        from apps.rule_engine.pipeline.v2.compat import run_audit_compat
        audit_run = run_audit_compat(
            document_id=str(invoice_id),
            document_type="sales_invoice",
            organization_id=self.organization_id,
            triggered_by="legacy_adapter",
        )
        return AuditRunResult.from_audit_run(audit_run)

    def save_audit_issues(self, report, invoice=None, created_by=None):
        """
        No-op stub — AuditPipelineV2 persists findings directly.
        Kept for call-site compatibility only.
        """
        logger.debug(
            "[legacy_adapter] save_audit_issues() called on adapter — "
            "findings already persisted by V2 pipeline."
        )
        return []


class AuditRunResult:
    """
    Thin wrapper around AuditRun that satisfies the AuditReport interface
    expected by legacy callers.
    """

    def __init__(self, audit_run):
        self._run = audit_run
        self.risk_score   = float(audit_run.risk_score or 0)
        self.risk_level   = audit_run.risk_level or "low"
        self.escalate     = audit_run.blocks_approval or audit_run.requires_manual_review
        self.passed_rules = audit_run.passed_rules
        self.failed_rules = audit_run.failed_rules
        self.warning_rules = audit_run.warning_rules
        self.audit_run_id = str(audit_run.id)

    @classmethod
    def from_audit_run(cls, audit_run) -> "AuditRunResult":
        return cls(audit_run)

    # Legacy consumers check report.escalate, report.risk_level, report.risk_score
    def __repr__(self) -> str:
        return (
            f"AuditRunResult(run={self.audit_run_id} "
            f"risk={self.risk_score} level={self.risk_level} "
            f"escalate={self.escalate})"
        )


# ── Adapter 2: apps.auditing.services.audit_processing_service ────────────────

class LegacyAuditProcessingServiceAdapter:
    """
    Drop-in replacement for AuditProcessingService.

    Accepts an AuditDocument, resolves document_type from its category,
    and routes to AuditPipelineV2 via run_audit_compat.

    Usage (replace existing AuditProcessingService instantiation):

        # Before:
        service = AuditProcessingService()
        service.process(doc)

        # After:
        service = LegacyAuditProcessingServiceAdapter()
        service.process(doc)
    """

    CATEGORY_TO_DOC_TYPE = {
        "invoice":         "sales_invoice",
        "purchase_order":  "purchase_order",
        "bank_statement":  "bank_statement",
        "payroll":         "payroll",
        "expense":         "expense",
        "tax_return":      "tax_return",
        "fixed_asset":     "fixed_asset",
        "sales_receipt":   "sales_receipt",
        "grn":             "grn",
        "payment":         "payment",
    }

    def __init__(self):
        warnings.warn(
            "LegacyAuditProcessingServiceAdapter wraps the deprecated "
            "AuditProcessingService. Migrate to AuditPipelineV2 directly.",
            DeprecationWarning,
            stacklevel=2,
        )

    def process(self, doc):
        """
        Process an AuditDocument through V2 pipeline.
        Returns the doc unchanged (V2 persists results to AuditRun, not AuditDocument).
        """
        try:
            document_type = self._resolve_doc_type(doc)
            org_id = str(
                getattr(doc, "organization_id", None)
                or getattr(getattr(doc, "organization", None), "id", None)
            )
            doc_id = str(doc.pk)

            from apps.rule_engine.pipeline.v2.compat import run_audit_compat
            audit_run = run_audit_compat(
                document_id=doc_id,
                document_type=document_type,
                organization_id=org_id,
                triggered_by="legacy_processing_service",
            )
            logger.info(
                "[legacy_adapter] AuditProcessingService.process() → "
                "V2 run=%s risk=%s/%s",
                audit_run.id,
                getattr(audit_run, "risk_score", "?"),
                getattr(audit_run, "risk_level", "?"),
            )
        except Exception as exc:
            logger.exception(
                "[legacy_adapter] AuditProcessingService.process() failed "
                "for doc=%s: %s", getattr(doc, "pk", "?"), exc
            )
        return doc

    def _resolve_doc_type(self, doc) -> str:
        """Resolve canonical document_type from AuditDocument.category."""
        category = (
            getattr(doc, "document_type", None)
            or getattr(doc, "category", None)
            or "other"
        )
        return self.CATEGORY_TO_DOC_TYPE.get(str(category).lower(), "other")


# ── Adapter 3: apps.audit_engine.services.orchestrator.AuditOrchestrator ──────

class LegacyAuditOrchestratorAdapter:
    """
    Drop-in replacement for AuditOrchestrator.

    Accepts an AuditJob, extracts document info, and routes to V2.
    Returns the AuditJob with status updated to COMPLETED.

    Usage:
        # Before:
        orchestrator = AuditOrchestrator()
        orchestrator.run(audit_job)

        # After:
        orchestrator = LegacyAuditOrchestratorAdapter()
        orchestrator.run(audit_job)
    """

    def __init__(self):
        warnings.warn(
            "LegacyAuditOrchestratorAdapter wraps the deprecated "
            "AuditOrchestrator. Migrate to AuditPipelineV2 directly.",
            DeprecationWarning,
            stacklevel=2,
        )

    def run(self, audit_job):
        """
        Execute V2 pipeline for the given AuditJob.
        Updates AuditJob status and returns it.
        """
        try:
            from apps.rule_engine.pipeline.v2.compat import run_audit_compat
            audit_run = run_audit_compat(
                document_id=str(audit_job.document_id),
                document_type=getattr(audit_job, "document_type", "other"),
                organization_id=str(audit_job.organization_id),
                triggered_by="legacy_orchestrator",
            )

            # Update AuditJob status to mirror the V2 result
            try:
                audit_job.status = "completed"
                audit_job.save(update_fields=["status"])
            except Exception:
                pass

            logger.info(
                "[legacy_adapter] AuditOrchestrator.run() → "
                "V2 run=%s risk=%s/%s",
                audit_run.id,
                getattr(audit_run, "risk_score", "?"),
                getattr(audit_run, "risk_level", "?"),
            )
        except Exception as exc:
            logger.exception(
                "[legacy_adapter] AuditOrchestrator.run() failed "
                "for job=%s: %s", getattr(audit_job, "id", "?"), exc
            )
            try:
                audit_job.status = "failed"
                audit_job.save(update_fields=["status"])
            except Exception:
                pass

        return audit_job


# ── Convenience function: mirrors apps.audit.audit_engine.run_audit ───────────

def run_audit_compat_legacy(
    document: dict,
    organization_id=None,
    invoice_id=None,
    context: Optional[dict] = None,
    persist: bool = True,
    invoice=None,
    created_by=None,
):
    """
    Drop-in replacement for apps.audit.audit_engine.run_audit().

    Accepts the same keyword arguments as the original convenience function
    and routes to AuditPipelineV2 via run_audit_compat.

    Returns an AuditRunResult (duck-type compatible with AuditReport).
    """
    doc_id = invoice_id or (invoice.pk if invoice else None)
    org_id = organization_id or (
        invoice.organization_id if invoice else None
    )
    if not doc_id or not org_id:
        raise ValueError(
            "run_audit_compat_legacy() requires invoice_id (or invoice) "
            "and organization_id."
        )

    from apps.rule_engine.pipeline.v2.compat import run_audit_compat
    audit_run = run_audit_compat(
        document_id=str(doc_id),
        document_type="sales_invoice",
        organization_id=str(org_id),
        triggered_by="legacy_run_audit",
    )
    return AuditRunResult.from_audit_run(audit_run)
