"""
Risk Aggregator — computes a normalized risk score (0–100) from AuditResult list.

Scoring model:
  - Each FAIL result contributes its severity weight
  - Each WARNING result contributes 50% of its severity weight
  - PASS, SKIPPED, NOT_APPLICABLE, ERROR contribute 0
  - Final score = (total fail weight / total possible weight) * 100
  - CRITICAL failure always results in risk_level=critical regardless of score
"""
from decimal import Decimal
import logging

logger = logging.getLogger("rule_engine")

SEVERITY_WEIGHTS = {
    "critical": Decimal("40.0"),
    "high":     Decimal("25.0"),
    "medium":   Decimal("10.0"),
    "low":      Decimal("5.0"),
    "info":     Decimal("1.0"),
}

RISK_THRESHOLDS = {
    "critical": 75,
    "high":     50,
    "medium":   25,
}

WARNING_WEIGHT_FACTOR = Decimal("0.5")
MANUAL_REVIEW_THRESHOLD = 50  # risk_score >= this triggers manual review


class RiskAggregator:

    def compute(self, results: list, assignments: list) -> dict:
        """
        Compute risk score from a list of AuditResult objects.

        Returns dict with:
          risk_score (float 0–100)
          risk_level (str: low/medium/high/critical)
          blocks_approval (bool)
          requires_manual_review (bool)
          score_breakdown (dict)
          top_failed_rules (list)
        """
        raw_score = Decimal("0")
        max_possible = Decimal("0")
        blocks_approval = False
        has_critical_fail = False
        score_breakdown = {k: 0.0 for k in SEVERITY_WEIGHTS}
        failed_rules = []

        assignment_map = {a.rule.rule_code: a for a in assignments}

        for result in results:
            status = result.status if isinstance(result.status, str) else result.status.value
            if status in ("skipped", "not_applicable", "error"):
                continue

            severity = result.applied_severity
            weight = SEVERITY_WEIGHTS.get(severity, Decimal("0"))
            max_possible += weight

            if status == "fail":
                raw_score += weight
                score_breakdown[severity] = score_breakdown.get(severity, 0) + float(weight)

                if severity == "critical":
                    has_critical_fail = True

                if result.blocks_approval:
                    blocks_approval = True

                failed_rules.append({
                    "rule_code": result.rule_code,
                    "severity": severity,
                    "risk_contribution": float(result.risk_contribution),
                })

            elif status == "warning":
                partial = weight * WARNING_WEIGHT_FACTOR
                raw_score += partial
                score_breakdown[severity] = score_breakdown.get(severity, 0) + float(partial)

        # Normalize to 0–100
        if max_possible > 0:
            risk_score = (raw_score / max_possible) * Decimal("100")
        else:
            risk_score = Decimal("0")

        risk_score = min(risk_score, Decimal("100"))

        # Determine risk level
        score_float = float(risk_score)
        if has_critical_fail or score_float >= RISK_THRESHOLDS["critical"]:
            risk_level = "critical"
        elif score_float >= RISK_THRESHOLDS["high"]:
            risk_level = "high"
        elif score_float >= RISK_THRESHOLDS["medium"]:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Sort top failed rules by contribution
        top_failed = sorted(failed_rules, key=lambda x: x["risk_contribution"], reverse=True)[:5]

        return {
            "risk_score": round(score_float, 2),
            "risk_level": risk_level,
            "blocks_approval": blocks_approval,
            "requires_manual_review": score_float >= MANUAL_REVIEW_THRESHOLD,
            "score_breakdown": score_breakdown,
            "top_failed_rules": top_failed,
        }
