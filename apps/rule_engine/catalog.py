from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class RuleCategory(str, Enum):
    COMPLETENESS = "CMT"
    FIELD_INTEGRITY = "FLD"
    FINANCIAL_ARITHMETIC = "FIN"
    COMPLIANCE = "CMP"
    DUPLICATE_DETECTION = "DUP"
    FRAUD_INDICATORS = "FRD"
    RISK_ANOMALY = "RSK"
    WORKFLOW_CONTROL = "WFL"


@dataclass(slots=True)
class RuleCatalogEntry:
    rule_code: str
    category: RuleCategory
    severity: str
    is_blocking: bool
    description_ar: str
    description_en: str
    supported_doc_types: list[str]
    failure_message_ar: str
    failure_message_en: str
    recommended_action_ar: str
    recommended_action_en: str
    required_fields: list[str] = field(default_factory=list)
    legacy_rule_codes: list[str] = field(default_factory=list)


def _register(entry: RuleCatalogEntry) -> RuleCatalogEntry:
    RULE_CATALOG[entry.rule_code] = entry
    for legacy_code in entry.legacy_rule_codes:
        LEGACY_RULE_CODE_MAP[legacy_code] = entry.rule_code
    return entry


RULE_CATALOG: dict[str, RuleCatalogEntry] = {}
LEGACY_RULE_CODE_MAP: dict[str, str] = {}


