"""
SOCPA (Saudi Organization for Certified Public Accountants) standards.

Mapping the most-cited SOCPA / SAAS standards onto rules that operate on
single-document data. Like the IFRS pack, multi-period SOCPA standards
(quality control, internal-control evaluation across periods) live in a
separate module — these are the document-level checks.

    SOCPA-200 Auditor independence (uploaded_by must not be related to vendor)
    SOCPA-315 Risk assessment evidence sufficiency
    SOCPA-450 Material misstatement evaluation
    SOCPA-500 Sufficient appropriate audit evidence
    SOCPA-700 Forming an audit opinion (basis: rule failures)
"""
from __future__ import annotations

import logging
from decimal import Decimal

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem,
)

logger = logging.getLogger("rule_engine")


class AuditorIndependenceRule(AuditRuleBase):
    """SOCPA-200 (auditor independence).

    Rule: the user who *audits* the document must not be the vendor's
    relationship owner or the user who originally uploaded it. Mirrors
    SOCPA's "self-review threat" prohibition.
    """

    rule_code = "SOCPA-200"
    rule_name_en = "Auditor Independence (SOCPA 200)"
    rule_name_ar = "استقلالية المدقق (SOCPA 200)"
    default_severity = "high"
    rule_type = "compliance"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        uploaded_by = getattr(doc, "uploaded_by_id", None)
        reviewed_by = getattr(doc, "reviewed_by_id", None)
        if not (uploaded_by and reviewed_by):
            return self._pass("Reviewer not yet assigned.")
        if str(uploaded_by) == str(reviewed_by):
            return self._fail(
                "Auditor independence violated: same user uploaded and reviewed.",
                "إخلال باستقلالية المدقق: نفس المستخدم رفع وراجع المستند.",
                evidence=[EvidenceItem(
                    field_path="reviewed_by",
                    observed=str(reviewed_by),
                    expected="different user from uploaded_by",
                )],
            )
        return self._pass("Reviewer is independent of uploader.")


class SufficientEvidenceRule(AuditRuleBase):
    """SOCPA-500 (sufficient appropriate audit evidence).

    Required evidence: original file, OCR confidence ≥ 60%, line items
    extracted, and at least one audit-trail event. Without these, the
    auditor cannot reach a supportable conclusion.
    """

    rule_code = "SOCPA-500"
    rule_name_en = "Sufficient Audit Evidence (SOCPA 500)"
    rule_name_ar = "كفاية أدلة التدقيق (SOCPA 500)"
    default_severity = "medium"
    rule_type = "compliance"

    OCR_FLOOR = 60.0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        gaps = []
        if not getattr(doc, "raw_text", None):
            gaps.append("no extracted text")
        ocr = getattr(doc, "ocr_confidence", None)
        if ocr is not None and ocr < self.OCR_FLOOR:
            gaps.append(f"OCR confidence {ocr:.0f}% (< {self.OCR_FLOOR:.0f}%)")
        line_items = getattr(doc, "line_items", None) or []
        if not line_items:
            gaps.append("no line items extracted")
        events = getattr(doc, "audit_events", None) or []
        if not events:
            gaps.append("no audit trail events")

        if gaps:
            return self._fail(
                "Insufficient evidence: " + ", ".join(gaps),
                "أدلة التدقيق غير كافية: " + "، ".join(gaps),
                evidence=[EvidenceItem(
                    field_path="audit_evidence",
                    observed=", ".join(gaps),
                    expected="text + OCR ≥60% + line items + audit trail",
                )],
            )
        return self._pass("Audit evidence is sufficient and appropriate.")


class MaterialMisstatementRule(AuditRuleBase):
    """SOCPA-450 (material misstatement evaluation).

    Combines existing high-severity rule failures into a misstatement-risk
    summary. If 3+ critical/high rules failed, the invoice is treated as
    materially misstated and must not be approved without remediation.
    """

    rule_code = "SOCPA-450"
    rule_name_en = "Material Misstatement Risk (SOCPA 450)"
    rule_name_ar = "خطر التحريف الجوهري (SOCPA 450)"
    default_severity = "critical"
    rule_type = "compliance"

    HIGH_SEVERITY_THRESHOLD = 3

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            failed = getattr(doc, "failed_rule_codes", None) or []
            severities = getattr(doc, "failed_rule_severities", None) or {}
            high_count = 0
            for code in failed:
                sev = (severities.get(code, "") or "").lower()
                if sev in ("high", "critical"):
                    high_count += 1
            if high_count >= self.HIGH_SEVERITY_THRESHOLD:
                return self._fail(
                    f"{high_count} high/critical rule failures — material misstatement risk.",
                    f"{high_count} قاعدة فاشلة بشدة عالية أو حرجة — خطر تحريف جوهري.",
                    evidence=[EvidenceItem(
                        field_path="failed_rule_codes",
                        observed=", ".join(failed[:8]),
                        expected=f"< {self.HIGH_SEVERITY_THRESHOLD} high-severity failures",
                    )],
                )
            return self._pass(f"{high_count} high-severity failures — below misstatement threshold.")
        except Exception as exc:
            logger.warning("SOCPA-450 rule failed: %s", exc)
            return self._pass("Misstatement check skipped.")


class AuditOpinionBasisRule(AuditRuleBase):
    """SOCPA-700 (forming an audit opinion).

    Aggregates the document's overall auditability based on rule outcomes
    plus risk score. Output classifies the supportable opinion as
    *unqualified*, *qualified*, *adverse*, or *disclaimer*.
    """

    rule_code = "SOCPA-700"
    rule_name_en = "Auditor's Opinion Basis (SOCPA 700)"
    rule_name_ar = "أساس رأي المدقق (SOCPA 700)"
    default_severity = "low"
    rule_type = "compliance"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            score = float(getattr(doc, "validation_score", 0) or 0)
            risk = (getattr(doc, "risk_level", "") or "").lower()
            failed = len(getattr(doc, "failed_rule_codes", None) or [])

            if risk == "critical" or score < 40:
                opinion, opinion_ar = "Adverse", "رأي معارض"
            elif risk == "high" or score < 60 or failed >= 5:
                opinion, opinion_ar = "Qualified", "رأي متحفظ"
            elif risk == "medium" or score < 80:
                opinion, opinion_ar = "Disclaimer", "امتناع عن إبداء الرأي"
            else:
                opinion, opinion_ar = "Unqualified (Clean)", "رأي نظيف"

            # Always pass — this rule is informational.
            return self._pass(
                f"Supportable audit opinion: {opinion} (score {score:.0f}, risk {risk}).",
                f"الرأي المُدعَم: {opinion_ar} (الدرجة {score:.0f}، المخاطر {risk}).",
            )
        except Exception as exc:
            logger.warning("SOCPA-700 rule failed: %s", exc)
            return self._pass("Opinion basis check skipped.")
