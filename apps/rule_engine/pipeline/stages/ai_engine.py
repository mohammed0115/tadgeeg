"""
AIEngineStage — Stage 5 of AuditPipeline V2.

Applies AI analysis to the audit context for documents that warrant deeper
investigation. Automatically skipped for low-risk documents to reduce cost.

Architecture
------------
The stage delegates to AIAnalysisService (heuristic, default) or
ClaudeAIAnalysisService (LLM-backed) based on the AUDIT_AI_PROVIDER
Django setting:

  AUDIT_AI_PROVIDER = "heuristic"  # default — no external API calls
  AUDIT_AI_PROVIDER = "claude"     # wire to Anthropic Claude API

Both services return the same structured dict so callers are provider-agnostic.

Output shape
------------
  anomaly_signals   list of detected anomaly dicts (type, detail, weight)
  narrative         plain-language summary of findings
  confidence        float 0–1
  recommended_action  "approve" | "flag" | "review" | "reject"
  ai_provider       string identifier for the engine used

Populates: context.ai_insights
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.rule_engine.pipeline.stages.base import BaseStage

if TYPE_CHECKING:
    from apps.rule_engine.pipeline.v2.context import PipelineContext

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["AIEngineStage"]


# ── Analysis services ──────────────────────────────────────────────────────────

class AIAnalysisService:
    """
    Default heuristic analysis service. Produces structured insights from
    already-computed context without calling any external API.
    """

    @staticmethod
    def analyse(context: "PipelineContext") -> dict:
        doc = context.normalized_doc
        risk = context.risk_data
        results = context.rule_results

        failed_rules = [
            {"code": r.rule_code, "severity": r.applied_severity}
            for r in results
            if getattr(r, "status", "") == "fail"
        ]

        anomaly_signals = []

        # Heuristic 1 — multiple critical failures
        critical_fails = [r for r in failed_rules if r["severity"] == "critical"]
        if len(critical_fails) >= 2:
            anomaly_signals.append({
                "type": "multiple_critical_failures",
                "detail": f"{len(critical_fails)} critical rule failures detected",
                "weight": 0.9,
            })

        # Heuristic 2 — large amount with unknown/unapproved vendor
        vendor = context.vendor_context
        if (doc and doc.total_amount
                and float(doc.total_amount) > 50_000
                and vendor.get("is_approved") is None):
            anomaly_signals.append({
                "type": "high_value_unknown_vendor",
                "detail": f"Amount={doc.total_amount} with unverified vendor",
                "weight": 0.75,
            })

        # Heuristic 3 — low OCR confidence on high-value transaction
        if (doc and doc.is_low_confidence(threshold=0.6)
                and doc.total_amount and float(doc.total_amount) > 10_000):
            anomaly_signals.append({
                "type": "low_ocr_confidence_high_value",
                "detail": (
                    f"OCR confidence={doc.ocr_confidence:.2f} "
                    f"on transaction of {doc.total_amount}"
                ),
                "weight": 0.6,
            })

        # Heuristic 4 — unusual document frequency
        history = context.history_context
        if history.get("recent_run_count", 0) > 30:
            anomaly_signals.append({
                "type": "unusual_submission_frequency",
                "detail": (
                    f"{history['recent_run_count']} documents in "
                    f"{history.get('lookback_days', 90)} days"
                ),
                "weight": 0.5,
            })

        confidence = _compute_confidence(anomaly_signals, risk)
        recommended_action = _recommend_action(risk, anomaly_signals)
        narrative = _build_narrative(doc, risk, failed_rules, anomaly_signals)

        return {
            "anomaly_signals": anomaly_signals,
            "narrative": narrative,
            "confidence": round(confidence, 3),
            "recommended_action": recommended_action,
            "ai_provider": "heuristic_v1",
            "failed_rule_summary": failed_rules[:5],
        }


class ClaudeAIAnalysisService(AIAnalysisService):
    """
    LLM-backed analysis using the Anthropic Claude API.

    To activate: set AUDIT_AI_PROVIDER = "claude" in settings.py and ensure
    ANTHROPIC_API_KEY is present in the environment.

    Integration stub — falls back to heuristic until prompt engineering is complete.

    Example full integration:

        from anthropic import Anthropic
        client = Anthropic()
        prompt = _build_audit_prompt(context)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_claude_response(response.content[0].text, context)
    """

    @staticmethod
    def analyse(context: "PipelineContext") -> dict:
        # TODO: Replace with real Claude API call.
        logger.info(
            "[ai_engine] ClaudeAIAnalysisService: falling back to heuristic "
            "(Claude API not yet wired — set AUDIT_AI_PROVIDER='claude' and "
            "implement the prompt in ClaudeAIAnalysisService.analyse)"
        )
        result = AIAnalysisService.analyse(context)
        result["ai_provider"] = "claude_stub"
        return result


# ── Stage ──────────────────────────────────────────────────────────────────────

class AIEngineStage(BaseStage):
    """
    Runs AI analysis and stores insights in context.ai_insights.

    Skip conditions (configurable via AI_SKIP_RISK_LEVELS):
      - risk_level == "low" by default (cost saving)
    """

    name = "ai_engine"
    AI_SKIP_RISK_LEVELS = {"low"}

    def should_skip(self, context: "PipelineContext") -> bool:
        risk_level = context.risk_data.get("risk_level", "low")
        return risk_level in self.AI_SKIP_RISK_LEVELS

    def _run(self, context: "PipelineContext") -> "PipelineContext":
        from django.conf import settings
        provider = getattr(settings, "AUDIT_AI_PROVIDER", "heuristic")

        service = (
            ClaudeAIAnalysisService()
            if provider == "claude"
            else AIAnalysisService()
        )

        context.ai_insights = service.analyse(context)

        logger.info(
            "[ai_engine] provider=%s signals=%d confidence=%.2f action=%s",
            context.ai_insights.get("ai_provider"),
            len(context.ai_insights.get("anomaly_signals", [])),
            context.ai_insights.get("confidence", 0),
            context.ai_insights.get("recommended_action"),
        )
        return context


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compute_confidence(signals: list, risk: dict) -> float:
    if not signals:
        return 0.5
    max_weight = max(s["weight"] for s in signals)
    risk_bonus = 0.1 if risk.get("risk_level") in ("high", "critical") else 0.0
    return min(max_weight + risk_bonus, 1.0)


def _recommend_action(risk: dict, signals: list) -> str:
    if risk.get("blocks_approval"):
        return "reject"
    if risk.get("risk_level") == "critical":
        return "reject"
    if risk.get("risk_level") == "high" or len(signals) >= 2:
        return "review"
    if risk.get("requires_manual_review"):
        return "flag"
    return "approve"


def _build_narrative(doc, risk: dict, failed_rules: list, signals: list) -> str:
    parts = []
    if doc:
        parts.append(
            f"Document {doc.document_number or doc.document_id} "
            f"({doc.document_type}) dated {doc.document_date} "
            f"for {doc.total_amount} {doc.currency or ''}."
        )
    parts.append(
        f"Risk: {risk.get('risk_level', 'unknown')} "
        f"(score={risk.get('risk_score', 0):.1f})."
    )
    if failed_rules:
        codes = ", ".join(r["code"] for r in failed_rules[:3])
        suffix = "..." if len(failed_rules) > 3 else ""
        parts.append(f"Failed rules: {codes}{suffix}.")
    if signals:
        types = ", ".join(s["type"] for s in signals)
        parts.append(f"Anomaly signals: {types}.")
    return " ".join(parts)
