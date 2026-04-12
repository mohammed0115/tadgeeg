"""
Base rule interface for the Tadgeeg Document Audit Rule Engine.

All rule implementations MUST inherit from AuditRuleBase and implement execute().
Rules are stateless — they receive a NormalizedDocument and return a RuleResult.
Rules must NEVER raise exceptions; use try/except internally and return ERROR status.
"""

import abc
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("rule_engine")


class RuleStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    NOT_APPLICABLE = "not_applicable"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class EvidenceItem:
    evidence_type: str  # field_value, calculation, comparison, reference, cross_document, statistical
    field_name: str = ""
    field_name_ar: str = ""
    expected_value: Any = None
    actual_value: Any = None
    description: str = ""
    description_ar: str = ""
    linked_document_type: str = ""
    linked_document_id: str = ""

    def to_dict(self) -> dict:
        return {
            "evidence_type": self.evidence_type,
            "field_name": self.field_name,
            "field_name_ar": self.field_name_ar,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "description": self.description,
            "description_ar": self.description_ar,
            "linked_document_type": self.linked_document_type,
            "linked_document_id": self.linked_document_id,
        }


@dataclass
class RuleResult:
    status: RuleStatus
    explanation_en: str
    explanation_ar: str = ""
    rule_code: str = ""
    catalog_code: str = ""
    legacy_rule_code: str = ""
    is_blocking: bool = False
    risk_contribution: float = 0.0
    evidence: list = field(default_factory=list)  # list[EvidenceItem]
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self):
        identifier = self.legacy_rule_code or self.rule_code
        if not identifier:
            return
        try:
            from apps.rule_engine.catalog import resolve_rule_catalog_metadata

            entry = resolve_rule_catalog_metadata(identifier)
            self.catalog_code = entry.rule_code
            self.rule_code = entry.rule_code
            if not self.legacy_rule_code:
                self.legacy_rule_code = identifier
            self.is_blocking = bool(self.is_blocking or entry.is_blocking)
        except Exception:
            if not self.catalog_code:
                self.catalog_code = self.rule_code

    def to_dict(self) -> dict:
        return {
            "status": self.status.value if isinstance(self.status, RuleStatus) else self.status,
            "explanation_en": self.explanation_en,
            "explanation_ar": self.explanation_ar,
            "rule_code": self.rule_code,
            "catalog_code": self.catalog_code,
            "legacy_rule_code": self.legacy_rule_code,
            "is_blocking": self.is_blocking,
            "risk_contribution": float(self.risk_contribution),
            "evidence_count": len(self.evidence),
            "evidence": [e.to_dict() if hasattr(e, 'to_dict') else e for e in self.evidence],
            "raw_data": self.raw_data,
        }

    @property
    def failed(self) -> bool:
        return self.status == RuleStatus.FAIL

    @property
    def passed(self) -> bool:
        return self.status == RuleStatus.PASS

    @property
    def is_warning(self) -> bool:
        return self.status == RuleStatus.WARNING


