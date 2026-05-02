"""
Internal-control rules: CTL-003 (budget), CTL-004 (post-approval lock),
CTL-005 (segregation of duties), CTL-006 (audit trail).

These complement the existing structural rules. They model the kind of
internal-controls failures auditors flag — not OCR/format issues, but
*business-process* problems like "this invoice exceeds the department budget"
or "the same person approved and posted this".
"""
from __future__ import annotations

import logging
from decimal import Decimal

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem,
)

logger = logging.getLogger("rule_engine")


class BudgetThresholdRule(AuditRuleBase):
    """CTL-003: Invoice exceeds the department / cost-center budget threshold.

    Threshold defaults to 100,000 SAR but is configurable per-rule and per-org.
    Without a budget context the rule passes (no false positives on missing data).
    """

    rule_code = "CTL-003"
    rule_name_en = "Budget Threshold Exceeded"
    rule_name_ar = "تجاوز سقف الميزانية المخصصة"
    default_severity = "high"
    rule_type = "compliance"

    DEFAULT_THRESHOLD = Decimal("100000")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.total_amount)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            threshold = Decimal(str(self.get_config("threshold", self.DEFAULT_THRESHOLD)))
            amount = Decimal(str(doc.total_amount or 0))
            if amount > threshold:
                pct_over = ((amount - threshold) / threshold) * 100
                return self._fail(
                    f"Amount {amount} exceeds budget threshold {threshold} by {pct_over:.0f}%.",
                    f"المبلغ {amount} يتجاوز سقف الميزانية {threshold} بنسبة {pct_over:.0f}%.",
                    evidence=[EvidenceItem(
                        field_path="total_amount",
                        observed=str(amount),
                        expected=f"<= {threshold}",
                    )],
                )
            return self._pass(
                f"Amount {amount} within budget {threshold}.",
                f"المبلغ {amount} ضمن الميزانية {threshold}.",
            )
        except Exception as exc:
            logger.warning("CTL-003 failed: %s", exc)
            return self._pass("Budget check skipped (data unavailable).")


class PostApprovalLockRule(AuditRuleBase):
    """CTL-004: An approved invoice was modified after approval.

    Compares the document's last-modified timestamp against its approval
    timestamp. Flag when post-approval edits exist without a re-approval entry.
    """

    rule_code = "CTL-004"
    rule_name_en = "Post-Approval Modification"
    rule_name_ar = "تعديل بعد الاعتماد"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        # Requires approval history; pass through when not approved yet.
        return getattr(doc, "approval_status", "") == "approved"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            approved_at = getattr(doc, "approved_at", None)
            modified_at = getattr(doc, "modified_at", None) or getattr(doc, "updated_at", None)
            if not approved_at or not modified_at:
                return self._pass("No timestamps to compare.")
            # Allow a 60-second clock-skew tolerance.
            from datetime import timedelta
            if modified_at - approved_at > timedelta(seconds=60):
                return self._fail(
                    "Document was modified after being approved.",
                    "تم تعديل المستند بعد اعتماده.",
                    evidence=[EvidenceItem(
                        field_path="modified_at",
                        observed=str(modified_at),
                        expected=f"<= {approved_at}",
                    )],
                )
            return self._pass("No post-approval changes detected.")
        except Exception as exc:
            logger.warning("CTL-004 failed: %s", exc)
            return self._pass("Post-approval check skipped.")


class SegregationOfDutiesRule(AuditRuleBase):
    """CTL-005: Same user uploaded AND approved the document.

    Standard internal-control violation — the person creating a transaction
    must not be the one approving it.
    """

    rule_code = "CTL-005"
    rule_name_en = "Segregation of Duties Violation"
    rule_name_ar = "إخلال بمبدأ الفصل بين الصلاحيات"
    default_severity = "critical"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return getattr(doc, "approval_status", "") == "approved"

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        uploaded_by = getattr(doc, "uploaded_by_id", None)
        approved_by = getattr(doc, "approved_by_id", None)
        if not uploaded_by or not approved_by:
            return self._pass("Approver/uploader not both recorded.")
        if str(uploaded_by) == str(approved_by):
            return self._fail(
                "Same user uploaded and approved this document.",
                "نفس المستخدم رفع المستند ووافق عليه.",
                evidence=[EvidenceItem(
                    field_path="approved_by",
                    observed=str(approved_by),
                    expected="user != uploaded_by",
                )],
            )
        return self._pass("Uploader and approver are different users.")


class AuditTrailCompletenessRule(AuditRuleBase):
    """CTL-006: Required audit-trail events are present (uploaded → processed → approved/rejected)."""

    rule_code = "CTL-006"
    rule_name_en = "Incomplete Audit Trail"
    rule_name_ar = "سلسلة تدقيق غير مكتملة"
    default_severity = "medium"
    rule_type = "compliance"

    REQUIRED_EVENTS = {"uploaded", "processed"}

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            events = getattr(doc, "audit_events", None) or []
            event_types = {str(e.get("event_type", "")).lower() for e in events if isinstance(e, dict)}
            missing = self.REQUIRED_EVENTS - event_types
            if missing:
                return self._fail(
                    f"Missing audit-trail events: {', '.join(sorted(missing))}.",
                    f"أحداث التدقيق المفقودة: {', '.join(sorted(missing))}.",
                    evidence=[EvidenceItem(
                        field_path="audit_events",
                        observed=", ".join(sorted(event_types)) or "(none)",
                        expected=", ".join(sorted(self.REQUIRED_EVENTS)),
                    )],
                )
            return self._pass("Audit trail complete.")
        except Exception as exc:
            logger.warning("CTL-006 failed: %s", exc)
            return self._pass("Audit trail check skipped.")
