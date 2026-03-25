from typing import List


class AuditScoringService:
    """
    Calculates an overall audit score (0–100) by deducting points per issue severity.
    Maps the final score to a risk level bucket.
    """

    SEVERITY_DEDUCTIONS = {
        "low": 2,
        "medium": 5,
        "high": 10,
        "critical": 20,
    }

    # Descending threshold → risk level mapping
    RISK_THRESHOLDS = [
        (90, "low"),
        (70, "medium"),
        (50, "high"),
        (0, "critical"),
    ]

    def calculate(self, issues: List[dict]) -> dict:
        """
        Calculate audit score from a list of issue dicts.

        Args:
            issues: List of dicts, each containing at minimum a 'severity' key.

        Returns:
            dict with keys:
              - overall_score (float, 0–100)
              - risk_level (str: low | medium | high | critical)
              - deductions (dict: severity → total points deducted)
              - issue_count (int)
        """
        score = 100.0
        deductions: dict = {"low": 0, "medium": 0, "high": 0, "critical": 0}

        for issue in issues:
            sev = issue.get("severity", "low").lower()
            deduction = self.SEVERITY_DEDUCTIONS.get(sev, 2)
            score -= deduction
            deductions[sev] = deductions.get(sev, 0) + deduction

        score = max(0.0, score)
        risk_level = self._score_to_risk(score)

        return {
            "overall_score": round(score, 2),
            "risk_level": risk_level,
            "deductions": deductions,
            "issue_count": len(issues),
        }

    def _score_to_risk(self, score: float) -> str:
        for threshold, level in self.RISK_THRESHOLDS:
            if score >= threshold:
                return level
        return "critical"
