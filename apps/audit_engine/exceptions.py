class AuditJobError(Exception):
    """Raised when an audit job fails to run or encounters a fatal error."""


class AuditParsingError(Exception):
    """Raised when a file cannot be parsed by any registered parser."""


class AuditRuleError(Exception):
    """Raised when an audit rule encounters an unrecoverable error."""


class AuditScoringError(Exception):
    """Raised when the scoring service cannot calculate a score."""
