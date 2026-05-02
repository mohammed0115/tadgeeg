"""
Document quality / authenticity rules: DOC-001 (low OCR confidence),
DOC-002 (handwritten / poor scan), DOC-003 (alterations detected).

These rules answer "is this document trustworthy as evidence?" before the
financial rules even run.
"""
from __future__ import annotations

import logging

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem,
)

logger = logging.getLogger("rule_engine")


class LowOCRConfidenceRule(AuditRuleBase):
    """DOC-001: OCR confidence is below the threshold (<70% by default).

    Low confidence usually means downstream extraction is unreliable, so this
    rule warns the auditor to manually verify the document before approving.
    """

    rule_code = "DOC-001"
    rule_name_en = "Low OCR Confidence"
    rule_name_ar = "ثقة منخفضة في التعرّف الضوئي"
    default_severity = "medium"
    rule_type = "validation"

    DEFAULT_THRESHOLD = 70.0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        threshold = float(self.get_config("threshold", self.DEFAULT_THRESHOLD))
        confidence = doc.ocr_confidence
        if confidence is None:
            return self._pass("OCR confidence not recorded.")
        if confidence < threshold:
            return self._fail(
                f"OCR confidence {confidence:.0f}% is below the {threshold:.0f}% threshold.",
                f"ثقة التعرّف الضوئي {confidence:.0f}% أقل من الحد المطلوب {threshold:.0f}%.",
                evidence=[EvidenceItem(
                    field_path="ocr_confidence",
                    observed=f"{confidence:.0f}%",
                    expected=f">= {threshold:.0f}%",
                )],
            )
        return self._pass(f"OCR confidence {confidence:.0f}% is acceptable.")


class HandwrittenDocumentRule(AuditRuleBase):
    """DOC-002: Document appears handwritten or has poor visual quality.

    Vision models flag this; we simply surface it as a soft warning so
    handwritten receipts (common for petty cash) get extra scrutiny.
    """

    rule_code = "DOC-002"
    rule_name_en = "Handwritten or Low-Quality Scan"
    rule_name_ar = "مستند بخط اليد أو مسح منخفض الجودة"
    default_severity = "low"
    rule_type = "validation"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        is_handwritten = bool(getattr(doc, "is_handwritten", False))
        is_clear = bool(getattr(doc, "is_clear", True))
        if is_handwritten:
            return self._fail(
                "Document is handwritten and may need manual verification.",
                "المستند بخط اليد ويحتاج إلى تحقق يدوي.",
                evidence=[EvidenceItem(field_path="is_handwritten", observed="true", expected="false")],
            )
        if not is_clear:
            return self._fail(
                "Scan quality is poor — recommend re-uploading a clearer copy.",
                "جودة المسح ضعيفة — يُنصح بإعادة رفع نسخة أوضح.",
                evidence=[EvidenceItem(field_path="is_clear", observed="false", expected="true")],
            )
        return self._pass("Document quality is acceptable.")


class DocumentAlterationRule(AuditRuleBase):
    """DOC-003: Alterations / tampering detected (whitening, ink mismatch, overwriting).

    The vision pipeline sets the `has_alterations` flag when the AI sees suspicious
    edits. Critical because tampered documents are a fraud red flag.
    """

    rule_code = "DOC-003"
    rule_name_en = "Document Alterations Detected"
    rule_name_ar = "اشتباه في تعديل المستند"
    default_severity = "critical"
    rule_type = "anomaly"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        has_alterations = bool(getattr(doc, "has_alterations", False))
        if has_alterations:
            return self._fail(
                "Possible alteration detected — escalate to senior auditor.",
                "اشتباه في تعديل المستند — يجب تصعيده للمدقق الرئيسي.",
                evidence=[EvidenceItem(
                    field_path="has_alterations",
                    observed="true",
                    expected="false",
                )],
            )
        return self._pass("No alterations detected.")
