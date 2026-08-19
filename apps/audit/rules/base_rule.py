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
    rule_code: str = ""
    catalog_code: str = ""
    legacy_rule_code: str = ""
    is_blocking: bool = False
    explanation: str = ""
    details: dict = field(default_factory=dict)
    document_id: Optional[int] = None

    def __post_init__(self):
        identifier = self.legacy_rule_code or self.rule_code or self.rule_id
        if not identifier:
            return
        try:
            from apps.rule_engine.catalog import resolve_rule_catalog_metadata

            entry = resolve_rule_catalog_metadata(identifier, severity=self.severity)
            self.catalog_code = entry.rule_code
            self.rule_code = entry.rule_code
            if not self.legacy_rule_code:
                self.legacy_rule_code = identifier
            self.is_blocking = bool(self.is_blocking or entry.is_blocking)
        except ImportError:
            # The catalogue module is shadowed by a package of the same
            # name, deliberately — see the header of apps/rule_engine/catalog.py
            # and docs/CATALOG_SHADOW_IMPACT.md. Expected, so warned once and
            # not raised: seven call sites in four apps take this path for every
            # rule, and raising would stop a product that works today.
            if not globals().get("_CATALOG_SHADOW_WARNED"):
                globals()["_CATALOG_SHADOW_WARNED"] = True
                logger.warning(
                    "rule catalogue unavailable (apps/rule_engine/catalog.py is "
                    "shadowed by the package of the same name); catalog_code "
                    "falls back to the raw rule code"
                )
            if not self.catalog_code:
                self.catalog_code = self.rule_code or identifier
        except Exception as exc:
            # Anything that is not the shadowing is unexpected, and used to be
            # indistinguishable from it: one `except Exception` answered both.
            logger.error(
                "rule catalogue lookup failed for %s: %s: %s",
                identifier, type(exc).__name__, exc,
            )
            if not self.catalog_code:
                self.catalog_code = self.rule_code or identifier

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "rule_code": self.rule_code,
            "catalog_code": self.catalog_code,
            "legacy_rule_code": self.legacy_rule_code,
            "is_blocking": self.is_blocking,
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
    Abstract base class for all Tadgeeg AI audit rules.

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
    catalog_code: str = ""
    is_blocking: bool = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "AuditRule":
            return
        identifier = getattr(cls, "rule_id", "")
        if not identifier:
            return
        try:
            from apps.rule_engine.catalog import resolve_rule_catalog_metadata

            entry = resolve_rule_catalog_metadata(
                identifier,
                rule_name=getattr(cls, "rule_name", ""),
                severity=getattr(cls, "severity", Severity.MEDIUM),
            )
            cls.catalog_code = entry.rule_code
            cls.is_blocking = entry.is_blocking
        except ImportError:
            # The catalogue module is shadowed by a package of the same
            # name, deliberately — see the header of apps/rule_engine/catalog.py
            # and docs/CATALOG_SHADOW_IMPACT.md. Expected, so warned once and
            # not raised: seven call sites in four apps take this path for every
            # rule, and raising would stop a product that works today.
            if not globals().get("_CATALOG_SHADOW_WARNED"):
                globals()["_CATALOG_SHADOW_WARNED"] = True
                logger.warning(
                    "rule catalogue unavailable (apps/rule_engine/catalog.py is "
                    "shadowed by the package of the same name); catalog_code "
                    "falls back to the raw rule code"
                )
            cls.catalog_code = identifier
            cls.is_blocking = getattr(cls, "severity", Severity.MEDIUM) == Severity.CRITICAL
        except Exception as exc:
            # Anything that is not the shadowing is unexpected, and used to be
            # indistinguishable from it: one `except Exception` answered both.
            logger.error(
                "rule catalogue lookup failed for %s: %s: %s",
                identifier, type(exc).__name__, exc,
            )
            cls.catalog_code = identifier
            cls.is_blocking = getattr(cls, "severity", Severity.MEDIUM) == Severity.CRITICAL

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
            rule_code=self.catalog_code or self.rule_id,
            catalog_code=self.catalog_code or self.rule_id,
            legacy_rule_code=self.rule_id,
            is_blocking=self.is_blocking,
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
            rule_code=self.catalog_code or self.rule_id,
            catalog_code=self.catalog_code or self.rule_id,
            legacy_rule_code=self.rule_id,
            is_blocking=self.is_blocking,
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
            rule_code=self.catalog_code or self.rule_id,
            catalog_code=self.catalog_code or self.rule_id,
            legacy_rule_code=self.rule_id,
            is_blocking=self.is_blocking,
            explanation=reason,
        )

    def _error(self, exc: Exception) -> RuleResult:
        logger.error("[Rule %s] Evaluation error: %s", self.rule_id, exc)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            result=RuleStatus.ERROR,
            rule_code=self.catalog_code or self.rule_id,
            catalog_code=self.catalog_code or self.rule_id,
            legacy_rule_code=self.rule_id,
            is_blocking=self.is_blocking,
            explanation=f"Rule evaluation failed: {exc}",
        )
