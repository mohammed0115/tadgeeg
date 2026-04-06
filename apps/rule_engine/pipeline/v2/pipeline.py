"""
AuditPipelineV2 — Unified, modular audit pipeline.

Stage execution order
---------------------
  1. DocumentNormalizerStage  (CriticalStage — aborts on failure)
  2. ContextBuilderStage      (BaseStage     — failure logged, pipeline continues)
  2.5 ThreeWayMatchStage      (BaseStage     — skipped for non-procurement types)
  3. RuleEngineStage          (CriticalStage — aborts on failure)
  4. RiskEngineStage          (BaseStage     — failure logged)
  5. AIEngineStage            (BaseStage     — skipped for low-risk docs)
  6. DecisionEngineStage      (BaseStage     — failure logged)

Idempotency
-----------
Two calls for the same (document_id, document_type, organization_id) within
IDEMPOTENCY_WINDOW_SECONDS return the existing completed run without
re-executing. Override with force_rerun=True or triggered_by="reprocess".

The engine_version field on AuditRun is set to PIPELINE_ENGINE_VERSION ("3.0")
so V1 and V2 runs are distinguishable in the database.

Async usage
-----------
    from apps.rule_engine.tasks.audit_tasks_v2 import run_audit_v2_task
    run_audit_v2_task.delay(document_id, document_type, organization_id)

Sync usage
----------
    from apps.rule_engine.pipeline.v2.pipeline import AuditPipelineV2
    pipeline = AuditPipelineV2()
    audit_run = pipeline.run(document_id, document_type, organization_id)

Drop-in migration
-----------------
    from apps.rule_engine.pipeline.v2.compat import run_audit_compat
    audit_run = run_audit_compat(document_id, document_type, organization_id)
"""
from __future__ import annotations

import logging
import traceback as tb
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from apps.rule_engine.models import AuditRun
from apps.rule_engine.pipeline.v2.context import PipelineContext
from apps.rule_engine.pipeline.stages.normalizer         import DocumentNormalizerStage
from apps.rule_engine.pipeline.stages.context_builder    import ContextBuilderStage
from apps.rule_engine.pipeline.stages.three_way_match_stage import ThreeWayMatchStage
from apps.rule_engine.pipeline.stages.rule_engine        import RuleEngineStage
from apps.rule_engine.pipeline.stages.risk_engine        import RiskEngineStage
from apps.rule_engine.pipeline.stages.ai_engine          import AIEngineStage
from apps.rule_engine.pipeline.stages.decision_engine    import DecisionEngineStage

logger = logging.getLogger("rule_engine.pipeline")

PIPELINE_ENGINE_VERSION    = "3.0"
IDEMPOTENCY_WINDOW_SECONDS = 3_600   # 1 hour

__all__ = ["AuditPipelineV2"]


class AuditPipelineV2:
    """
    Main orchestrator for the V2 audit pipeline.

    Instantiation is cheap and safe across threads — all per-run state
    lives in PipelineContext, not on the pipeline instance.
    """

    # Override in tests to inject mock stages.
    STAGE_CLASSES = [
        DocumentNormalizerStage,
        ContextBuilderStage,
        ThreeWayMatchStage,      # Stage 2.5 — procurement triplet resolution
        RuleEngineStage,
        RiskEngineStage,
        AIEngineStage,
        DecisionEngineStage,
    ]

    def __init__(self) -> None:
        self._stages = [cls() for cls in self.STAGE_CLASSES]

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(
        self,
        document_id: str,
        document_type: str,
        organization_id: str,
        triggered_by: str = "upload",
        force_rerun: bool = False,
        dry_run: bool = False,
    ) -> AuditRun:
        """
        Execute the full pipeline and return the completed AuditRun.

        Parameters
        ----------
        document_id       UUID of the document to audit.
        document_type     Registered document type string.
        organization_id   UUID of the owning organisation.
        triggered_by      "upload" | "manual" | "scheduled" | "reprocess"
        force_rerun       Bypass idempotency guard (always creates a new run).
        dry_run           Skip all DB writes; useful for smoke-testing.
        """
        ctx = PipelineContext(
            document_id=str(document_id),
            document_type=document_type,
            organization_id=str(organization_id),
            triggered_by=triggered_by,
            force_rerun=force_rerun,
            is_dry_run=dry_run,
            pipeline_version=PIPELINE_ENGINE_VERSION,
        )

        logger.info(
            "[pipeline_v2] Starting — doc=%s type=%s org=%s trigger=%s dry=%s",
            document_id, document_type, organization_id, triggered_by, dry_run,
        )

        # ── Idempotency guard ───────────────────────────────────────────────
        if not force_rerun and triggered_by != "reprocess":
            existing = self._find_existing_run(ctx)
            if existing:
                logger.info(
                    "[pipeline_v2] Returning existing run %s (idempotency guard).",
                    existing.id,
                )
                return existing

        # ── Create AuditRun ─────────────────────────────────────────────────
        audit_run: Optional[AuditRun] = None
        if not dry_run:
            audit_run = AuditRun.objects.create(
                organization_id=organization_id,
                document_type=document_type,
                document_id=document_id,
                triggered_by=triggered_by,
                status=AuditRun.Status.RUNNING,
                engine_version=PIPELINE_ENGINE_VERSION,
                started_at=timezone.now(),
            )
            ctx.audit_run_id = str(audit_run.id)
            logger.info("[pipeline_v2] Created AuditRun %s.", audit_run.id)

        # ── Execute stages ──────────────────────────────────────────────────
        try:
            for stage in self._stages:
                ctx = stage.execute(ctx)

            if audit_run and not dry_run:
                audit_run.status = AuditRun.Status.COMPLETED
                audit_run.completed_at = timezone.now()
                audit_run.processing_time_ms = int(
                    (audit_run.completed_at - audit_run.started_at).total_seconds() * 1000
                )
                audit_run.save(update_fields=[
                    "status", "completed_at", "processing_time_ms",
                ])

            logger.info(
                "[pipeline_v2] Completed — run=%s risk=%s/%s decision=%s "
                "total_ms=%d stage_errors=%s",
                ctx.audit_run_id,
                ctx.risk_data.get("risk_score", "?"),
                ctx.risk_data.get("risk_level", "?"),
                ctx.decision.get("action", "?"),
                sum(ctx.stage_timings.values()),
                list(ctx.stage_errors.keys()) or "none",
            )

        except Exception as exc:
            if audit_run and not dry_run:
                audit_run.status = AuditRun.Status.FAILED
                audit_run.error_log = [{"error": str(exc), "traceback": tb.format_exc()}]
                audit_run.completed_at = timezone.now()
                audit_run.save(update_fields=["status", "error_log", "completed_at"])
            logger.exception(
                "[pipeline_v2] Fatal error for document %s: %s", document_id, exc
            )
            raise

        return audit_run  # type: ignore[return-value]

    # ── Idempotency ─────────────────────────────────────────────────────────────

    @staticmethod
    def _find_existing_run(ctx: PipelineContext) -> Optional[AuditRun]:
        """
        Return a recent completed V2 run for the same document if one exists
        within the idempotency window, else None.
        """
        cutoff = timezone.now() - timedelta(seconds=IDEMPOTENCY_WINDOW_SECONDS)
        return (
            AuditRun.objects
            .filter(
                document_id=ctx.document_id,
                document_type=ctx.document_type,
                organization_id=ctx.organization_id,
                status=AuditRun.Status.COMPLETED,
                engine_version=PIPELINE_ENGINE_VERSION,
                completed_at__gte=cutoff,
            )
            .order_by("-completed_at")
            .first()
        )
