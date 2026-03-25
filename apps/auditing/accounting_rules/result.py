from dataclasses import asdict, dataclass, field
from typing import Any

from apps.auditing.accounting_rules.enums import AccountingStandard, RuleCategory, RuleSeverity, RuleStatus


@dataclass
class RuleResult:
    rule_code: str
    title: str
    standard: AccountingStandard
    category: RuleCategory
    status: RuleStatus
    severity: RuleSeverity
    observation: str
    failure_reason: str = ""
    recommendation: str = ""
    score_impact: float = 0.0
    confidence: float = 1.0
    related_fields: list[str] = field(default_factory=list)
    metadata_json: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["standard"] = self.standard.value
        payload["category"] = self.category.value
        payload["status"] = self.status.value
        payload["severity"] = self.severity.value
        return payload


@dataclass
class EvaluationResult:
    record_type: str
    record_id: str
    standard: AccountingStandard
    summary: dict[str, Any]
    results: list[RuleResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "record_id": self.record_id,
            "standard": self.standard.value,
            "summary": self.summary,
            "results": [item.to_dict() for item in self.results],
        }
