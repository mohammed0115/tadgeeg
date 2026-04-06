"""
AuditRunV2Metadata — extended output record for AuditPipeline V2.

Stores AI insights, decision, context summary, and stage instrumentation
produced by the V2 pipeline as a OneToOne extension of AuditRun.

This model is deliberately separate from AuditRun so that:
  - V1 runs are unaffected (no new nullable columns on re_audit_run).
  - V2-specific data can be queried / deleted independently.
  - Schema evolution of AI/decision fields doesn't touch the core run table.
"""
import uuid

from django.db import models

from apps.rule_engine.models.audit_execution import AuditRun


class AuditRunV2Metadata(models.Model):
    """
    One-to-one extension of AuditRun for V2 pipeline outputs.
    Created by DecisionEngineStage at the end of every successful V2 run.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    audit_run = models.OneToOneField(
        AuditRun,
        on_delete=models.CASCADE,
        related_name="v2_metadata",
    )

    # ── Stage 5 output (AIEngineStage) ─────────────────────────────────────
    ai_insights = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structured output from AIEngineStage: anomaly_signals, narrative, "
            "confidence, recommended_action, ai_provider."
        ),
    )

    # ── Stage 6 output (DecisionEngineStage) ──────────────────────────────
    decision = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Final decision: action, confidence, auto_action, escalate_to, "
            "reasoning, blocking_rules, risk_snapshot, ai_snapshot."
        ),
    )

    # ── Context enrichment summary (ContextBuilderStage) ──────────────────
    context_summary = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Serialised PipelineContext.to_meta_dict(): pipeline_version, "
            "fingerprint, stage_timings, vendor/history/erp context."
        ),
    )

    # ── Pipeline instrumentation ───────────────────────────────────────────
    stage_timings = models.JSONField(
        default=dict,
        blank=True,
        help_text="Elapsed milliseconds per stage: {stage_name: ms}.",
    )
    stage_errors = models.JSONField(
        default=dict,
        blank=True,
        help_text="Errors swallowed by non-critical stages: {stage_name: error_str}.",
    )
    stages_skipped = models.JSONField(
        default=list,
        blank=True,
        help_text="List of stage names that were skipped (e.g. ai_engine for low-risk docs).",
    )

    pipeline_version = models.CharField(
        max_length=16,
        default="3.0",
        help_text="AuditPipelineV2 version string at time of execution.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "re_audit_run_v2_meta"
        verbose_name = "Audit Run V2 Metadata"
        verbose_name_plural = "Audit Run V2 Metadata"

    def __str__(self) -> str:
        action = (self.decision or {}).get("action", "?")
        return f"V2Meta[{self.audit_run_id}] action={action}"

    # ── Convenience accessors ──────────────────────────────────────────────

    @property
    def final_action(self) -> str:
        return (self.decision or {}).get("action", "unknown")

    @property
    def ai_provider(self) -> str:
        return (self.ai_insights or {}).get("ai_provider", "unknown")

    @property
    def total_elapsed_ms(self) -> int:
        return sum((self.stage_timings or {}).values())
