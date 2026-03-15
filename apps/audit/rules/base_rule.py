"""
Audit Rule Base Interface

All audit rules must inherit from AuditRule and implement evaluate().

Design:
  - Rules are stateless: evaluate() receives all needed data as arguments
  - Rules never raise exceptions: failures are caught and returned as errors
  - Rules return a RuleResult dataclass for consistent serialisation
  - Severity determines how failures affect the overall risk score
"""

import abc
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("finai")


class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # Immediate escalation required
    HIGH = "HIGH"           # Significant audit concern
    MEDIUM = "MEDIUM"       # Notable but not blocking
    LOW = "LOW"             # Informational


class RuleStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"         # Rule could not execute
    SKIPPED = "SKIPPED"     # Rule not applicable to this document type


@dataclass
class RuleResult:
    """
    Structured result returned by every audit rule.

    Serialises cleanly to JSON for storage in AuditCase.findings.
    """

    rule_id: str
    rule_name: str
    severity: Severity
    result: RuleStatus
    explanation: str = ""
    details: dict = field(default_factory=dict)
    document_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity.value if isinstance(self.severity, Severity) else self.severity,
            "result": self.result.value if isinstance(self.result, RuleStatus) else self.result,
            "explanation": self.explanation,
            "details": self.details,
            "document_id": self.document_id,
        }

    @property
    def failed(self) -> bool:
        return self.result == RuleStatus.FAILED

    @property
    def passed(self) -> bool:
        return self.result == RuleStatus.PASSED


class AuditRule(abc.ABC):
    """
    Abstract base class for all FinAI audit rules.

    Subclasses must set class-level attributes:
      rule_id:        Unique identifier (e.g. "R001")
      rule_name:      Human-readable name
      severity:       Default Severity for FAILED results
      applies_to:     Set of document types this rule applies to
                      (empty set = applies to all types)
      description:    Full description of what the rule checks
    """

    rule_id: str = "R000"
    rule_name: str = "Base Rule"
    severity: Severity = Severity.MEDIUM
    applies_to: set[str] = set()  # Empty = all document types
    description: str = ""

    @abc.abstractmethod
    def evaluate(
        self,
        document: dict,
        organization_id: int = None,
        context: dict = None,
    ) -> RuleResult:
        """
        Evaluate this rule against a document.

        Args:
            document:        Normalised document dict from FinancialAIEngine.
            organization_id: Organisation ID for DB queries.
            context:         Optional extra context (financial_analysis, etc.).

        Returns:
            RuleResult (never raises).
        """

    def is_applicable(self, document: dict) -> bool:
        """Return True if this rule should run for the given document."""
        if not self.applies_to:
            return True
        doc_type = (document.get("document_type") or "other").lower()
        return doc_type in {t.lower() for t in self.applies_to}

    def _pass(self, doc_id: int = None, details: dict = None) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            result=RuleStatus.PASSED,
            explanation="",
            details=details or {},
            document_id=doc_id,
        )

    def _fail(self, explanation: str, doc_id: int = None, details: dict = None) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            result=RuleStatus.FAILED,
            explanation=explanation,
            details=details or {},
            document_id=doc_id,
        )

    def _skip(self, reason: str = "Not applicable") -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            result=RuleStatus.SKIPPED,
            explanation=reason,
        )

    def _error(self, exc: Exception) -> RuleResult:
        logger.error("[Rule %s] Evaluation error: %s", self.rule_id, exc)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            result=RuleStatus.ERROR,
            explanation=f"Rule evaluation failed: {exc}",
        )
