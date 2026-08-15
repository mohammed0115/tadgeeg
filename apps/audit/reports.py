"""Audit-report contract shared by the document pipeline and its serialiser.

`AuditReport` was moved here from ``apps.audit.audit_engine`` when the legacy
engine was removed. It is a data contract rather than engine behaviour: the
pipeline serialiser reads its fields, and compatibility adapters satisfy the
same shape. It must not be deleted with the legacy engine.
"""

from dataclasses import dataclass, field
from typing import Optional

from .rules.base_rule import AuditRule, RuleResult, RuleStatus, Severity


@dataclass
class AuditReport:
    """
    Complete result of running all audit rules against a document.
    """

    document_id: Optional[int] = None
    rule_results: list[RuleResult] = field(default_factory=list)
    risk_score: int = 0
    risk_level: str = "low"
    total_rules: int = 0
    passed_rules: int = 0
    failed_rules: int = 0
    skipped_rules: int = 0
    error_rules: int = 0
    escalate: bool = False
    processing_time_ms: int = 0
    summary: str = ""

    # ── The `*_count` aliases, and why both names exist ─────────────────────
    #
    # `core/services/pipeline.py::_serialise_audit_report` reads eleven names
    # off a report. Seven of them are the fields above. The other four it
    # spells `passed_count`, `failed_count`, `skipped_count`, `error_count` —
    # and this class spelled them `*_rules`.
    #
    # The `*_count` spelling is the contract, not this class's preference:
    # `AuditRunResult` in
    # apps/rule_engine/services/compatibility/legacy_audit_adapter.py exposes
    # exactly these four names for exactly this caller. Whichever engine the
    # documents path routes to, the serialiser must find them.
    #
    # Aliases rather than a rename: `passed_rules` and its siblings are read
    # elsewhere, and renaming a field that works to fix one that does not is
    # how a caller breaks silently. An alias costs nothing — the same choice
    # AuditRunResult made.
    #
    # The names are not maintained by hand:
    # tests/test_documents_path_parity.py extracts them from the serialiser
    # with `ast` and fails if a twelfth appears.

    @property
    def passed_count(self) -> int:
        return self.passed_rules

    @property
    def failed_count(self) -> int:
        return self.failed_rules

    @property
    def skipped_count(self) -> int:
        return self.skipped_rules

    @property
    def error_count(self) -> int:
        return self.error_rules

    @property
    def failed_results(self) -> list[RuleResult]:
        return [r for r in self.rule_results if r.result == RuleStatus.FAILED]

    @property
    def critical_failures(self) -> list[RuleResult]:
        return [
            r for r in self.failed_results
            if r.severity in (Severity.CRITICAL, "CRITICAL")
        ]

    @property
    def high_failures(self) -> list[RuleResult]:
        return [
            r for r in self.failed_results
            if r.severity in (Severity.HIGH, "HIGH")
        ]

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "rule_results": [r.to_dict() for r in self.rule_results],
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "total_rules": self.total_rules,
            "passed_rules": self.passed_rules,
            "failed_rules": self.failed_rules,
            "skipped_rules": self.skipped_rules,
            "error_rules": self.error_rules,
            "escalate": self.escalate,
            "processing_time_ms": self.processing_time_ms,
            "summary": self.summary,
        }
