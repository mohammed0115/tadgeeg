"""
PipelineContext — shared mutable state that flows through all V2 pipeline stages.

Each stage reads from and writes to this object. It travels down the stage
chain carrying the full picture of what has been computed so far.

Design rules:
  - Stages MUTATE the context in place and return it (no copies).
  - All stage outputs are typed and documented here so the contract is explicit.
  - Helpers (.fingerprint, .to_meta_dict) keep orchestration logic out of stages.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    # Avoid circular import at runtime; used only for type checkers.
    from apps.rule_engine.rules.base import NormalizedDocument

__all__ = ["PipelineContext"]


@dataclass
class PipelineContext:
    # ── Input ──────────────────────────────────────────────────────────────────
    document_id: str
    document_type: str
    organization_id: str
    triggered_by: str = "upload"

    # Pipeline configuration
    is_dry_run: bool = False          # True → skip all DB writes (testing)
    pipeline_version: str = "3.0"    # written to AuditRun.engine_version
    force_rerun: bool = False         # True → bypass idempotency guard

    # ── Runtime state ──────────────────────────────────────────────────────────
    audit_run_id: Optional[str] = None   # set after AuditRun is created

    # ── Stage 1: DocumentNormalizerStage ───────────────────────────────────────
    normalized_doc: Optional[Any] = None   # NormalizedDocument instance

    # ── Stage 2: ContextBuilderStage ───────────────────────────────────────────
    vendor_context: dict = field(default_factory=dict)   # counterparty profile
    history_context: dict = field(default_factory=dict)  # past document runs
    erp_context: dict = field(default_factory=dict)      # budget / cost-centre

    # ── Stage 3: RuleEngineStage ────────────────────────────────────────────────
    rule_results: list = field(default_factory=list)      # list[AuditResult ORM]
    rule_assignments: list = field(default_factory=list)  # list[RuleAssignment ORM]

    # ── Stage 4: RiskEngineStage ────────────────────────────────────────────────
    risk_data: dict = field(default_factory=dict)

    # ── Stage 5: AIEngineStage ──────────────────────────────────────────────────
    ai_insights: dict = field(default_factory=dict)

    # ── Stage 6: DecisionEngineStage ────────────────────────────────────────────
    decision: dict = field(default_factory=dict)

    # ── Instrumentation ─────────────────────────────────────────────────────────
    stage_timings: dict = field(default_factory=dict)   # {stage_name: elapsed_ms}
    stage_errors: dict = field(default_factory=dict)    # {stage_name: error_str}
    stages_skipped: list = field(default_factory=list)  # [stage_name, ...]

    # ── Idempotency ─────────────────────────────────────────────────────────────

    @property
    def fingerprint(self) -> str:
        """
        Deterministic SHA-256 hash for deduplication.
        Two runs for the same document in the same org always produce the same
        fingerprint, regardless of triggered_by or timestamp.
        """
        raw = f"{self.document_id}:{self.document_type}:{self.organization_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def has_stage_error(self, stage_name: str) -> bool:
        return stage_name in self.stage_errors

    def mark_skipped(self, stage_name: str) -> None:
        if stage_name not in self.stages_skipped:
            self.stages_skipped.append(stage_name)

    def to_meta_dict(self) -> dict:
        """
        Serialisable summary stored in AuditRunV2Metadata.
        Contains instrumentation + enrichment context; NOT rule results
        (those live in AuditResult rows).
        """
        return {
            "pipeline_version": self.pipeline_version,
            "fingerprint": self.fingerprint,
            "triggered_by": self.triggered_by,
            "stage_timings": self.stage_timings,
            "stage_errors": self.stage_errors,
            "stages_skipped": self.stages_skipped,
            "total_elapsed_ms": sum(self.stage_timings.values()),
            "vendor_context": self.vendor_context,
            "history_context": self.history_context,
            "erp_context": self.erp_context,
        }
