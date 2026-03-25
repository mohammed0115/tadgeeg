from dataclasses import dataclass, field
from typing import Any

from apps.rule_engine.rules.base import RuleResult, RuleStatus


GAAP_STATUS_MAP = {
    "passed": RuleStatus.PASS,
    "failed": RuleStatus.FAIL,
    "warning": RuleStatus.WARNING,
    "not_applicable": RuleStatus.NOT_APPLICABLE,
}


@dataclass
class GAAPRuleResult:
    rule_code: str
    title: str
    status: str
    severity: str
    observation: str
    failure_reason: str = ""
    recommendation: str = ""
    score_impact: float = 0.0
    metadata_json: dict[str, Any] = field(default_factory=dict)

    def to_rule_result(self) -> RuleResult:
        mapped_status = GAAP_STATUS_MAP.get(self.status, RuleStatus.NOT_APPLICABLE)
        explanation = self.observation or self.failure_reason or "GAAP evaluation completed"
        return RuleResult(
            status=mapped_status,
            explanation_en=explanation,
            explanation_ar=explanation,
            risk_contribution=float(self.score_impact or 0.0),
            evidence=[],
            raw_data={
                "rule_code": self.rule_code,
                "title": self.title,
                "status": self.status,
                "severity": self.severity,
                "observation": self.observation,
                "failure_reason": self.failure_reason,
                "recommendation": self.recommendation,
                "score_impact": float(self.score_impact or 0.0),
                "metadata_json": self.metadata_json,
            },
        )
