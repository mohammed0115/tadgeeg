import logging
from typing import List, Optional

from apps.audit_engine.services.rules.base import BaseAuditRule
from apps.audit_engine.services.rules.generic_rules import (
    EmptyDocumentRule,
    LowPageCountRule,
    LowRowCountRule,
    MissingColumnHeadersRule,
    MissingMetadataRule,
    WeakTextContentRule,
)

logger = logging.getLogger(__name__)


class RuleRegistry:
    """
    Central registry for all audit rules.
    Rules are registered as singleton instances.
    Thread-safety note: rules are stateless, so shared instances are safe.
    """

    _rules: List[BaseAuditRule] = []

    @classmethod
    def register(cls, rule: BaseAuditRule):
        """Append a rule instance to the registry."""
        cls._rules.append(rule)

    @classmethod
    def clear(cls):
        """Remove all registered rules (mainly for testing)."""
        cls._rules = []

    @classmethod
    def get_rules_for_audit_type(cls, audit_type: str) -> List[BaseAuditRule]:
        """
        Return rules that apply to the given audit_type.
        Rules with an empty audit_types list apply universally.
        """
        return [
            rule for rule in cls._rules
            if not rule.audit_types or audit_type in rule.audit_types
        ]

    @classmethod
    def apply_all(
        cls,
        parse_result,
        audit_type: str,
        context: Optional[dict] = None,
    ) -> List[dict]:
        """
        Apply all matching rules to parse_result.

        Returns:
            Flat list of issue dicts (each maps to AuditIssue fields).
            Individual rule errors are logged and swallowed — the audit
            must never crash due to a misbehaving rule.
        """
        all_issues: List[dict] = []
        for rule in cls.get_rules_for_audit_type(audit_type):
            try:
                result = rule.apply(parse_result, audit_type, context)
                all_issues.extend(result.issues)
            except Exception as exc:
                logger.warning(
                    "Rule %s (%s) raised an unhandled exception and was skipped: %s",
                    rule.rule_code,
                    rule.rule_name,
                    exc,
                    exc_info=True,
                )
        return all_issues


# ---------------------------------------------------------------------------
# Auto-register all built-in rules at import time
# ---------------------------------------------------------------------------
for _rule_class in [
    EmptyDocumentRule,
    LowPageCountRule,
    MissingMetadataRule,
    LowRowCountRule,
    MissingColumnHeadersRule,
    WeakTextContentRule,
]:
    RuleRegistry.register(_rule_class())
