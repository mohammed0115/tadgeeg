"""
Risk Scoring Engine

Aggregates signals from multiple sources into a unified risk level:

  Inputs:
    - duplicate_score      (0–1) from DuplicateDetector
    - fraud_score          (0–1) from FraudDetector
    - compliance_score     (0–1) from VATValidator
    - audit_rule_results   list of rule results from AuditEngine
    - missing_fields       count of missing required fields
    - document_quality     OCR confidence / image clarity score

  Output:
    {
      risk_score:  0–100  (composite numerical score)
      risk_level:  "low" | "medium" | "high" | "critical"
      risk_factors: list of human-readable risk explanations
      escalate:    bool (whether to auto-create an audit case)
    }

Risk level thresholds:
  critical:  risk_score ≥ 75
  high:      risk_score ≥ 50
  medium:    risk_score ≥ 25
  low:       risk_score < 25

These thresholds are configurable per organisation via settings.
"""

import logging
from typing import Optional

logger = logging.getLogger("finai")

# ── Weights ───────────────────────────────────────────────────────────────────
# Each signal contributes a weighted share of the final risk_score.
WEIGHTS = {
    "duplicate":    0.30,
    "fraud":        0.35,
    "compliance":   0.20,   # inverse: (1 - compliance_score)
    "audit_rules":  0.10,
    "missing_fields": 0.05,
}

# ── Thresholds ────────────────────────────────────────────────────────────────
LEVEL_CRITICAL = 75
LEVEL_HIGH = 50
LEVEL_MEDIUM = 25

# Severity multipliers for audit rule results
SEVERITY_SCORES = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.2}

# Required financial fields
REQUIRED_FIELDS = [
    "vendor_name",
    "document_number",
    "date",
    "total_amount",
    "currency",
]


class RiskEngine:
    """
    Composite risk scoring engine.

    Usage:
        engine = RiskEngine()
        result = engine.score(
            document=normalised_doc,
            duplicate_result=dup_result,
            fraud_result=fraud_result,
            compliance_result=comp_result,
            audit_rule_results=rule_results,
        )
    """

    def score(
        self,
        document: dict,
        duplicate_result: dict = None,
        fraud_result: dict = None,
        compliance_result: dict = None,
        audit_rule_results: list[dict] = None,
    ) -> dict:
        """
        Compute composite risk score from all available signals.

        Args:
            document:            Normalised document dict.
            duplicate_result:    Output of DuplicateDetector.detect().
            fraud_result:        Output of FraudDetector.detect().
            compliance_result:   Output of VATValidator.validate().
            audit_rule_results:  List of audit rule result dicts.

        Returns:
            {
              risk_score: int (0–100),
              risk_level: str,
              risk_factors: list[str],
              escalate: bool,
              signal_breakdown: dict
            }
        """
        duplicate_result = duplicate_result or {}
        fraud_result = fraud_result or {}
        compliance_result = compliance_result or {}
        audit_rule_results = audit_rule_results or []

        risk_factors: list[str] = []
        signal_breakdown: dict[str, float] = {}

        # ── 1. Duplicate signal ───────────────────────────────────────────────
        dup_score = float(duplicate_result.get("duplicate_score", 0.0))
        dup_component = dup_score * WEIGHTS["duplicate"] * 100
        signal_breakdown["duplicate"] = round(dup_component, 2)
        if dup_score >= 0.70:
            risk_factors.extend(duplicate_result.get("duplicate_reasons", []))

        # ── 2. Fraud signal ───────────────────────────────────────────────────
        fraud_score = float(fraud_result.get("fraud_score", 0.0))
        fraud_component = fraud_score * WEIGHTS["fraud"] * 100
        signal_breakdown["fraud"] = round(fraud_component, 2)
        risk_factors.extend(fraud_result.get("fraud_patterns", []))

        # ── 3. Compliance signal (inverse) ────────────────────────────────────
        comp_score = float(compliance_result.get("compliance_score", 1.0))
        comp_component = (1 - comp_score) * WEIGHTS["compliance"] * 100
        signal_breakdown["compliance"] = round(comp_component, 2)
        if comp_score < 0.80:
            issues = compliance_result.get("issues", [])
            risk_factors.extend(issues[:3])  # Top 3 issues

        # ── 4. Audit rule signal ──────────────────────────────────────────────
        rule_component = self._score_audit_rules(audit_rule_results) * WEIGHTS["audit_rules"] * 100
        signal_breakdown["audit_rules"] = round(rule_component, 2)
        failed_rules = [
            r.get("explanation", r.get("rule_name", ""))
            for r in audit_rule_results
            if r.get("result") == "FAILED" and r.get("severity") in ("HIGH", "CRITICAL")
        ]
        risk_factors.extend(failed_rules[:3])

        # ── 5. Missing fields ─────────────────────────────────────────────────
        missing = self._count_missing_fields(document)
        missing_component = min(missing / len(REQUIRED_FIELDS), 1.0) * WEIGHTS["missing_fields"] * 100
        signal_breakdown["missing_fields"] = round(missing_component, 2)
        if missing > 0:
            missing_names = [f for f in REQUIRED_FIELDS if not document.get(f)]
            risk_factors.append(f"Missing required fields: {', '.join(missing_names)}")

        # ── Composite score ───────────────────────────────────────────────────
        raw_score = sum(signal_breakdown.values())

        # Critical rule override: any CRITICAL audit rule → minimum HIGH risk
        has_critical_rule = any(
            r.get("severity") == "CRITICAL" and r.get("result") == "FAILED"
            for r in audit_rule_results
        )
        if has_critical_rule:
            raw_score = max(raw_score, LEVEL_HIGH + 1)

        risk_score = min(int(round(raw_score)), 100)
        risk_level = self._to_level(risk_score)
        escalate = risk_level in ("high", "critical")

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "risk_factors": list(dict.fromkeys(risk_factors)),  # Deduplicate, preserve order
            "escalate": escalate,
            "signal_breakdown": signal_breakdown,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _score_audit_rules(self, rule_results: list[dict]) -> float:
        """
        Translate audit rule failures into a 0–1 sub-score.

        High/critical failures dominate; low/medium are additive.
        """
        if not rule_results:
            return 0.0

        failed = [r for r in rule_results if r.get("result") == "FAILED"]
        if not failed:
            return 0.0

        total_weight = 0.0
        for rule in failed:
            severity = (rule.get("severity") or "low").lower()
            total_weight += SEVERITY_SCORES.get(severity, 0.2)

        return min(total_weight / max(len(rule_results), 1), 1.0)

    def _count_missing_fields(self, document: dict) -> int:
        return sum(1 for f in REQUIRED_FIELDS if not document.get(f))

    @staticmethod
    def _to_level(score: int) -> str:
        if score >= LEVEL_CRITICAL:
            return "critical"
        if score >= LEVEL_HIGH:
            return "high"
        if score >= LEVEL_MEDIUM:
            return "medium"
        return "low"
