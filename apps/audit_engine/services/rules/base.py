from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RuleResult:
    """Returned by every audit rule after evaluation."""

    issues: List[dict] = field(default_factory=list)
    """List of issue dicts. Each dict maps to AuditIssue fields."""

    score_impact: float = 0.0
    """Cumulative score deduction produced by this rule (informational)."""

    metadata: dict = field(default_factory=dict)
    """Arbitrary metadata the rule wants to expose."""


class BaseAuditRule(ABC):
    """Abstract base for all audit rules."""

    rule_code: str = ""
    rule_name: str = ""
    audit_types: List[str] = []
    """Restrict this rule to specific audit_type values. Empty = applies to all."""

    @abstractmethod
    def apply(self, parse_result, audit_type: str, context: Optional[dict] = None) -> RuleResult:
        """
        Evaluate parse_result and return a RuleResult.

        Args:
            parse_result: ParseResult instance from a parser.
            audit_type: The AuditJob.audit_type value.
            context: Optional extra context (e.g. organisation settings).

        Returns:
            RuleResult with zero or more issues.
        """
        raise NotImplementedError
