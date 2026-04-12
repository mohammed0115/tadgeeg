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
    catalog_code: str = ""
    legacy_rule_code: str = ""
    is_blocking: bool = False
    failure_reason: str = ""
    recommendation: str = ""
    score_impact: float = 0.0
    confidence: float = 1.0
    related_fields: list[str] = field(default_factory=list)
    metadata_json: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        identifier = self.legacy_rule_code or self.rule_code
        if not identifier:
            return
        try:
            from apps.rule_engine.catalog import resolve_rule_catalog_metadata

            entry = resolve_rule_catalog_metadata(
                identifier,
                rule_name=self.title,
                rule_type=self.category.value,
                severity=self.severity.value,
            )
            self.catalog_code = entry.rule_code
            if not self.legacy_rule_code:
                self.legacy_rule_code = identifier
            self.rule_code = entry.rule_code
            self.is_blocking = bool(self.is_blocking or entry.is_blocking)
        except Exception:
            if not self.catalog_code:
                self.catalog_code = self.rule_code

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
