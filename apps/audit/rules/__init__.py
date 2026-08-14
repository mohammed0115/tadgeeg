"""
Audit Rules Package

All audit rules implement the AuditRule interface defined in base_rule.py.
Rules are auto-discovered by the registry in audit_engine.py.

To add a new rule:
  1. Create a file in this directory (e.g., my_new_rule.py)
  2. Implement a class that extends AuditRule
  3. Register it in REGISTERED_RULES in audit_engine.py
"""

from .base_rule import AuditRule, RuleResult, Severity, RuleStatus
__all__ = [
    "AuditRule",
    "RuleResult",
    "Severity",
    "RuleStatus",
]
