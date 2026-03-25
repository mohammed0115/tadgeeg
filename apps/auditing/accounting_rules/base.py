import abc
from datetime import date
from decimal import Decimal
from typing import Any

from apps.auditing.accounting_rules.enums import (
    AccountingStandard,
    EntityType,
    RuleCategory,
    RuleSeverity,
    RuleStatus,
)
from apps.auditing.accounting_rules.result import RuleResult


class AccountingRule(abc.ABC):
    code: str = ""
    title: str = ""
    description: str = ""
    standard: AccountingStandard = AccountingStandard.GAAP
    category: RuleCategory = RuleCategory.COMPLETENESS
    severity: RuleSeverity = RuleSeverity.MEDIUM
    weight: float = 1.0
    applies_to: tuple[EntityType, ...] = tuple()
    enabled_by_default: bool = True
    config_key: str | None = None

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def is_applicable(self, record: dict[str, Any], context: dict[str, Any]) -> bool:
        record_type = str(record.get("record_type") or "").lower()
        if not self.applies_to:
            return True
        return record_type in {item.value for item in self.applies_to}

    @abc.abstractmethod
    def evaluate(self, record: dict[str, Any], context: dict[str, Any]) -> RuleResult:
        ...

    def get_recommendation(self, record: dict[str, Any], context: dict[str, Any]) -> str:
        return ""

    def insufficient_data(self, reason: str, fields: list[str]) -> RuleResult:
        return RuleResult(
            rule_code=self.code,
            title=self.title,
            standard=self.standard,
            category=self.category,
            status=RuleStatus.INSUFFICIENT_DATA,
            severity=self.severity,
            observation=reason,
            failure_reason=reason,
            recommendation="Provide the missing fields and re-run evaluation.",
            score_impact=0.0,
            confidence=0.0,
            related_fields=fields,
            metadata_json={"missing_fields": fields},
        )

    @staticmethod
    def as_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except Exception:
            return default

    @staticmethod
    def as_date(value: Any) -> date | None:
        if isinstance(value, date):
            return value
        if value is None:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except Exception:
            return None
