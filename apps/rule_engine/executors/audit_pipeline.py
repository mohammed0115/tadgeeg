"""
Audit Pipeline — main orchestrator for document rule execution.

Execution flow:
1. Create AuditRun record (status=RUNNING)
2. Normalize document into NormalizedDocument
3. Select applicable rules via RuleSelector
4. Execute each rule via RuleExecutor
5. Persist AuditResult + AuditEvidence for each rule
6. Aggregate risk via RiskAggregator
7. Upsert RiskScoreSummary
8. Complete AuditRun (status=COMPLETED)
"""

import time
import traceback as tb
import logging
from django.utils import timezone
from django.db import transaction

from apps.rule_engine.models import (
    AuditRun, AuditResult, AuditEvidence, RiskScoreSummary
)
from apps.rule_engine.registry.rule_registry import RuleRegistry, RuleRegistryError
from apps.rule_engine.selectors.rule_selector import RuleSelector
from apps.rule_engine.normalizers import DocumentNormalizerFactory
from apps.rule_engine.risk.risk_aggregator import RiskAggregator
from apps.rule_engine.rules.base import RuleStatus

logger = logging.getLogger("rule_engine")


class AuditPipeline:
    """
    Main orchestrator. One instance per execution is safe (stateless).
    """

    def __init__(self):
        self.registry = RuleRegistry()
        self.selector = RuleSelector()
        self.aggregator = RiskAggregator()

    def run(
        self,
        document_id: str,
        document_type: str,
        organization_id: str,
        triggered_by: str = "upload",
    ) -> AuditRun:
        """
        Execute all applicable rules against a document.
        Returns the completed AuditRun instance.
        """
        logger.info(
            f"AuditPipeline starting: document_id={document_id}, "
            f"type={document_type}, org={organization_id}"
        )

        audit_run = AuditRun.objects.create(
            organization_id=organization_id,
            document_type=document_type,
            document_id=document_id,
            triggered_by=triggered_by,
            status=AuditRun.Status.RUNNING,
            started_at=timezone.now(),
        )

        try:
            # Step 1: Normalize document
            normalizer = DocumentNormalizerFactory.get(document_type)
            normalized_doc = normalizer.normalize(document_id, organization_id)

            # Step 2: Select applicable rules
            assignments = self.selector.get_applicable_rules(document_type, organization_id)
            audit_run.total_rules = len(assignments)

            logger.info(f"AuditRun {audit_run.id}: executing {len(assignments)} rules")

            # Step 3: Execute each rule
            results = []
            for assignment in assignments:
                result = self._execute_single_rule(audit_run, assignment, normalized_doc)
                results.append(result)

            # Step 4: Aggregate risk with contextual document signals
            risk_data = self.aggregator.compute(
                results,
                assignments,
                normalized_doc=normalized_doc,
            )
            self._update_vendor_intelligence(normalized_doc, risk_data)

            # Step 5: Update counters
            status_counts = self._count_statuses(results)
            audit_run.passed_rules = status_counts.get("pass", 0)
            audit_run.failed_rules = status_counts.get("fail", 0)
            audit_run.warning_rules = status_counts.get("warning", 0)
            audit_run.skipped_rules = status_counts.get("skipped", 0) + status_counts.get("not_applicable", 0)
            audit_run.error_rules = status_counts.get("error", 0)

            audit_run.risk_score = risk_data["risk_score"]
            audit_run.risk_level = risk_data["risk_level"]
            audit_run.requires_manual_review = risk_data["requires_manual_review"]
            audit_run.blocks_approval = risk_data["blocks_approval"]

            # Step 6: Upsert RiskScoreSummary
            self._upsert_risk_summary(audit_run, risk_data)

            # Complete
            audit_run.status = AuditRun.Status.COMPLETED
            audit_run.completed_at = timezone.now()
            audit_run.processing_time_ms = int(
                (audit_run.completed_at - audit_run.started_at).total_seconds() * 1000
            )
            audit_run.save()

            logger.info(
                f"AuditRun {audit_run.id} completed: risk={risk_data['risk_score']:.1f} "
                f"({risk_data['risk_level']}), failed={audit_run.failed_rules}/{audit_run.total_rules}"
            )

            return audit_run

        except Exception as e:
            logger.exception(f"AuditPipeline fatal error for document {document_id}: {e}")
            audit_run.status = AuditRun.Status.FAILED
            audit_run.error_log = [{"error": str(e), "traceback": tb.format_exc()}]
            audit_run.completed_at = timezone.now()
            audit_run.save()
            raise

    def _execute_single_rule(self, audit_run, assignment, normalized_doc) -> AuditResult:
        """Execute one rule and persist its result. Never raises."""
        start_ms = time.monotonic()

        result = AuditResult(
            audit_run=audit_run,
            rule_assignment=assignment,
            rule_code=assignment.rule.rule_code,
            rule_version=assignment.rule.version,
            applied_severity=assignment.effective_severity,
            blocks_approval=assignment.effective_blocks_approval,
        )

        try:
            # Load rule class
            rule_class = self.registry.get_class(assignment.rule.implementation_class)
            rule_instance = rule_class(config=assignment.effective_config)

            # Check canonical field dependencies (Day 4 — RuleDependencyChecker)
            missing_fields = self._check_field_dependencies(rule_instance, normalized_doc)
            if missing_fields:
                result.status = AuditResult.Status.SKIPPED
                result.explanation = (
                    f"Skipped: required canonical fields not available: {', '.join(missing_fields)}"
                )
                result.explanation_ar = (
                    f"تم التخطي: الحقول المطلوبة غير متوفرة في البيانات القانونية: {', '.join(missing_fields)}"
                )
                result.execution_time_ms = int((time.monotonic() - start_ms) * 1000)
                result.save()
                return result

            # Check preconditions
            if not rule_instance.check_preconditions(normalized_doc):
                result.status = AuditResult.Status.SKIPPED
                result.explanation = "Preconditions not met — required fields missing or not applicable"
                result.explanation_ar = "تم تخطي القاعدة: البيانات المطلوبة غير متوفرة"
            else:
                # Execute rule
                rule_result = rule_instance.execute(normalized_doc)

                status_value = rule_result.status.value if hasattr(rule_result.status, 'value') else rule_result.status
                result.status = status_value
                result.explanation = rule_result.explanation_en
                result.explanation_ar = rule_result.explanation_ar
                result.risk_contribution = rule_result.risk_contribution
                result.raw_output = rule_result.to_dict()

                result.execution_time_ms = int((time.monotonic() - start_ms) * 1000)
                result.save()

                # Persist evidence items
                evidence_items = list(rule_result.evidence or [])
                if result.status in (AuditResult.Status.FAIL, AuditResult.Status.WARNING) and not evidence_items:
                    # Ensure failed/warning outcomes always carry at least one evidence row for reporting consistency.
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
                    ev_dict = ev.to_dict() if hasattr(ev, 'to_dict') else ev
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
                return result

        except RuleRegistryError as e:
            result.status = AuditResult.Status.ERROR
            result.explanation = f"Rule class not found: {e}"
            result.error_message = str(e)
            logger.error(f"RuleRegistry error for {assignment.rule.rule_code}: {e}")

        except Exception as e:
            result.status = AuditResult.Status.ERROR
            result.explanation = f"Rule execution failed: {type(e).__name__}: {e}"
            result.error_message = str(e)
            result.error_traceback = tb.format_exc()
            logger.error(f"Rule {assignment.rule.rule_code} failed on doc {audit_run.document_id}: {e}")

        result.execution_time_ms = int((time.monotonic() - start_ms) * 1000)
        result.save()
        return result

    @staticmethod
    def _update_vendor_intelligence(normalized_doc, risk_data: dict) -> None:
        try:
            from apps.invoices.services.vendor_intelligence import VendorIntelligenceService
            VendorIntelligenceService().update_after_audit(normalized_doc, risk_data)
        except Exception as exc:
            logger.warning("[AuditPipeline] Vendor intelligence update skipped: %s", exc)

    def _upsert_risk_summary(self, audit_run: AuditRun, risk_data: dict):
        """Create or update RiskScoreSummary for the document."""
        try:
            RiskScoreSummary.objects.update_or_create(
                document_id=audit_run.document_id,
                defaults={
                    "organization_id": audit_run.organization_id,
                    "document_type": audit_run.document_type,
                    "latest_audit_run": audit_run,
                    "risk_score": risk_data["risk_score"],
                    "risk_level": risk_data["risk_level"],
                    "fraud_indicators": len(risk_data.get("anomaly_findings", [])),
                    "blocking_failures": audit_run.results.filter(
                        status="fail", blocks_approval=True
                    ).count(),
                    "compliance_failures": audit_run.results.filter(
                        status="fail",
                    ).count(),
                    "requires_manual_review": risk_data["requires_manual_review"],
                    "blocks_approval": risk_data["blocks_approval"],
                    "score_breakdown": risk_data.get("score_breakdown", {}),
                    "top_failed_rules": risk_data.get("top_failed_rules", []),
                }
            )
        except Exception as e:
            logger.error(f"Failed to upsert RiskScoreSummary for doc {audit_run.document_id}: {e}")

    @staticmethod
    def _check_field_dependencies(rule_instance, normalized_doc) -> list:
        """
        RuleDependencyChecker: returns a list of missing field codes.
        If field_dependencies is empty, always passes (returns []).
        Checks the DocumentCanonicalData record for this document.
        """
        deps = getattr(rule_instance, "field_dependencies", [])
        if not deps:
            return []
        try:
            from apps.documents.canonical_models import DocumentCanonicalData
            rec = DocumentCanonicalData.objects.filter(
                typed_object_id=str(normalized_doc.document_id)
            ).first()
            if rec is None:
                # No canonical record at all — skip only if any dependency declared
                return list(deps)
            canonical = rec.canonical_data or {}
            return [f for f in deps if canonical.get(f) is None]
        except Exception as exc:
            logger.warning("RuleDependencyChecker error for %s: %s", normalized_doc.document_id, exc)
            return []  # fail open — run the rule anyway

    @staticmethod
    def _count_statuses(results: list) -> dict:
        counts = {}
        for r in results:
            status = r.status if isinstance(r.status, str) else r.status.value
            counts[status] = counts.get(status, 0) + 1
        return counts
