"""EXP-M01, EXP-M02, EXP-M07, EXP-M09: Expense audit rules"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class MissingReceiptRule(AuditRuleBase):
    rule_code = "EXP-M01"
    rule_name_en = "Missing Receipt for Expense Line"
    rule_name_ar = "فاتورة إثبات مفقودة لبند مصروف"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        lines = doc.get("expense_lines", [])
        return isinstance(lines, list) and len(lines) > 0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        lines = doc.get("expense_lines", [])
        missing = [
            line for line in lines
            if not line.get("receipt_attached", False) and float(line.get("amount", 0) or 0) > 0
        ]

        # Also use pre-computed count
        missing_count = doc.get("missing_receipts_count", 0) or len(missing)

        if missing_count > 0:
            return self._fail(
                f"{missing_count} expense line(s) have no attached receipt.",
                f"{missing_count} بند مصروف بدون فاتورة إثبات مرفقة.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="receipt_attached",
                    field_name_ar="الفاتورة المرفقة",
                    expected_value=True,
                    actual_value=f"{missing_count} lines missing receipt",
                    description=f"{missing_count} expense line(s) lack receipts.",
                    description_ar=f"{missing_count} بند مصروف بدون إيصال.",
                )]
            )
        return self._pass(
            "All expense lines have attached receipts.",
            "جميع بنود المصروفات لديها فواتير إثبات مرفقة.",
        )


class ExpensePolicyLimitRule(AuditRuleBase):
    rule_code = "EXP-M02"
    rule_name_en = "Expense Exceeds Policy Limit"
    rule_name_ar = "مصروف يتجاوز الحد السياساتي"
    default_severity = "high"
    rule_type = "compliance"

    DEFAULT_LIMITS = {
        "meals": 150,
        "travel": 2000,
        "accommodation": 500,
        "entertainment": 500,
        "other": 1000,
    }

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("over_policy_limit_count", 0) is not None or bool(doc.get("expense_lines"))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        over_count = doc.get("over_policy_limit_count", 0) or 0

        if over_count > 0:
            return self._fail(
                f"{over_count} expense line(s) exceed the policy limit for their category.",
                f"{over_count} بند مصروف يتجاوز الحد السياساتي لفئته.",
                evidence=[EvidenceItem(
                    evidence_type="reference",
                    field_name="expense_category",
                    field_name_ar="فئة المصروف",
                    expected_value="Within policy limits",
                    actual_value=f"{over_count} lines over limit",
                    description=f"{over_count} expense lines exceed category limits.",
                    description_ar=f"{over_count} بند يتجاوز الحدود السياساتية.",
                )]
            )

        # Check lines directly if no pre-computed count
        limits = self.get_config("policy_limits", self.DEFAULT_LIMITS)
        lines = doc.get("expense_lines", [])
        violations = []

        for line in lines:
            cat = str(line.get("category", "other")).lower()
            amount = float(line.get("amount", 0) or 0)
            limit = float(limits.get(cat, limits["other"]))
            if amount > limit:
                violations.append(f"{cat}: {amount:.2f} > {limit:.2f}")

        if violations:
            return self._fail(
                f"Policy limit exceeded: {'; '.join(violations[:3])}",
                f"تجاوز الحد السياساتي: {'; '.join(violations[:3])}",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="expense_amount",
                    field_name_ar="مبلغ المصروف",
                    expected_value="Within limits",
                    actual_value=violations[:5],
                    description="One or more expense lines exceed policy limits.",
                    description_ar="بنود مصروفات تتجاوز الحدود السياساتية.",
                )]
            )

        return self._pass(
            "All expense lines are within policy limits.",
            "جميع بنود المصروفات ضمن الحدود السياساتية.",
        )


class SelfApprovalRule(AuditRuleBase):
    rule_code = "EXP-M07"
    rule_name_en = "Manager Self-Approval Risk"
    rule_name_ar = "مخاطر الموافقة على مصروف النفس"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.get("employee_id")) and bool(doc.approved_by_id)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        submitter = str(doc.get("employee_id", ""))
        approver = str(doc.approved_by_id or "")

        if submitter and approver and submitter == approver:
            return self._fail(
                "Expense report submitter and approver are the same person — segregation of duties violation.",
                "مقدّم تقرير المصروفات والموافق عليه هو نفس الشخص — مخالفة لمبدأ الفصل بين الصلاحيات.",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="approved_by",
                    field_name_ar="الموافق",
                    expected_value="Different from submitter",
                    actual_value=f"Same person: {approver}",
                    description="Submitter ID matches approver ID.",
                    description_ar="معرّف مقدم التقرير يطابق معرّف الموافق.",
                )]
            )
        return self._pass(
            "Submitter and approver are different persons — segregation of duties maintained.",
            "مقدّم التقرير والموافق أشخاص مختلفون — مبدأ الفصل بين الصلاحيات محقق.",
        )


class ExpenseTotalMatchRule(AuditRuleBase):
    rule_code = "EXP-M09"
    rule_name_en = "Expense Total Does Not Match Line Items"
    rule_name_ar = "الإجمالي المطالب به لا يطابق مجموع البنود"
    default_severity = "critical"
    rule_type = "validation"

    TOLERANCE = Decimal("0.01")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        lines = doc.get("expense_lines", [])
        return isinstance(lines, list) and len(lines) > 0 and doc.get("total_claimed") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        lines = doc.get("expense_lines", [])
        total_claimed = self.safe_decimal(doc.get("total_claimed"))
        calculated = sum(self.safe_decimal(line.get("amount", 0)) for line in lines)
        discrepancy = abs(calculated - total_claimed)

        evidence = [EvidenceItem(
            evidence_type="calculation",
            field_name="total_claimed",
            field_name_ar="المبلغ الإجمالي المطالب",
            expected_value=float(calculated),
            actual_value=float(total_claimed),
            description=f"Sum of line items: {calculated}, declared total: {total_claimed}",
            description_ar=f"مجموع البنود: {calculated}، الإجمالي المُعلن: {total_claimed}",
        )]

        if discrepancy > self.TOLERANCE:
            return self._fail(
                f"Expense total mismatch: line items sum to {calculated} but claimed total is {total_claimed}.",
                f"تعارض في إجمالي المصروفات: مجموع البنود {calculated} لكن الإجمالي المطالب {total_claimed}.",
                evidence=evidence,
            )
        return self._pass(
            "Expense total matches line item sum.",
            "الإجمالي المطالب يطابق مجموع البنود.",
        )