_register(
    RuleCatalogEntry(
        rule_code="CMT-001",
        category=RuleCategory.COMPLETENESS,
        severity="critical",
        is_blocking=True,
        description_ar="حقول مطلوبة مفقودة",
        description_en="Required fields are missing",
        supported_doc_types=["*"],
        failure_message_ar="يجب تعبئة جميع الحقول الإلزامية قبل الاعتماد.",
        failure_message_en="All required fields must be filled before approval.",
        recommended_action_ar="أكمل الحقول المطلوبة الناقصة.",
        recommended_action_en="Complete the missing required fields.",
        legacy_rule_codes=["R003"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="CMT-002",
        category=RuleCategory.COMPLETENESS,
        severity="high",
        is_blocking=True,
        description_ar="بيانات الشراء غير مكتملة",
        description_en="Purchase document completeness is insufficient",
        supported_doc_types=["purchase_order"],
        failure_message_ar="مستند الشراء يفتقد بيانات تشغيلية أو مرجعية أساسية.",
        failure_message_en="The purchase document is missing essential operational or reference data.",
        recommended_action_ar="استكمل رقم المستند والمرجع والجهة الطالبة والبيانات المساندة.",
        recommended_action_en="Complete the document number, reference, requester, and supporting data.",
    )
)
_register(
    RuleCatalogEntry(
        rule_code="FIN-001",
        category=RuleCategory.FINANCIAL_ARITHMETIC,
        severity="critical",
        is_blocking=True,
        description_ar="المجموع الكلي لا يساوي المجموع الفرعي + الضريبة",
        description_en="Total amount does not equal subtotal + tax",
        supported_doc_types=["purchase_invoice", "sales_invoice", "purchase_order", "invoice"],
        failure_message_ar="خطأ في الحساب: المجموع الكلي لا يطابق المجموع الفرعي + الضريبة.",
        failure_message_en="Calculation error: total does not equal subtotal plus tax.",
        recommended_action_ar="راجع مبالغ البنود والضريبة.",
        recommended_action_en="Review line item amounts and tax calculation.",
        required_fields=["subtotal", "vat_amount", "total_amount"],
        legacy_rule_codes=["VAT-02"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="FIN-002",
        category=RuleCategory.FINANCIAL_ARITHMETIC,
        severity="critical",
        is_blocking=True,
        description_ar="المدين لا يساوي الدائن في القيد المحاسبي",
        description_en="Debit total does not equal credit total in journal entry",
        supported_doc_types=["journal_entry"],
        failure_message_ar="القيد المحاسبي غير متوازن: المدين لا يساوي الدائن.",
        failure_message_en="Journal entry is not balanced: debit does not equal credit.",
        recommended_action_ar="تحقق من مبالغ المدين والدائن.",
        recommended_action_en="Verify debit and credit amounts.",
        required_fields=["debit_total", "credit_total"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="FIN-003",
        category=RuleCategory.FINANCIAL_ARITHMETIC,
        severity="critical",
        is_blocking=True,
        description_ar="الرصيد الختامي لا يطابق الرصيد الافتتاحي والمعاملات",
        description_en="Closing balance does not match opening balance and transactions",
        supported_doc_types=["bank_statement"],
        failure_message_ar="خطأ في مطابقة كشف الحساب البنكي.",
        failure_message_en="Bank statement reconciliation failed.",
        recommended_action_ar="راجع قائمة المعاملات والأرصدة.",
        recommended_action_en="Review transaction list and balances.",
        required_fields=["opening_balance", "closing_balance", "transactions"],
        legacy_rule_codes=["BNK-M01"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="CMP-001",
        category=RuleCategory.COMPLIANCE,
        severity="critical",
        is_blocking=True,
        description_ar="الرقم الضريبي مفقود أو غير صالح",
        description_en="Tax Registration Number is missing or invalid",
        supported_doc_types=["purchase_invoice", "sales_invoice", "invoice"],
        failure_message_ar="يجب أن يحتوي المستند على رقم ضريبي صالح.",
        failure_message_en="The document must contain a valid tax registration number.",
        recommended_action_ar="تحقق من الرقم الضريبي للمورد أو العميل.",
        recommended_action_en="Verify the supplier or customer tax registration number.",
        required_fields=["vendor_vat_number"],
        legacy_rule_codes=["R002", "VAT-04"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="CMP-002",
        category=RuleCategory.COMPLIANCE,
        severity="critical",
        is_blocking=True,
        description_ar="لا يوجد موافق على المستند",
        description_en="Document has no approver assigned",
        supported_doc_types=["purchase_order", "payroll"],
        failure_message_ar="يجب تحديد موافق على المستند قبل الاعتماد.",
        failure_message_en="An approver must be assigned before document approval.",
        recommended_action_ar="عيّن موافقاً مخولاً للمستند.",
        recommended_action_en="Assign an authorized approver to the document.",
        required_fields=["approver"],
        legacy_rule_codes=["CTL-05"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="DUP-001",
        category=RuleCategory.DUPLICATE_DETECTION,
        severity="high",
        is_blocking=True,
        description_ar="رقم مستند مكرر لنفس المورد",
        description_en="Duplicate document number for the same counterparty",
        supported_doc_types=["purchase_invoice", "sales_invoice", "invoice"],
        failure_message_ar="يوجد مستند بنفس الرقم لهذا الطرف.",
        failure_message_en="A document with the same number already exists for this counterparty.",
        recommended_action_ar="تحقق من رقم المستند أو ارجع إلى الأصل.",
        recommended_action_en="Verify the document number or reference the original document.",
        legacy_rule_codes=["R001", "DUP-01"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="DUP-002",
        category=RuleCategory.DUPLICATE_DETECTION,
        severity="high",
        is_blocking=True,
        description_ar="محتوى الملف مطابق لملف سبق رفعه",
        description_en="File content is identical to a previously uploaded file",
        supported_doc_types=["*"],
        failure_message_ar="هذا الملف تم رفعه من قبل ببصمة متطابقة.",
        failure_message_en="This file was already uploaded with an identical fingerprint.",
        recommended_action_ar="تحقق إن كان هذا تكراراً غير مقصود.",
        recommended_action_en="Verify whether this is an unintended duplicate upload.",
        legacy_rule_codes=["DUP-04", "AI-R08"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="FRD-001",
        category=RuleCategory.FRAUD_INDICATORS,
        severity="high",
        is_blocking=False,
        description_ar="مبلغ غير طبيعي مقارنة بالتاريخ السابق",
        description_en="Amount is unusual compared with historical patterns",
        supported_doc_types=["purchase_invoice", "purchase_order", "invoice"],
        failure_message_ar="المبلغ يتجاوز النمط التاريخي المتوقع بشكل ملحوظ.",
        failure_message_en="The amount materially exceeds the expected historical pattern.",
        recommended_action_ar="أجر مراجعة إضافية من الإدارة المالية.",
        recommended_action_en="Perform an additional finance-management review.",
        legacy_rule_codes=["R004", "ANO-01"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="RSK-001",
        category=RuleCategory.RISK_ANOMALY,
        severity="high",
        is_blocking=False,
        description_ar="مؤشرات مخاطر المورد أو الطرف المقابل مرتفعة",
        description_en="Vendor or counterparty risk indicators are elevated",
        supported_doc_types=["*"],
        failure_message_ar="تم رصد مؤشرات مخاطر مرتفعة للطرف المقابل.",
        failure_message_en="Elevated counterparty risk indicators were detected.",
        recommended_action_ar="يتطلب هذا المستند مراجعة أعمق قبل المتابعة.",
        recommended_action_en="This document requires deeper review before proceeding.",
        legacy_rule_codes=["R006"],
    )
)
_register(
    RuleCatalogEntry(
        rule_code="WFL-001",
        category=RuleCategory.WORKFLOW_CONTROL,
        severity="critical",
        is_blocking=True,
        description_ar="لا يمكن ترحيل مستند غير معتمد",
        description_en="Cannot post a document that has not been approved",
        supported_doc_types=["*"],
        failure_message_ar="يجب اعتماد المستند قبل الترحيل.",
        failure_message_en="Document must be approved before posting.",
        recommended_action_ar="أكمل دورة الاعتماد أولاً.",
        recommended_action_en="Complete the approval workflow first.",
        legacy_rule_codes=["CTL-04"],
    )
)


_DOC_TYPES_BY_PREFIX = {
    "AI": ["*"],
    "ANO": ["*"],
    "BNK": ["bank_statement"],
    "CDR": ["purchase_invoice", "purchase_order", "bank_statement", "payroll"],
    "CTL": ["*"],
    "DUP": ["*"],
    "EXP": ["expense_report"],
    "FIX": ["fixed_asset"],
    "GAAP": ["journal_entry", "financial_statement"],
    "GEN": ["*"],
    "GRN": ["goods_receipt", "purchase_order"],
    "IFRS": ["journal_entry", "financial_statement"],
    "INV": ["purchase_invoice", "sales_invoice", "invoice"],
    "PAY": ["payroll"],
    "PMT": ["payment"],
    "PO": ["purchase_order"],
    "R": ["invoice"],
    "REC": ["sales_receipt"],
    "SEC": ["*"],
    "TAX": ["tax_declaration"],
    "VAT": ["purchase_invoice", "sales_invoice", "invoice"],
}


def _normalize_severity(value) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "medium").strip().lower()
    if text in {"critical", "high", "medium", "low", "info"}:
        return text
    if text in {"passed", "failed", "error", "skipped", "warning"}:
        return "medium"
    return "medium"


def _infer_category(rule_identifier: str, rule_name: str = "", rule_type: str = "") -> RuleCategory:
    text = " ".join(filter(None, [rule_identifier, rule_name, rule_type])).lower()
    if any(token in text for token in ["duplicate", "dup", "fingerprint", "hash"]):
        return RuleCategory.DUPLICATE_DETECTION
    if any(token in text for token in ["approval", "approver", "workflow", "audit trail", "self approval", "no edit", "overlap"]):
        return RuleCategory.WORKFLOW_CONTROL
    if any(token in text for token in ["reconciliation", "arithmetic", "amount match", "total", "balance", "salary", "debit", "credit", "vat calculation", "threshold"]):
        return RuleCategory.FINANCIAL_ARITHMETIC
    if any(token in text for token in ["fraud", "ghost", "alteration", "structuring", "benford", "cluster", "spike", "weekend transaction", "late night"]):
        return RuleCategory.FRAUD_INDICATORS
    if any(token in text for token in ["risk", "anomaly", "confidence", "handwritten", "clarity", "dominance"]):
        return RuleCategory.RISK_ANOMALY
    if any(token in text for token in ["missing", "required", "completeness", "present", "receipt", "currency", "qr", "documentation"]):
        return RuleCategory.COMPLETENESS
    if any(token in text for token in ["format", "date", "iban", "classification", "quality inspection"]):
        return RuleCategory.FIELD_INTEGRITY
    return RuleCategory.COMPLIANCE


def _infer_doc_types(rule_identifier: str) -> list[str]:
    prefix = str(rule_identifier or "").split("-", 1)[0].upper()
    return list(_DOC_TYPES_BY_PREFIX.get(prefix, ["*"]))


def _stable_code_number(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 900) + 100


def _build_generated_catalog_code(category: RuleCategory, seed: str) -> str:
    candidate = f"{category.value}-{_stable_code_number(seed):03d}"
    while candidate in RULE_CATALOG and seed not in RULE_CATALOG[candidate].legacy_rule_codes:
        seed = f"{seed}:next"
        candidate = f"{category.value}-{_stable_code_number(seed):03d}"
    return candidate


def _infer_blocking(category: RuleCategory, severity: str) -> bool:
    if severity == "critical":
        return True
    if severity == "high" and category in {
        RuleCategory.COMPLETENESS,
        RuleCategory.FINANCIAL_ARITHMETIC,
        RuleCategory.COMPLIANCE,
        RuleCategory.DUPLICATE_DETECTION,
        RuleCategory.WORKFLOW_CONTROL,
    }:
        return True
    return False


def resolve_rule_catalog_metadata(
    rule_identifier: str,
    *,
    rule_name: str = "",
    rule_type: str = "",
    severity="medium",
    supported_doc_types: list[str] | None = None,
) -> RuleCatalogEntry:
    identifier = str(rule_identifier or "").strip()
    if not identifier:
        raise ValueError("rule_identifier is required")

    resolved_code = LEGACY_RULE_CODE_MAP.get(identifier, identifier)
    if resolved_code in RULE_CATALOG:
        return RULE_CATALOG[resolved_code]

    category = _infer_category(identifier, rule_name=rule_name, rule_type=rule_type)
    normalized_severity = _normalize_severity(severity)
    catalog_code = _build_generated_catalog_code(category, identifier)
    entry = RuleCatalogEntry(
        rule_code=catalog_code,
        category=category,
        severity=normalized_severity,
        is_blocking=_infer_blocking(category, normalized_severity),
        description_ar=rule_name or f"قاعدة متوافقة للمُعرّف {identifier}",
        description_en=rule_name or f"Compatibility catalog entry for rule {identifier}",
        supported_doc_types=list(supported_doc_types or _infer_doc_types(identifier)),
        failure_message_ar="فشلت هذه القاعدة وتحتاج إلى مراجعة المستخدم أو فريق التدقيق.",
        failure_message_en="This rule failed and requires user or audit-team review.",
        recommended_action_ar="راجع البيانات المرتبطة بهذه القاعدة وأعد التنفيذ بعد التصحيح.",
        recommended_action_en="Review the data used by this rule and re-run after correction.",
        legacy_rule_codes=[identifier],
    )
    return _register(entry)


def get_rules_for_doc_type(doc_type: str) -> list[RuleCatalogEntry]:
    return [
        rule
        for rule in RULE_CATALOG.values()
        if doc_type in rule.supported_doc_types or "*" in rule.supported_doc_types
    ]


def get_blocking_rules(doc_type: str) -> list[RuleCatalogEntry]:
    return [rule for rule in get_rules_for_doc_type(doc_type) if rule.is_blocking]


def get_rules_by_category(category: RuleCategory) -> list[RuleCatalogEntry]:
    return [rule for rule in RULE_CATALOG.values() if rule.category == category]