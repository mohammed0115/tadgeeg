"""
DecisionEngineStage — Stage 6 (final) of AuditPipeline V2.

Synthesises all upstream signals — rule results, risk score, AI insights,
and enriched context — into a single authoritative Decision.

Decision fields
---------------
  action          "approve" | "flag" | "review" | "reject"
  confidence      float 0–1
  auto_action     bool — True when the action can be taken automatically
                  (e.g. approve on clean pass, reject on blocking rule failure)
  escalate_to     None | "manager" | "auditor" | "compliance_team"
  reasoning       ordered list of factor dicts that drove the decision
  blocking_rules  rule codes that explicitly blocked approval
  risk_snapshot   compact copy of risk_data for audit trail
  ai_snapshot     compact copy of ai_insights for audit trail

Priority order (first match wins):
  1. Blocking rule failure     → reject  (auto, compliance_team)
  2. Critical risk score       → reject  (manual, auditor)
  3. High risk + AI signals    → review  (manual, auditor)
  4. requires_manual_review    → flag    (manual, manager)
  5. AI recommends review/flag → flag    (manual, manager)
  6. All clear                 → approve (auto)

Populates: context.decision
Also:       persists a compact decision summary to AuditRunV2Metadata.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.rule_engine.pipeline.stages.base import BaseStage

if TYPE_CHECKING:
    from apps.rule_engine.pipeline.v2.context import PipelineContext

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["DecisionEngineStage"]


# ── Decision policy ────────────────────────────────────────────────────────────

class DecisionPolicy:
    """
    Pure function: evaluates context → decision dict.
    No DB access; fully testable in isolation.
    """

    @staticmethod
    def evaluate(context: "PipelineContext") -> dict:
        risk = context.risk_data
        ai   = context.ai_insights

        blocking_rules = [
            r.rule_code
            for r in context.rule_results
            if getattr(r, "status", "") == "fail"
            and getattr(r, "blocks_approval", False)
        ]

        reasoning: list = []
        action      = "approve"
        confidence  = 0.9
        auto_action = True
        escalate_to = None

        # ── Priority 1: Approval-blocking rule failure ─────────────────────
        if blocking_rules:
            action      = "reject"
            auto_action = True     # system-enforced; no human needed to confirm
            confidence  = 1.0
            escalate_to = "compliance_team"
            reasoning.append({
                "factor":  "blocking_rule_failure",
                "detail":  f"Approval blocked by rules: {', '.join(blocking_rules)}",
                "weight":  1.0,
            })

        # ── Priority 2: Critical risk score ───────────────────────────────
        elif risk.get("risk_level") == "critical":
            action      = "reject"
            auto_action = False    # critical → human sign-off required
            confidence  = 0.95
            escalate_to = "auditor"
            reasoning.append({
                "factor": "critical_risk_score",
                "detail": (
                    f"Risk score={risk.get('risk_score', 0):.1f} "
                    f"meets critical threshold (≥75)"
                ),
                "weight": 0.95,
            })

        # ── Priority 3: High risk + AI anomaly signals ─────────────────────
        elif (risk.get("risk_level") == "high"
              and len(ai.get("anomaly_signals", [])) >= 1):
            action      = "review"
            auto_action = False
            confidence  = ai.get("confidence", 0.75)
            escalate_to = "auditor"
            reasoning.append({
                "factor": "high_risk_with_ai_signals",
                "detail": (
                    f"High risk (score={risk.get('risk_score', 0):.1f}) with "
                    f"{len(ai.get('anomaly_signals', []))} AI anomaly signal(s)"
                ),
                "weight": 0.85,
            })

        # ── Priority 4: Manual review threshold breached ──────────────────
        elif risk.get("requires_manual_review"):
            action      = "flag"
            auto_action = False
            confidence  = 0.70
            escalate_to = "manager"
            reasoning.append({
                "factor": "manual_review_required",
                "detail": (
                    f"Risk score={risk.get('risk_score', 0):.1f} "
                    f"exceeds manual-review threshold (≥50)"
                ),
                "weight": 0.70,
            })

        # ── Priority 5: AI recommends review or flag ──────────────────────
        elif ai.get("recommended_action") in ("review", "flag"):
            action      = ai["recommended_action"]
            auto_action = False
            confidence  = ai.get("confidence", 0.60)
            escalate_to = "manager" if action == "flag" else "auditor"
            reasoning.append({
                "factor": "ai_recommendation",
                "detail": (
                    f"AI recommends '{action}' "
                    f"(confidence={confidence:.2f}, "
                    f"provider={ai.get('ai_provider', 'unknown')})"
                ),
                "weight": confidence,
            })

        # ── Priority 6: Clean pass ────────────────────────────────────────
        else:
            reasoning.append({
                "factor": "all_checks_passed",
                "detail": (
                    f"risk={risk.get('risk_level', 'low')} "
                    f"(score={risk.get('risk_score', 0):.1f}), "
                    f"no blocking failures, no AI anomalies"
                ),
                "weight": 0.9,
            })

        # Append any risk-modifier reasons as supplementary context
        for mod_reason in risk.get("modifier_reasons", []):
            reasoning.append({
                "factor": "risk_modifier",
                "detail": mod_reason,
                "weight": 0.3,
            })

        return {
            "action":          action,
            "confidence":      round(float(confidence), 3),
            "auto_action":     auto_action,
            "escalate_to":     escalate_to,
            "reasoning":       reasoning,
            "blocking_rules":  blocking_rules,
            "risk_snapshot": {
                "score": risk.get("risk_score"),
                "level": risk.get("risk_level"),
            },
            "ai_snapshot": {
                "recommended_action": ai.get("recommended_action"),
                "confidence":         ai.get("confidence"),
                "signals_count":      len(ai.get("anomaly_signals", [])),
                "provider":           ai.get("ai_provider"),
            },
        }


# ── Stage ──────────────────────────────────────────────────────────────────────

class DecisionEngineStage(BaseStage):
    """
    Evaluates DecisionPolicy and persists the decision to AuditRunV2Metadata.
    """

    name = "decision_engine"

    def _run(self, context: "PipelineContext") -> "PipelineContext":
        context.decision = DecisionPolicy.evaluate(context)
        self._persist(context)

        logger.info(
            "[decision_engine] action=%s confidence=%.2f auto=%s escalate=%s",
            context.decision["action"],
            context.decision["confidence"],
            context.decision["auto_action"],
            context.decision["escalate_to"],
        )
        return context

    @staticmethod
    def _persist(context: "PipelineContext") -> None:
        """Persist decision + AI insights to AuditRunV2Metadata."""
        try:
            from apps.rule_engine.models.audit_run_v2 import AuditRunV2Metadata
            from apps.rule_engine.models import AuditRun

            audit_run = AuditRun.objects.get(id=context.audit_run_id)
            AuditRunV2Metadata.objects.update_or_create(
                audit_run=audit_run,
                defaults={
                    "decision":        context.decision,
                    "ai_insights":     context.ai_insights,
                    "context_summary": context.to_meta_dict(),
                    "stage_timings":   context.stage_timings,
                    "stage_errors":    context.stage_errors,
                    "stages_skipped":  context.stages_skipped,
                    "pipeline_version": context.pipeline_version,
                },
            )
        except Exception as exc:
            logger.warning(
                "[decision_engine] Failed to persist V2 metadata: %s", exc
            )
