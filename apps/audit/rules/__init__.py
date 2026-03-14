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
from .duplicate_invoice_rule import DuplicateInvoiceRule
from .vat_validation_rule import VATValidationRule
from .missing_fields_rule import MissingFieldsRule
from .amount_anomaly_rule import AmountAnomalyRule
from .date_validation_rule import DateValidationRule
from .vendor_risk_rule import VendorRiskRule

__all__ = [
    "AuditRule",
    "RuleResult",
    "Severity",
    "RuleStatus",
    "DuplicateInvoiceRule",
    "VATValidationRule",
    "MissingFieldsRule",
    "AmountAnomalyRule",
    "DateValidationRule",
    "VendorRiskRule",
]
