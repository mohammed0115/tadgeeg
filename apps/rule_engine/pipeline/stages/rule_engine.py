"""
RuleEngineStage — Stage 3 of AuditPipeline V2.

Executes all applicable rules against the NormalizedDocument.
Reuses V1 rule execution logic (RuleSelector, RuleRegistry, AuditResult
persistence) to maintain full backward compatibility with existing rules.

This is a CriticalStage: without rule results, risk and decision stages
cannot produce meaningful output.

Populates:
  context.rule_results      list[AuditResult ORM instances]
  context.rule_assignments  list[RuleAssignment ORM instances]
Also updates AuditRun rule counters (total/passed/failed/warning/etc.).
"""
from __future__ import annotations

import logging
import time
import traceback as tb
from typing import TYPE_CHECKING

from apps.rule_engine.pipeline.stages.base import CriticalStage
from apps.rule_engine.registry.rule_registry import RuleRegistry, RuleRegistryError
from apps.rule_engine.selectors.rule_selector import RuleSelector
from apps.rule_engine.models import AuditRun, AuditResult, AuditEvidence

if TYPE_CHECKING:
    from apps.rule_engine.pipeline.v2.context import PipelineContext

logger = logging.getLogger("rule_engine.pipeline")

__all__ = ["RuleEngineStage"]


class RuleEngineStage(CriticalStage):
    """
    Runs all applicable rule classes and persists one AuditResult
    (+ N AuditEvidence rows) per rule.
    """

    name = "rule_engine"

    def __init__(self) -> None:
        self._registry = RuleRegistry()
        self._selector = RuleSelector()

    # ── Core ────────────────────────────────────────────────────────────────────

    def _run(self, context: "PipelineContext") -> "PipelineContext":
        audit_run = AuditRun.objects.get(id=context.audit_run_id)
        assignments = self._selector.get_applicable_rules(
            context.document_type,
            context.organization_id,
        )
        audit_run.total_rules = len(assignments)
        audit_run.save(update_fields=["total_rules"])

        context.rule_assignments = list(assignments)
        results: list[AuditResult] = []

        for assignment in assignments:
            result = self._execute_single_rule(audit_run, assignment, context.normalized_doc)
            results.append(result)

        context.rule_results = results

        counts = _count_statuses(results)
        audit_run.passed_rules  = counts.get("pass", 0)
        audit_run.failed_rules  = counts.get("fail", 0)
        audit_run.warning_rules = counts.get("warning", 0)
        audit_run.skipped_rules = (
            counts.get("skipped", 0) + counts.get("not_applicable", 0)
        )
        audit_run.error_rules = counts.get("error", 0)
        audit_run.save(update_fields=[
            "passed_rules", "failed_rules", "warning_rules",
            "skipped_rules", "error_rules",
        ])

        logger.info(
            "[rule_engine] Executed %d rules — pass=%d fail=%d warn=%d skip=%d err=%d",
            len(assignments),
            audit_run.passed_rules, audit_run.failed_rules,
            audit_run.warning_rules, audit_run.skipped_rules,
            audit_run.error_rules,
        )
        return context

    # ── Rule execution (mirrors AuditPipeline V1 logic) ─────────────────────────

    def _execute_single_rule(self, audit_run, assignment, normalized_doc) -> AuditResult:
        """Execute one rule and persist its result + evidence. Never raises."""
        t0 = time.monotonic()

        result = AuditResult(
            audit_run=audit_run,
            rule_assignment=assignment,
            rule_code=assignment.rule.rule_code,
            rule_version=assignment.rule.version,
            applied_severity=assignment.effective_severity,
            blocks_approval=assignment.effective_blocks_approval,
        )

        try:
            rule_class = self._registry.get_class(assignment.rule.implementation_class)
            rule_instance = rule_class(config=assignment.effective_config)

            missing = _check_field_dependencies(rule_instance, normalized_doc)
            if missing:
                result.status = AuditResult.Status.SKIPPED
                result.explanation = (
                    f"Skipped: required canonical fields not available: {', '.join(missing)}"
                )
                result.explanation_ar = (
                    f"تم التخطي: الحقول المطلوبة غير متوفرة: {', '.join(missing)}"
                )
                result.execution_time_ms = int((time.monotonic() - t0) * 1000)
                result.save()
                return result

            if not rule_instance.check_preconditions(normalized_doc):
                result.status = AuditResult.Status.SKIPPED
                result.explanation = "Preconditions not met — required data missing or not applicable"
                result.explanation_ar = "تم تخطي القاعدة: البيانات المطلوبة غير متوفرة"
                result.execution_time_ms = int((time.monotonic() - t0) * 1000)
                result.save()
                return result

            rule_result = rule_instance.execute(normalized_doc)
            status_val = (
                rule_result.status.value
                if hasattr(rule_result.status, "value")
                else rule_result.status
            )
            result.status = status_val
            result.explanation = rule_result.explanation_en
            result.explanation_ar = rule_result.explanation_ar
            result.blocks_approval = bool(
                result.blocks_approval or getattr(rule_result, "is_blocking", False)
            )
            result.risk_contribution = rule_result.risk_contribution
            result.raw_output = rule_result.to_dict()
            result.execution_time_ms = int((time.monotonic() - t0) * 1000)
            result.save()

            _persist_evidence(result, rule_result)
            return result

        except RuleRegistryError as exc:
            result.status = AuditResult.Status.ERROR
            result.explanation = f"Rule class not found: {exc}"
            result.error_message = str(exc)
            logger.error("[rule_engine] RuleRegistryError for %s: %s", assignment.rule.rule_code, exc)

        except Exception as exc:
            result.status = AuditResult.Status.ERROR
            result.explanation = f"Rule execution failed: {type(exc).__name__}: {exc}"
            result.error_message = str(exc)
            result.error_traceback = tb.format_exc()
            logger.error(
                "[rule_engine] Rule %s failed on doc %s: %s",
                assignment.rule.rule_code, audit_run.document_id, exc,
            )

        result.execution_time_ms = int((time.monotonic() - t0) * 1000)
        result.save()
        return result


