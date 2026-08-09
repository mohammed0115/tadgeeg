"""
Financial Audit Rule Engine

.. deprecated::
    This module is DEPRECATED as of AuditPipeline V2.
    All new code should use:

        from apps.rule_engine.pipeline.v2.compat import run_audit_compat

    Or the drop-in adapter:

        from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
            LegacyAuditEngineAdapter as AuditEngine,
            run_audit_compat_legacy as run_audit,
        )

    This file is retained for backward compatibility and will be removed
    in a future release after all callers have been migrated.

The rule engine evaluates a financial document against a registry of
modular audit rules and produces a structured AuditReport.

Architecture:
  - REGISTERED_RULES: ordered list of all active rule classes
  - AuditEngine.evaluate(): dispatches each rule, collects results
  - AuditReport: aggregates results + computes overall risk
  - save_audit_issues(): persists failed rules as AuditCase records

Usage from tasks / views:

    from apps.audit.audit_engine import AuditEngine

    engine = AuditEngine(organization_id=org.id)
    report = engine.evaluate(
        document=financial_result.to_dict(),
        invoice_id=invoice.id,
        context={"duplicate_result": dup, "compliance_result": comp},
    )

    if report.escalate:
        engine.save_audit_issues(report, invoice=invoice)

Rule lifecycle:
  Upload
  → FinancialAIEngine.analyse()
  → AuditEngine.evaluate()
  → AuditIssue records created
  → AuditCase escalated (if required)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Type

from .rules.base_rule import AuditRule, RuleResult, RuleStatus, Severity
from .rules.duplicate_invoice_rule import DuplicateInvoiceRule
from .rules.vat_validation_rule import VATValidationRule
from .rules.missing_fields_rule import MissingFieldsRule
from .rules.amount_anomaly_rule import AmountAnomalyRule
from .rules.date_validation_rule import DateValidationRule
from .rules.vendor_risk_rule import VendorRiskRule
from .rules.extended_rules import (
    ThreeWayMatchRule,
    CurrencyConsistencyRule,
    VATRateValidityRule,
    RoundNumberAnomalyRule,
    LineItemReconciliationRule,
    NegativeAmountRule,
    DueDateValidityRule,
    VATNumberFormatRule,
    VendorApprovalRule,
    DecimalPrecisionRule,
    ZatcaQRPresenceRule,
    MandatoryFieldsRule,
)

logger = logging.getLogger("finai")

# ── Rule Registry ─────────────────────────────────────────────────────────────
# Ordered list: critical-path rules first.
# Add new rules here — they'll be auto-discovered by evaluate().

REGISTERED_RULES: list[Type[AuditRule]] = [
    DuplicateInvoiceRule,           # R001 — Must run first (highest impact)
    MissingFieldsRule,              # R003 — Data completeness
    VATValidationRule,              # R002 — VAT compliance
    DateValidationRule,             # R005 — Date anomalies
    AmountAnomalyRule,              # R004 — Statistical analysis
    VendorRiskRule,                 # R006 — Vendor screening
    ThreeWayMatchRule,              # R007 — PO ↔ GRN ↔ Invoice
    CurrencyConsistencyRule,        # R008 — ISO-4217 currency
    VATRateValidityRule,            # R009 — KSA VAT rates (0/5/15)
    RoundNumberAnomalyRule,         # R010 — Suspicious round totals
    LineItemReconciliationRule,     # R011 — Line items sum = subtotal
    NegativeAmountRule,             # R012 — Reject negative amounts
    DueDateValidityRule,            # R013 — Due date sanity
    VATNumberFormatRule,            # R014 — KSA TRN format (15 digits, 3..3)
    VendorApprovalRule,             # R015 — Vendor not blocked
    DecimalPrecisionRule,           # R016 — Amounts >2 dp
    ZatcaQRPresenceRule,            # R017 — Phase 2 QR required for SA invoices
    MandatoryFieldsRule,            # R018 — ZATCA + ISA 500 fields
]

# Severity → weight mapping for aggregate risk calculation
SEVERITY_RISK_WEIGHTS: dict[str, float] = {
    "CRITICAL": 40.0,
    "HIGH":     25.0,
    "MEDIUM":   10.0,
    "LOW":       5.0,
}

# Risk level thresholds (same as RiskEngine for consistency)
RISK_THRESHOLDS = {
    "critical": 75,
    "high": 50,
    "medium": 25,
}


# ── Audit Report ──────────────────────────────────────────────────────────────

@dataclass
class AuditReport:
    """
    Complete result of running all audit rules against a document.
    """

    document_id: Optional[int] = None
    rule_results: list[RuleResult] = field(default_factory=list)
    risk_score: int = 0
    risk_level: str = "low"
    total_rules: int = 0
    passed_rules: int = 0
    failed_rules: int = 0
    skipped_rules: int = 0
    error_rules: int = 0
    escalate: bool = False
    processing_time_ms: int = 0
    summary: str = ""

    @property
    def failed_results(self) -> list[RuleResult]:
        return [r for r in self.rule_results if r.result == RuleStatus.FAILED]

    @property
    def critical_failures(self) -> list[RuleResult]:
        return [
            r for r in self.failed_results
            if r.severity in (Severity.CRITICAL, "CRITICAL")
        ]

    @property
    def high_failures(self) -> list[RuleResult]:
        return [
            r for r in self.failed_results
            if r.severity in (Severity.HIGH, "HIGH")
        ]

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "rule_results": [r.to_dict() for r in self.rule_results],
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "total_rules": self.total_rules,
            "passed_rules": self.passed_rules,
            "failed_rules": self.failed_rules,
            "skipped_rules": self.skipped_rules,
            "error_rules": self.error_rules,
            "escalate": self.escalate,
            "processing_time_ms": self.processing_time_ms,
            "summary": self.summary,
        }


# ── Audit Engine ──────────────────────────────────────────────────────────────

class AuditEngine:
    """
    Financial Audit Rule Engine.

    Evaluates all registered rules and produces an AuditReport.
    Can persist findings to the database as AuditCase / issue records.
    """

    def __init__(
        self,
        organization_id: int = None,
        rules: list[Type[AuditRule]] = None,
    ):
        self.organization_id = organization_id
        self.rule_classes = rules or REGISTERED_RULES

    def evaluate(
        self,
        document: dict,
        invoice_id: int = None,
        context: dict = None,
    ) -> AuditReport:
        """
        Run all registered rules against the document.

        Args:
            document:   Normalised document dict (from FinancialAIEngine.to_dict()).
            invoice_id: Optional Invoice PK for database persistence.
            context:    Pre-computed sub-results (duplicate_result, etc.)
                        to avoid redundant computation.

        Returns:
            AuditReport
        """
        t_start = time.monotonic()
        context = context or {}
        results: list[RuleResult] = []

        # Inject the invoice/document PK into the dict so rules that delegate
        # to back-end services (e.g. DuplicateDetector) can exclude the current
        # row from match queries — without this, a freshly-saved invoice will
        # match itself as a "near-certain duplicate" (R001 self-match bug).
        if invoice_id is not None and "invoice_id" not in document:
            document = {**document, "invoice_id": invoice_id, "document_id": invoice_id}

        logger.info(
            "[AuditEngine] Evaluating %d rules for document=%s invoice=%s",
            len(self.rule_classes),
            document.get("document_number", "?"),
            invoice_id,
        )

        for rule_class in self.rule_classes:
            rule = rule_class()
            try:
                result = rule.evaluate(
                    document=document,
                    organization_id=self.organization_id,
                    context=context,
                )
                result.document_id = invoice_id
            except Exception as exc:
                result = rule._error(exc)
                logger.exception(
                    "[AuditEngine] Rule %s crashed unexpectedly", rule.rule_id
                )
            results.append(result)

            # Log individual result
            logger.debug(
                "[AuditEngine] Rule %s (%s): %s — %s",
                result.rule_id,
                result.severity,
                result.result,
                result.explanation[:100] if result.explanation else "",
            )

        # Phase 2.2 — also run every PUBLISHED custom DSL rule for this org.
        results.extend(self._evaluate_custom_rules(document, invoice_id))

        # ── Aggregate ─────────────────────────────────────────────────────────
        report = self._build_report(results, invoice_id)
        report.processing_time_ms = int((time.monotonic() - t_start) * 1000)

        logger.info(
            "[AuditEngine] Complete: risk=%s (%d) | passed=%d failed=%d | %dms",
            report.risk_level,
            report.risk_score,
            report.passed_rules,
            report.failed_rules,
            report.processing_time_ms,
        )

        return report

    def save_audit_issues(
        self,
        report: AuditReport,
        invoice=None,
        transaction=None,
        created_by=None,
    ) -> list:
        """
        Persist failed rule results as AuditCase records.

        Only creates cases for FAILED results with HIGH or CRITICAL severity.
        MEDIUM/LOW failures are stored as sub-issues on existing cases.

        Returns:
            List of created AuditCase instances.
        """
        from .models import AuditCase

        cases = []
        for result in report.failed_results:
            sev = (result.severity.value if isinstance(result.severity, Severity)
                   else str(result.severity))

            if sev not in ("CRITICAL", "HIGH"):
                continue  # Only create cases for significant issues

            priority_map = {"CRITICAL": "critical", "HIGH": "high"}
            priority = priority_map.get(sev, "medium")

            try:
                import json as _json
                def _json_safe(obj):
                    """Recursively convert non-serializable types to strings."""
                    if isinstance(obj, dict):
                        return {k: _json_safe(v) for k, v in obj.items()}
                    if isinstance(obj, (list, tuple)):
                        return [_json_safe(i) for i in obj]
                    try:
                        _json.dumps(obj)
                        return obj
                    except (TypeError, ValueError):
                        return str(obj)
                case_data = {
                    "organization_id": self.organization_id,
                    "case_type": "audit",
                    "priority": priority,
                    "status": "open",
                    "title": f"[{result.rule_id}] {result.rule_name}",
                    "description": result.explanation,
                    "ai_findings": _json_safe(result.to_dict()),
                    "ai_risk_score": report.risk_score,
                }
                if invoice:
                    case_data["invoice"] = invoice
                if transaction:
                    case_data["transaction"] = transaction
                if created_by:
                    case_data["created_by"] = created_by

                case = AuditCase.objects.create(**case_data)
                cases.append(case)
                logger.info(
                    "[AuditEngine] Created AuditCase %s for rule %s",
                    case.pk, result.rule_id,
                )
            except Exception as exc:
                logger.error(
                    "[AuditEngine] Failed to create AuditCase for rule %s: %s",
                    result.rule_id, exc,
                )

        return cases

    # ── Internal ──────────────────────────────────────────────────────────────

    def _evaluate_custom_rules(self, document: dict, invoice_id) -> list[RuleResult]:
        """Run every PUBLISHED DSL rule for this organisation against ``document``.

        Each rule produces one RuleResult so the failures show up in the same
        AuditReport, AuditCase rows, and risk-score aggregation as the
        built-in rules. Errors in a single rule never abort the others.
        """
        if not self.organization_id:
            return []
        try:
            from apps.audit.models import CustomRuleDefinition
            from apps.audit.services.rule_dsl import evaluate as eval_dsl
        except ImportError:
            return []

        out: list[RuleResult] = []
        qs = (
            CustomRuleDefinition.objects
            .filter(
                organization_id=self.organization_id,
                status=CustomRuleDefinition.Status.PUBLISHED,
                is_active=True,
                condition_type=CustomRuleDefinition.ConditionType.DSL,
            )
            .order_by("name")
        )
        for rule in qs:
            try:
                outcome = eval_dsl(rule.expression_dsl or {}, document)
            except Exception as exc:   # never let one rule poison the whole audit
                logger.warning("[AuditEngine] custom rule %s crashed: %s",
                               rule.id, exc)
                continue

            severity_str = (outcome.severity or rule.severity or "MEDIUM").upper()
            try:
                severity_enum = Severity(severity_str)
            except ValueError:
                severity_enum = Severity.MEDIUM

            result = RuleResult(
                rule_id=f"CUSTOM-{str(rule.id)[:8]}",
                rule_name=rule.name,
                severity=severity_enum,
                result=RuleStatus.FAILED if outcome.triggered else RuleStatus.PASSED,
                explanation=outcome.message or outcome.explanation,
                details={
                    "custom_rule_id": str(rule.id),
                    "action":         outcome.action,
                    "rule_name":      rule.name,
                    "rule_version":   rule.version,
                },
                document_id=invoice_id,
            )
            out.append(result)
            logger.debug(
                "[AuditEngine] Custom rule %s: triggered=%s severity=%s",
                rule.name, outcome.triggered, severity_str,
            )
        return out

    def _build_report(
        self, results: list[RuleResult], document_id: Optional[int]
    ) -> AuditReport:
        """Aggregate rule results into an AuditReport."""
        passed = sum(1 for r in results if r.result == RuleStatus.PASSED)
        failed = sum(1 for r in results if r.result == RuleStatus.FAILED)
        skipped = sum(1 for r in results if r.result == RuleStatus.SKIPPED)
        errors = sum(1 for r in results if r.result == RuleStatus.ERROR)

        # Compute risk score from failed rules
        raw_score = 0.0
        for r in results:
            if r.result == RuleStatus.FAILED:
                sev = r.severity.value if isinstance(r.severity, Severity) else str(r.severity)
                raw_score += SEVERITY_RISK_WEIGHTS.get(sev, 5.0)

        risk_score = min(int(round(raw_score)), 100)

        # Risk level
        if risk_score >= RISK_THRESHOLDS["critical"]:
            risk_level = "critical"
        elif risk_score >= RISK_THRESHOLDS["high"]:
            risk_level = "high"
        elif risk_score >= RISK_THRESHOLDS["medium"]:
            risk_level = "medium"
        else:
            risk_level = "low"

        escalate = risk_level in ("high", "critical")

        # Summary
        critical_rules = [
            r.rule_name for r in results
            if r.result == RuleStatus.FAILED
            and (r.severity == Severity.CRITICAL or r.severity == "CRITICAL")
        ]
        if critical_rules:
            summary = f"CRITICAL issues: {', '.join(critical_rules)}"
        elif failed > 0:
            failed_names = [r.rule_name for r in results if r.result == RuleStatus.FAILED]
            summary = f"{failed} rule(s) failed: {', '.join(failed_names[:3])}"
        else:
            summary = f"All {passed} applicable rules passed."

        return AuditReport(
            document_id=document_id,
            rule_results=results,
            risk_score=risk_score,
            risk_level=risk_level,
            total_rules=len(results),
            passed_rules=passed,
            failed_rules=failed,
            skipped_rules=skipped,
            error_rules=errors,
            escalate=escalate,
            summary=summary,
        )


# ── Convenience function ──────────────────────────────────────────────────────

def run_audit(
    document: dict,
    organization_id: int = None,
    invoice_id: int = None,
    context: dict = None,
    persist: bool = False,
    invoice=None,
    created_by=None,
) -> AuditReport:
    """
    DEPRECATED legacy audit pipeline. Kept ONLY for rollback.

    The canonical audit pipeline is now ``apps.rule_engine.tasks.audit_tasks
    .run_audit_task`` driven by ``AuditPipeline`` in
    ``apps.rule_engine.executors``. See Documentation/AUDIT_PIPELINE_CANONICAL.md.

    This function is no longer called from production upload paths when
    ``settings.USE_NEW_RULE_ENGINE`` is True (the default). It remains as
    an escape hatch: flip the flag to False to revert to this engine
    while a regression is investigated.

    Removal plan: delete this and the AuditEngine class once
    USE_NEW_RULE_ENGINE has run cleanly in production for 2 release
    cycles with no rollbacks.

    Args:
        document:        Normalised document dict.
        organization_id: Organisation ID.
        invoice_id:      Invoice PK (for DB linkage).
        context:         Pre-computed results dict.
        persist:         If True, create AuditCase records for failures.
        invoice:         Invoice model instance (for FK).
        created_by:      User who triggered the audit.

    Returns:
        AuditReport
    """
    engine = AuditEngine(organization_id=organization_id)
    report = engine.evaluate(document, invoice_id=invoice_id, context=context)

    if persist and report.failed_rules > 0:
        engine.save_audit_issues(report, invoice=invoice, created_by=created_by)

    return report