@dataclass
class NormalizedDocument:
    """
    Canonical structure passed to all rules.
    Rules access common fields directly; document-type-specific data via typed_data dict.
    This decouples rules from specific Django model implementations.
    """
    document_id: str
    document_type: str  # sales_invoice, purchase_order, bank_statement, payroll, expense, tax_return, fixed_asset, sales_receipt, other
    organization_id: str
    language: str = "ar"

    # Common fields — all document types
    document_number: Optional[str] = None
    document_date: Any = None  # date or str
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    counterparty_name: Optional[str] = None
    tax_id: Optional[str] = None
    file_hash: Optional[str] = None

    # Workflow
    status: Optional[str] = None
    approved_by_id: Optional[str] = None
    cost_center: Optional[str] = None
    account_code: Optional[str] = None
    budget_limit: Optional[float] = None

    # Document-type specific structured data (all type-specific fields go here)
    typed_data: dict = field(default_factory=dict)

    # OCR / extraction metadata
    ocr_confidence: Optional[float] = None
    is_handwritten: bool = False
    extraction_method: str = "ai"

    # Organization context (registration date, fiscal year, approved vendor list, etc.)
    org_context: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Safe access to typed_data fields."""
        return self.typed_data.get(key, default)

    def get_org(self, key: str, default: Any = None) -> Any:
        """Safe access to org_context fields."""
        return self.org_context.get(key, default)

    def is_low_confidence(self, threshold: float = 0.7) -> bool:
        """Returns True if OCR confidence is below threshold."""
        if self.ocr_confidence is None:
            return False
        return self.ocr_confidence < threshold


class AuditRuleBase(abc.ABC):
    """
    Abstract base class for all audit rules in the Document Rule Engine.

    Subclasses must:
    1. Set class attributes: rule_code, rule_name_en, rule_name_ar, default_severity
    2. Implement execute(doc: NormalizedDocument) -> RuleResult

    Subclasses may:
    - Override check_preconditions() to skip rule when data is insufficient
    - Override __init__ to add initialization logic (must call super().__init__(config))
    - Set field_dependencies to list canonical field codes this rule reads
    """

    # Override in each rule class
    rule_code: str = ""
    rule_name_en: str = ""
    rule_name_ar: str = ""
    default_severity: str = "medium"
    rule_type: str = "validation"  # validation, compliance, anomaly, reconciliation, risk
    catalog_code: str = ""
    is_blocking: bool = False

    # List of canonical field_codes this rule requires.
    # If set, the pipeline skips the rule when ANY listed field is absent from
    # the document's DocumentCanonicalData record.
    field_dependencies: list = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__name__ == "AuditRuleBase":
            return
        identifier = getattr(cls, "rule_code", "")
        if not identifier:
            return
        try:
            from apps.rule_engine.catalog import resolve_rule_catalog_metadata

            entry = resolve_rule_catalog_metadata(
                identifier,
                rule_name=getattr(cls, "rule_name_en", "") or getattr(cls, "rule_name_ar", ""),
                rule_type=getattr(cls, "rule_type", ""),
                severity=getattr(cls, "default_severity", "medium"),
            )
            cls.catalog_code = entry.rule_code
            cls.is_blocking = entry.is_blocking
        except Exception:
            cls.catalog_code = identifier
            cls.is_blocking = str(getattr(cls, "default_severity", "")).lower() == "critical"

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, falling back to default."""
        return self.config.get(key, default)

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        """
        Return False to SKIP this rule (e.g., required fields are missing).
        Default: always run.
        Override in rules that require specific fields to be present.
        """
        return True

    @abc.abstractmethod
    def execute(self, doc: NormalizedDocument) -> RuleResult:
        """
        Core rule logic. Must return a RuleResult.
        Must NEVER raise exceptions — catch all errors and return error status.
        """
        ...

    # ── Convenience builders ──────────────────────────────────────────────────

    def _pass(
        self,
        explanation_en: str,
        explanation_ar: str = "",
        evidence: Optional[list] = None,
    ) -> RuleResult:
        return RuleResult(
            status=RuleStatus.PASS,
            explanation_en=explanation_en,
            explanation_ar=explanation_ar or explanation_en,
            rule_code=self.catalog_code or self.rule_code,
            catalog_code=self.catalog_code or self.rule_code,
            legacy_rule_code=self.rule_code,
            is_blocking=self.is_blocking,
            risk_contribution=0.0,
            evidence=evidence or [],
        )

    def _fail(
        self,
        explanation_en: str,
        explanation_ar: str = "",
        evidence: Optional[list] = None,
        risk: float = 1.0,
    ) -> RuleResult:
        return RuleResult(
            status=RuleStatus.FAIL,
            explanation_en=explanation_en,
            explanation_ar=explanation_ar or explanation_en,
            rule_code=self.catalog_code or self.rule_code,
            catalog_code=self.catalog_code or self.rule_code,
            legacy_rule_code=self.rule_code,
            is_blocking=self.is_blocking,
            risk_contribution=risk,
            evidence=evidence or [],
        )

    def _warning(
        self,
        explanation_en: str,
        explanation_ar: str = "",
        evidence: Optional[list] = None,
        risk: float = 0.5,
    ) -> RuleResult:
        return RuleResult(
            status=RuleStatus.WARNING,
            explanation_en=explanation_en,
            explanation_ar=explanation_ar or explanation_en,
            rule_code=self.catalog_code or self.rule_code,
            catalog_code=self.catalog_code or self.rule_code,
            legacy_rule_code=self.rule_code,
            is_blocking=self.is_blocking,
            risk_contribution=risk,
            evidence=evidence or [],
        )

    def _not_applicable(
        self,
        reason_en: str = "Not applicable to this document type",
        reason_ar: str = "غير قابل للتطبيق على هذا النوع من المستندات",
    ) -> RuleResult:
        return RuleResult(
            status=RuleStatus.NOT_APPLICABLE,
            explanation_en=reason_en,
            explanation_ar=reason_ar or "غير قابل للتطبيق على هذا النوع من المستندات",
            rule_code=self.catalog_code or self.rule_code,
            catalog_code=self.catalog_code or self.rule_code,
            legacy_rule_code=self.rule_code,
            is_blocking=self.is_blocking,
            risk_contribution=0.0,
        )

    def _skipped(
        self,
        reason_en: str = "Preconditions not met",
        reason_ar: str = "تم تخطي القاعدة: البيانات المطلوبة غير متوفرة",
    ) -> RuleResult:
        return RuleResult(
            status=RuleStatus.SKIPPED,
            explanation_en=reason_en,
            explanation_ar=reason_ar or "تم تخطي القاعدة: البيانات المطلوبة غير متوفرة",
            rule_code=self.catalog_code or self.rule_code,
            catalog_code=self.catalog_code or self.rule_code,
            legacy_rule_code=self.rule_code,
            is_blocking=self.is_blocking,
            risk_contribution=0.0,
        )

    def _error(self, exc: Exception, rule_code: str = "") -> RuleResult:
        logger.exception(f"Rule {rule_code or self.rule_code} execution error: {exc}")
        return RuleResult(
            status=RuleStatus.ERROR,
            explanation_en=f"Rule execution failed: {type(exc).__name__}: {exc}",
            explanation_ar="فشل تنفيذ القاعدة بسبب خطأ تقني",
            rule_code=self.catalog_code or self.rule_code,
            catalog_code=self.catalog_code or self.rule_code,
            legacy_rule_code=self.rule_code,
            is_blocking=self.is_blocking,
            risk_contribution=0.0,
        )

    def get_canonical_field(self, doc: NormalizedDocument, field_code: str, default: Any = None) -> Any:
        """
        Read a field from the DocumentCanonicalData record for this document.
        Returns `default` if the record or field is absent.
        Use this when a rule needs authoritative canonical data rather than
        the in-memory NormalizedDocument (e.g. for cross-rule consistency).
        """
        try:
            from apps.documents.canonical_models import DocumentCanonicalData
            rec = DocumentCanonicalData.objects.filter(
                typed_object_id=str(doc.document_id)
            ).first()
            if rec:
                return rec.canonical_data.get(field_code, default)
        except Exception as exc:
            logger.debug("get_canonical_field(%s, %s) failed: %s", doc.document_id, field_code, exc)
        return default

    def safe_decimal(self, value: Any, default: Decimal = Decimal("0")) -> Decimal:
        """Safely convert any value to Decimal."""
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except Exception:
            return default

    def safe_float(self, value: Any, default: float = 0.0) -> float:
        """Safely convert any value to float."""
        if value is None:
            return default
        try:
            return float(value)
        except Exception:
            return default