# ── Module-level helpers ───────────────────────────────────────────────────────

def _count_statuses(results: list) -> dict:
    counts: dict = {}
    for r in results:
        s = r.status if isinstance(r.status, str) else r.status.value
        counts[s] = counts.get(s, 0) + 1
    return counts


def _check_field_dependencies(rule_instance, normalized_doc) -> list:
    deps = getattr(rule_instance, "field_dependencies", [])
    if not deps:
        return []
    try:
        from apps.documents.canonical_models import DocumentCanonicalData
        rec = DocumentCanonicalData.objects.filter(
            typed_object_id=str(normalized_doc.document_id)
        ).first()
        if rec is None:
            return list(deps)
        canonical = rec.canonical_data or {}
        return [f for f in deps if canonical.get(f) is None]
    except Exception as exc:
        logger.warning("[rule_engine] FieldDependencyChecker error: %s", exc)
        return []  # fail open — run the rule anyway


def _persist_evidence(result: AuditResult, rule_result) -> None:
    """Persist EvidenceItems for FAIL/WARNING results. Guarantees at least one row."""
    evidence_items = list(rule_result.evidence or [])

    if result.status in (AuditResult.Status.FAIL, AuditResult.Status.WARNING) and not evidence_items:
        # Sentinel row: ensures every failure has traceable evidence.
        evidence_items = [{
            "evidence_type": "field_value",
            "field_name": "rule_code",
            "field_name_ar": "رمز القاعدة",
            "expected_value": "pass",
            "actual_value": result.status,
            "description": result.explanation,
            "description_ar": result.explanation_ar,
        }]

    for ev in evidence_items:
        ev_dict = ev.to_dict() if hasattr(ev, "to_dict") else ev
        AuditEvidence.objects.create(
            audit_result=result,
            evidence_type=ev_dict.get("evidence_type", "field_value"),
            field_name=ev_dict.get("field_name", ""),
            field_name_ar=ev_dict.get("field_name_ar", ""),
            expected_value=ev_dict.get("expected_value"),
            actual_value=ev_dict.get("actual_value"),
            description=ev_dict.get("description", ""),
            description_ar=ev_dict.get("description_ar", ""),
            linked_document_type=ev_dict.get("linked_document_type", ""),
            linked_document_id=ev_dict.get("linked_document_id") or None,
        )
