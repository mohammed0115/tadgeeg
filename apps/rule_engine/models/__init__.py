"""
Rule Engine model package.

Import all models here so that Django's app registry can discover them and
so that callers can use ``from apps.rule_engine.models import SomeModel``
without knowing which sub-module the model lives in.
"""

from apps.rule_engine.models.rule_definition import (  # noqa: F401
    RuleCategory,
    RuleDefinition,
    RuleDefinitionTranslation,
    RuleScope,
    RuleType,
    Severity,
)
from apps.rule_engine.models.rule_assignment import (  # noqa: F401
    ApplicabilityMode,
    AssignmentStatus,
    RuleAssignment,
    SupportedDocumentType,
)
from apps.rule_engine.models.audit_execution import (  # noqa: F401
    AuditEvidence,
    AuditResult,
    AuditRun,
)
from apps.rule_engine.rules.base import RuleResult  # noqa: F401
from apps.rule_engine.models.risk import RiskScoreSummary  # noqa: F401
from apps.rule_engine.models.review import ManualReviewDecision  # noqa: F401
from apps.rule_engine.models.cross_document import CrossDocumentLink  # noqa: F401
from apps.rule_engine.models.rule_field_dependency import RuleFieldDependency  # noqa: F401
from apps.rule_engine.models.audit_run_v2 import AuditRunV2Metadata  # noqa: F401

# Legacy compatibility aliases used by older tests and callers.
ValidationRule = RuleDefinition
RuleGroup = RuleCategory

__all__ = [
    # rule_definition
    "RuleCategory",
    "RuleDefinition",
    "RuleDefinitionTranslation",
    "RuleScope",
    "RuleType",
    "Severity",
    # (RuleSeverity is an alias — use Severity directly)
    # rule_assignment
    "ApplicabilityMode",
    "AssignmentStatus",
    "RuleAssignment",
    "SupportedDocumentType",
    # audit_execution
    "AuditEvidence",
    "AuditResult",
    "AuditRun",
    "RuleResult",
    # risk
    "RiskScoreSummary",
    # review
    "ManualReviewDecision",
    # cross_document
    "CrossDocumentLink",
    # rule_field_dependency
    "RuleFieldDependency",
    # audit_run_v2
    "AuditRunV2Metadata",
    # legacy aliases
    "ValidationRule",
    "RuleGroup",
]
