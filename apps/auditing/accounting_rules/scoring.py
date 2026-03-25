from collections import Counter

from apps.auditing.accounting_rules.enums import RuleStatus
from apps.auditing.accounting_rules.result import RuleResult


class RuleScoringEngine:
    def __init__(self, score_policy: dict[str, float] | None = None):
        self.score_policy = score_policy or {
            "passed": 0.0,
            "warning": 0.5,
            "failed": 1.0,
            "not_applicable": 0.0,
            "insufficient_data": 0.0,
        }

    def summarize(self, results: list[RuleResult]) -> dict:
        counts = Counter(item.status.value for item in results)
        applicable = [
            item
            for item in results
            if item.status not in (RuleStatus.NOT_APPLICABLE, RuleStatus.INSUFFICIENT_DATA)
        ]
        total_weight = sum(max(item.weighted_factor if hasattr(item, "weighted_factor") else 1.0, 0.1) for item in applicable)
        if total_weight <= 0:
            total_weight = max(len(applicable), 1)

        impact = 0.0
        for item in applicable:
            base_impact = self.score_policy.get(item.status.value, 0.0)
            impact += base_impact + float(item.score_impact or 0.0)

        compliance_score = max(0.0, round(100.0 - (impact / max(total_weight, 1.0)) * 100.0, 2))
        high_severity_findings = sum(
            1
            for item in results
            if item.status in (RuleStatus.FAILED, RuleStatus.WARNING)
            and item.severity.value in ("critical", "high")
        )

        return {
            "total_rules": len(results),
            "passed": counts.get(RuleStatus.PASSED.value, 0),
            "failed": counts.get(RuleStatus.FAILED.value, 0),
            "warning": counts.get(RuleStatus.WARNING.value, 0),
            "not_applicable": counts.get(RuleStatus.NOT_APPLICABLE.value, 0),
            "insufficient_data": counts.get(RuleStatus.INSUFFICIENT_DATA.value, 0),
            "compliance_score": compliance_score,
            "risk_impact": round(impact, 2),
            "high_severity_findings": high_severity_findings,
        }
