"""Risk Assessment Service — calculate overall risk from AI anomalies + validation."""

import logging

logger = logging.getLogger(__name__)


class RiskAssessmentService:
    """Calculate overall risk level from AI anomalies + validation findings."""

    # Severity weights for anomalies
    ANOMALY_SEVERITY_WEIGHT = {
        "high": 25,
        "medium": 12,
        "low": 5,
    }

    # Validation status weights
    VALIDATION_STATUS_WEIGHT = {
        "fail": 15,
        "warning": 5,
        "pass": 0,
        "not_applicable": 0,
    }

    def assess(self, ai_result: dict, validation_findings: list) -> str:
        """
        Calculate overall risk level.
        Returns: low | medium | high
        """
        score = 0
        score += self._score_anomalies(ai_result.get("anomalies", []))
        score += self._score_validation(validation_findings)
        score += self._score_confidence(ai_result.get("confidence_score", 1.0))

        # Also consider the AI's own risk assessment
        ai_risk = ai_result.get("risk_assessment", {})
        if isinstance(ai_risk, dict):
            ai_risk_level = ai_risk.get("overall_risk", "").lower()
            ai_risk_score = ai_risk.get("risk_score", 0)
            if ai_risk_level == "high":
                score += 20
            elif ai_risk_level == "medium":
                score += 10
            if isinstance(ai_risk_score, (int, float)):
                score += int(ai_risk_score * 0.2)  # 20% weight of AI's own score

        return self._score_to_level(score)

    def _score_anomalies(self, anomalies: list) -> int:
        """Score anomalies based on severity."""
        if not anomalies:
            return 0
        total = 0
        for anomaly in anomalies:
            if not isinstance(anomaly, dict):
                continue
            severity = anomaly.get("severity", "low").lower()
            weight = self.ANOMALY_SEVERITY_WEIGHT.get(severity, 5)
            total += weight
        return min(total, 60)  # Cap at 60 from anomalies

    def _score_validation(self, findings: list) -> int:
        """Score validation findings based on status."""
        if not findings:
            return 0
        total = 0
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            status = finding.get("status", "pass").lower()
            weight = self.VALIDATION_STATUS_WEIGHT.get(status, 0)
            total += weight
        return min(total, 40)  # Cap at 40 from validation

    def _score_confidence(self, confidence: float) -> int:
        """Low confidence contributes to risk score."""
        try:
            conf = float(confidence)
            # Normalize to 0-1 if given as percentage
            if conf > 1.0:
                conf = conf / 100.0
            if conf >= 0.8:
                return 0
            elif conf >= 0.6:
                return 5
            elif conf >= 0.4:
                return 15
            elif conf >= 0.2:
                return 25
            else:
                return 35
        except (TypeError, ValueError):
            return 15

    def _score_to_level(self, score: int) -> str:
        """Convert numeric score to risk level."""
        if score >= 50:
            return "high"
        elif score >= 20:
            return "medium"
        else:
            return "low"
