import abc
from datetime import date
from decimal import Decimal
from typing import Any

from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult
from apps.rule_engine.rules.gaap.result import GAAPRuleResult


class GAAPRuleBase(AuditRuleBase, abc.ABC):
    """
    Base GAAP contract.

    Each GAAP rule implements evaluate(record, context) and returns GAAPRuleResult.
    execute() adapts GAAPRuleResult back to the existing RuleResult contract.
    """

    code: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    severity: str = "medium"
    applies_to: tuple[str, ...] = tuple()
    gaap_principle: str = ""
    weight: float = 1.0

    @abc.abstractmethod
    def evaluate(self, record: dict[str, Any], context: dict[str, Any]) -> GAAPRuleResult:
        ...

    @property
    def rule_code(self) -> str:  # type: ignore[override]
        return self.code

    @property
    def rule_name_en(self) -> str:  # type: ignore[override]
        return self.title

    @property
    def default_severity(self) -> str:  # type: ignore[override]
        return self.severity

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return not self.applies_to or doc.document_type in self.applies_to

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        record = self._build_record(doc)
        context = {
            "organization_id": str(doc.organization_id),
            "document_type": doc.document_type,
            "rule_config": self.config,
        }
        return self.evaluate(record, context).to_rule_result()

    def _build_record(self, doc: NormalizedDocument) -> dict[str, Any]:
        return {
            "document_id": doc.document_id,
            "document_type": doc.document_type,
            "organization_id": doc.organization_id,
            "date": doc.document_date or doc.get("date") or doc.get("invoice_date"),
            "amount": doc.total_amount,
            "currency": doc.currency,
            "account": doc.account_code or doc.get("account_code"),
            "counterparty": doc.counterparty_name
            or doc.get("vendor_name")
            or doc.get("customer_name")
            or doc.get("counterparty"),
            "supporting_reference": doc.get("supporting_reference")
            or doc.get("invoice_number")
            or doc.document_number,
            "typed_data": doc.typed_data or {},
            "org_context": doc.org_context or {},
            "raw": doc,
        }

    @staticmethod
    def _as_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except Exception:
            return default

    @staticmethod
    def _as_date(value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except Exception:
            return None
