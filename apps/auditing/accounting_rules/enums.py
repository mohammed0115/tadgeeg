from enum import Enum


class AccountingStandard(str, Enum):
    GAAP = "GAAP"
    IFRS = "IFRS"


class RuleCategory(str, Enum):
    RECOGNITION = "recognition"
    CLASSIFICATION = "classification"
    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    CUTOFF = "cutoff"
    DOCUMENTATION = "documentation"
    ANOMALY = "anomaly"
    DISCLOSURE = "disclosure"


class RuleSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RuleStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_DATA = "insufficient_data"


class EntityType(str, Enum):
    INVOICE = "invoice"
    JOURNAL_ENTRY = "journal_entry"
    EXPENSE = "expense"
    PAYMENT = "payment"
    VENDOR_BILL = "vendor_bill"
    DOCUMENT = "document"
    AUDIT_CASE = "audit_case"
