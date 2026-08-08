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
    """Wrapper around ``AuditRun`` that satisfies the legacy ``AuditReport`` contract.

    **Why this exists and why it was incomplete.** Two independent callers read a
    report object, and they read different fields:

      * ``apps/audit/tasks.py``      — risk_score, risk_level, escalate
      * ``core/services/pipeline.py`` — the three above PLUS total_rules,
        passed_count, failed_count, skipped_count, error_count,
        processing_time_ms, summary, rule_results

    This class was written against the first caller and labelled a "drop-in
    replacement". It was not one: substituting it into ``pipeline.py`` raised
    ``AttributeError`` on seven fields. The docstring claimed Liskov
    substitutability and the code did not provide it.

    The contract is now enforced by ``tests/test_adapter_contract.py``, which
    walks every field every caller reads. If a caller starts reading an eighth
    field, that test fails before production does.

    **Naming.** ``passed_rules`` (the AuditRun column name) and ``passed_count``
    (the legacy AuditReport attribute name) are BOTH exposed and hold the same
    value. Renaming either one breaks a working caller, and an alias costs
    nothing.
    """

    #: Statuses in ``AuditResult.status`` that count as a pass. Kept explicit
    #: rather than derived, because ``apps.rule_engine`` and ``apps.audit`` use
    #: different casings for the same words — see apps/audit_platform/status.py.
    _PASSED_STATUSES = ("pass", "passed")

    def __init__(self, audit_run):
        self._run = audit_run

        # ── Original fields — unchanged, read by apps/audit/tasks.py ─────────
        self.risk_score = float(audit_run.risk_score or 0)
        self.risk_level = audit_run.risk_level or "low"
        self.escalate = bool(
            audit_run.blocks_approval or audit_run.requires_manual_review
        )
        self.passed_rules = audit_run.passed_rules
        self.failed_rules = audit_run.failed_rules
        self.warning_rules = audit_run.warning_rules
        self.audit_run_id = str(audit_run.id)

        # ── Added: counts read by core/services/pipeline.py ─────────────────
        # AuditRun already stores all of these. Nothing is computed or guessed.
        self.total_rules = audit_run.total_rules
        self.passed_count = audit_run.passed_rules
        self.failed_count = audit_run.failed_rules
        self.skipped_count = audit_run.skipped_rules
        self.error_count = audit_run.error_rules
        self.warning_count = audit_run.warning_rules

        # ── Added: timing ───────────────────────────────────────────────────
        self.processing_time_ms = self._resolve_processing_ms(audit_run)

        # ── Added: summary ──────────────────────────────────────────────────
        self.summary = (
            f"{audit_run.failed_rules} failed, "
            f"{audit_run.warning_rules} warning, "
            f"{audit_run.passed_rules} passed "
            f"of {audit_run.total_rules} rules "
            f"(risk {self.risk_score:.1f} / {self.risk_level})"
        )

        # ── Added: per-rule results ─────────────────────────────────────────
        # Lazy: pipeline.py iterates report.rule_results, but tasks.py never
        # touches it. Loading the rows eagerly would add a query to a caller
        # that has no use for them.
        self._rule_results = None

    # ── rule_results ────────────────────────────────────────────────────────

    @property
    def rule_results(self):
        """Per-rule results shaped like the legacy ``RuleResult`` objects.

        ``_serialise_audit_report`` in core/services/pipeline.py reads
        ``r.rule_id``, ``r.rule_name``, ``r.severity``, ``r.result``,
        ``r.explanation`` and ``r.details`` off each item, and calls
        ``.value`` on severity/result when present. Plain strings are returned,
        so the ``hasattr(..., "value")`` branch falls through to ``str()`` —
        which is what it is there for.
        """
        if self._rule_results is None:
            self._rule_results = [
                _LegacyRuleResultView(row)
                for row in self._run.results.all().order_by("executed_at", "rule_code")
            ]
        return self._rule_results

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_processing_ms(audit_run) -> int:
        """Milliseconds the run took.

        Preferred source is the V2 metadata sidecar's ``stage_timings``; falls
        back to ``completed_at - started_at``; returns 0 when neither is
        available. Returns 0 rather than None because pipeline.py writes this
        straight into a JSON payload the UI renders — ``None`` there shows as an
        empty duration, which reads as "instant" rather than "unknown".
        """
        try:
            meta = getattr(audit_run, "v2_metadata", None)
            timings = getattr(meta, "stage_timings", None) if meta else None
            if isinstance(timings, dict) and timings:
                total = sum(
                    float(v) for v in timings.values()
                    if isinstance(v, (int, float))
                )
                if total > 0:
                    return int(round(total))
        except Exception:  # noqa: BLE001 — a timing figure must never break a run
            pass

        started = getattr(audit_run, "started_at", None)
        completed = getattr(audit_run, "completed_at", None)
        if started and completed:
            return int(round((completed - started).total_seconds() * 1000))
        return 0

    @classmethod
    def from_audit_run(cls, audit_run) -> "AuditRunResult":
        return cls(audit_run)

    def __repr__(self) -> str:
        return (
            f"AuditRunResult(run={self.audit_run_id} "
            f"risk={self.risk_score} level={self.risk_level} "
            f"escalate={self.escalate} "
            f"rules={self.failed_count}F/{self.total_rules}T)"
        )


class _LegacyRuleResultView:
    """Read-only view of an ``AuditResult`` row in the legacy ``RuleResult`` shape.

    Deliberately not the model: a caller handed the row could save it, mutate
    it, or follow a relation this adapter never meant to expose — and then the
    adapter is a suggestion rather than a boundary. Same reasoning as the frozen
    result in apps/rule_engine/services/audit_facade.py.
    """

    __slots__ = ("rule_id", "rule_name", "severity", "result", "explanation", "details")

    def __init__(self, row):
        self.rule_id = row.rule_code
        self.rule_name = row.rule_code          # AuditResult stores no display name
        self.severity = row.applied_severity
        self.result = row.status
        self.explanation = row.explanation or ""
        self.details = row.raw_output or {}


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
