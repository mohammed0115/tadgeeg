"""
RiskEngineStage — Stage 4 of AuditPipeline V2.

Computes an enriched risk assessment by running a modifier chain on top of
the base score produced by the existing RiskAggregator.

Modifier chain (applied in order):
  1. BaseRiskModifier      wraps RiskAggregator (rule-based 0–100 score)
  2. VendorRiskModifier    inflates score for unapproved / unknown vendors
  3. FrequencyModifier     inflates score for unusual document frequency
  4. ERPContextModifier    inflates score when amount exceeds ERP budget

Each modifier returns an updated risk_data dict; modifiers are independent
and failures degrade gracefully (logged, skipped).

Populates:  context.risk_data
Also:       persists risk_score/risk_level back to AuditRun and upserts
            the RiskScoreSummary record.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.rule_engine.pipeline.stages.base import BaseStage
from apps.rule_engine.risk.risk_aggregator import RiskAggregator

if TYPE_CHECKING:
    from apps.rule_engine.pipeline.v2.context import PipelineContext

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["RiskEngineStage"]


# ── Modifier classes ───────────────────────────────────────────────────────────

class BaseRiskModifier:
    """Computes baseline risk from rule results via RiskAggregator."""

    def apply(self, risk_data: dict, context: "PipelineContext") -> dict:
        aggregator = RiskAggregator()
        return aggregator.compute(
            context.rule_results,
            context.rule_assignments,
            normalized_doc=context.normalized_doc,
            vendor_context=getattr(context, "vendor_context", {}),
            history_context=getattr(context, "history_context", {}),
            erp_context=getattr(context, "erp_context", {}),
        )


class VendorRiskModifier:
    """
    Inflates risk when the vendor is unknown, unapproved, or flagged.

      unknown vendor   → +5 pts
      unapproved       → +15 pts
      vendor flags     → +10 pts per flag (capped at +20 pts)
    """

    def apply(self, risk_data: dict, context: "PipelineContext") -> dict:
        vendor = context.vendor_context
        if not vendor:
            return risk_data

        adjustment = 0.0
        reasons = []

        if vendor.get("is_approved") is False:
            adjustment += 15.0
            reasons.append("unapproved_vendor")
        elif vendor.get("is_approved") is None:
            adjustment += 5.0
            reasons.append("unknown_vendor")

        flags = vendor.get("flags", [])
        if flags:
            adjustment += min(len(flags) * 10.0, 20.0)
            reasons.append(f"vendor_flags:{','.join(str(f) for f in flags)}")

        if adjustment > 0:
            risk_data = _apply_adjustment(risk_data, adjustment, reasons)

        return risk_data


class FrequencyModifier:
    """
    Inflates risk when an unusually high number of documents has been
    processed for the same org/type pair within the lookback window.
    """

    HIGH_FREQUENCY_THRESHOLD = 50  # runs within lookback window

    def apply(self, risk_data: dict, context: "PipelineContext") -> dict:
        history = context.history_context
        count = history.get("recent_run_count", 0)
        if count >= self.HIGH_FREQUENCY_THRESHOLD:
            reason = (
                f"high_frequency:{count}_docs_in_"
                f"{history.get('lookback_days', 90)}d"
            )
            risk_data = _apply_adjustment(risk_data, 10.0, [reason])
        return risk_data


class ERPContextModifier:
    """
    Inflates risk when the document amount exceeds the ERP budget limit.
    """

    def apply(self, risk_data: dict, context: "PipelineContext") -> dict:
        erp = context.erp_context
        doc = context.normalized_doc
        if not erp or not doc:
            return risk_data

        budget_limit = erp.get("budget_limit") or doc.budget_limit
        amount = doc.total_amount

        if budget_limit and amount:
            try:
                if float(amount) > float(budget_limit):
                    risk_data = _apply_adjustment(
                        risk_data, 20.0, ["amount_exceeds_erp_budget"]
                    )
            except (TypeError, ValueError):
                pass

        return risk_data


class AnomalyModifier:
    """
    Runs statistical anomaly detection (z-score, IQR, duplicate patterns,
    frequency analysis, vendor checks) and merges findings into risk_data.

    Contributions
    -------------
      anomaly_score ≥ 70  → additional +15 pts on the composite risk score
      anomaly_score ≥ 40  → additional +8 pts
      anomaly findings    → stored in risk_data["anomaly_findings"] so that
                            RiskScoreSummary.fraud_indicators is populated
      score_breakdown     → anomaly_score / anomaly_explanation / anomaly_flags
                            written for ReportService aggregation
    """

    def apply(self, risk_data: dict, context: "PipelineContext") -> dict:
        doc = context.normalized_doc
        if not doc:
            return risk_data

        try:
            from apps.rule_engine.anomaly.detector import AnomalyDetector

            result = AnomalyDetector().detect_with_db_history(
                doc=doc,
                history_context=getattr(context, "history_context", {}),
                vendor_context=getattr(context, "vendor_context", {}),
            )

            # Merge anomaly data into score_breakdown for ReportService
            breakdown = dict(risk_data.get("score_breakdown", {}))
            breakdown.update({
                "anomaly_score":       result.anomaly_score,
                "anomaly_explanation": result.explanation,
                "anomaly_flags": [
                    f["code"] for f in result.findings
                ],
            })
            risk_data = dict(risk_data)
            risk_data["score_breakdown"]   = breakdown
            risk_data["anomaly_findings"]  = result.findings
            risk_data["anomaly_methods"]   = result.methods_used
            risk_data["anomaly_score"]     = result.anomaly_score
            risk_data["anomaly_explanation"] = result.explanation

            # Inflate the composite risk score based on anomaly severity
            if result.anomaly_score >= 70:
                risk_data = _apply_adjustment(
                    risk_data, 15.0, [f"anomaly_high:{result.anomaly_score:.0f}"]
                )
            elif result.anomaly_score >= 40:
                risk_data = _apply_adjustment(
                    risk_data, 8.0, [f"anomaly_moderate:{result.anomaly_score:.0f}"]
                )

            logger.info(
                "[risk_engine] Anomaly score=%.1f findings=%d methods=%s",
                result.anomaly_score,
                len(result.findings),
                result.methods_used,
            )
        except Exception as exc:
            logger.warning("[risk_engine] AnomalyModifier failed (skipped): %s", exc)

        return risk_data


# ── Stage ──────────────────────────────────────────────────────────────────────

class RiskEngineStage(BaseStage):
    """
    Runs the modifier chain and persists enriched risk data.
    Populates: context.risk_data
    """

    name = "risk_engine"

    # Instantiate modifiers once at class level (they are stateless).
    # Execution order matters: BaseRiskModifier must run first so subsequent
    # modifiers can adjust the already-computed baseline score.
    _MODIFIER_CHAIN = [
        BaseRiskModifier(),
        AnomalyModifier(),
        VendorRiskModifier(),
        FrequencyModifier(),
        ERPContextModifier(),
    ]

    def _run(self, context: "PipelineContext") -> "PipelineContext":
        risk_data: dict = {}

        for modifier in self._MODIFIER_CHAIN:
            try:
                risk_data = modifier.apply(risk_data, context)
            except Exception as exc:
                logger.warning(
                    "[risk_engine] Modifier %s failed (skipped): %s",
                    type(modifier).__name__, exc,
                )

        context.risk_data = risk_data
        self._persist(context, risk_data)

        logger.info(
            "[risk_engine] score=%.1f level=%s blocks_approval=%s manual_review=%s",
            risk_data.get("risk_score", 0),
            risk_data.get("risk_level", "?"),
            risk_data.get("blocks_approval", False),
            risk_data.get("requires_manual_review", False),
        )
        return context

    @staticmethod
    def _persist(context: "PipelineContext", risk_data: dict) -> None:
        from apps.rule_engine.models import AuditRun, RiskScoreSummary
        try:
            audit_run = AuditRun.objects.get(id=context.audit_run_id)
            audit_run.risk_score = risk_data.get("risk_score")
            audit_run.risk_level = risk_data.get("risk_level")
            audit_run.requires_manual_review = risk_data.get("requires_manual_review", False)
            audit_run.blocks_approval = risk_data.get("blocks_approval", False)
            audit_run.save(update_fields=[
                "risk_score", "risk_level",
                "requires_manual_review", "blocks_approval",
            ])

            try:
                from apps.invoices.services.vendor_intelligence import VendorIntelligenceService
                VendorIntelligenceService().update_after_audit(context.normalized_doc, risk_data)
            except Exception as exc:
                logger.warning("[risk_engine] Vendor intelligence update skipped: %s", exc)

            RiskScoreSummary.objects.update_or_create(
                document_id=context.document_id,
                defaults={
                    "organization_id": context.organization_id,
                    "document_type": context.document_type,
                    "latest_audit_run": audit_run,
                    "risk_score": risk_data.get("risk_score"),
                    "risk_level": risk_data.get("risk_level"),
                    "fraud_indicators": len(risk_data.get("anomaly_findings", [])),
                    "blocking_failures": sum(
                        1 for r in context.rule_results
                        if getattr(r, "status", "") == "fail"
                        and getattr(r, "blocks_approval", False)
                    ),
                    "compliance_failures": sum(
                        1 for r in context.rule_results
                        if getattr(r, "status", "") == "fail"
                    ),
                    "requires_manual_review": risk_data.get("requires_manual_review", False),
                    "blocks_approval": risk_data.get("blocks_approval", False),
                    "score_breakdown": risk_data.get("score_breakdown", {}),
                    "top_failed_rules": risk_data.get("top_failed_rules", []),
                },
            )
        except Exception as exc:
            logger.error("[risk_engine] Failed to persist risk data: %s", exc)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _apply_adjustment(risk_data: dict, adjustment: float, reasons: list) -> dict:
    """Return a new risk_data dict with score and level recalculated."""
    risk_data = dict(risk_data)
    new_score = min(float(risk_data.get("risk_score", 0)) + adjustment, 100.0)
    risk_data["risk_score"] = round(new_score, 2)
    risk_data["risk_level"] = _score_to_level(new_score)
    risk_data.setdefault("modifier_reasons", []).extend(reasons)
    # Recalculate derived flags
    risk_data["requires_manual_review"] = new_score >= 50
    # Blocking stays attributable to a named rule.
    #
    # The base engine (risk/risk_engine.py) sets blocks_approval in exactly
    # three places, and all three are rule failures: a rule marked
    # blocks_approval that failed (:890), a critical-severity failure (:926),
    # and triggers_critical_override (:802). There is no score threshold
    # anywhere in it — `grep -c ">= 75"` returns 0.
    #
    # This line added a fourth path that blocked on the total. It could
    # therefore produce a blocked document with no failing rule to point at,
    # and the auditor who has to justify the refusal has nothing to cite.
    # A modifier is a ranking signal, not a finding.
    #
    # What still works: risk_score and risk_level continue to move, so risk
    # ordering keeps improving, and requires_manual_review still fires on
    # score — review is not a block. CTO decision, shipment 5 §1, option (a).
    return risk_data


def _score_to_level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"
