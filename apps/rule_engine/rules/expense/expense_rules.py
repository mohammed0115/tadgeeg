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


# ─── Extended Expense Rules ───────────────────────────────────────────────────

class DuplicateExpenseClaimRule(AuditRuleBase):
    """EXP-M03 — Detects duplicate expense claims within the same or across reports."""
    rule_code = "EXP-M03"
    rule_name_en = "Duplicate Expense Claim Detected"
    rule_name_ar = "مطالبة مصروف مكررة"
    default_severity = "high"
    rule_type = "anomaly"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        duplicate_claims = doc.get("duplicate_claims") or []

        if duplicate_claims:
            return self._fail(
                f"{len(duplicate_claims)} duplicate expense claim(s) detected.",
                f"تم اكتشاف {len(duplicate_claims)} مطالبة مصروف مكررة.",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="duplicate_claims",
                    field_name_ar="المطالبات المكررة",
                    expected_value="No duplicates",
                    actual_value=duplicate_claims[:5],
                    description=f"{len(duplicate_claims)} duplicate expense claims.",
                    description_ar=f"{len(duplicate_claims)} مطالبة مكررة.",
                )]
            )

        # Live check within lines
        lines = doc.get("expense_lines") or []
        seen = {}
        duplicates = []
        for line in lines:
            key = (
                str(line.get("date", "")),
                str(line.get("category", "")).lower(),
                str(line.get("amount", "")),
            )
            if key in seen:
                duplicates.append(key)
            else:
                seen[key] = True

        if duplicates:
            return self._fail(
                f"{len(duplicates)} expense line(s) appear to be duplicated "
                "(same date, category, and amount).",
                f"{len(duplicates)} بند مصروف يبدو مكرراً "
                "(نفس التاريخ والفئة والمبلغ).",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="expense_lines",
                    field_name_ar="بنود المصروفات",
                    expected_value="All unique lines",
                    actual_value=str(duplicates[:3]),
                    description=f"Duplicate expense lines detected: {duplicates[:3]}",
                    description_ar=f"بنود مصروفات مكررة: {duplicates[:3]}",
                )]
            )
        return self._pass(
            "No duplicate expense claims detected.",
            "لم يتم اكتشاف أي مطالبات مصروف مكررة.",
        )


class ExpenseSubmissionDeadlineRule(AuditRuleBase):
    """EXP-M04 — Expense reports must be submitted within policy deadline."""
    rule_code = "EXP-M04"
    rule_name_en = "Expense Report Submitted Late"
    rule_name_ar = "تأخر في تقديم تقرير المصروفات"
    default_severity = "medium"
    rule_type = "compliance"

    WARN_DAYS = 30
    FAIL_DAYS = 90

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.get("submitted_date") is not None and
                doc.get("report_period_to") is not None)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        from datetime import datetime, date as date_type
        warn_days = int(self.get_config("warn_days", self.WARN_DAYS))
        fail_days = int(self.get_config("fail_days", self.FAIL_DAYS))

        try:
            submitted_raw = doc.get("submitted_date")
            period_to_raw = doc.get("report_period_to")
            submitted = submitted_raw if isinstance(submitted_raw, date_type) else datetime.fromisoformat(str(submitted_raw)).date()
            period_to = period_to_raw if isinstance(period_to_raw, date_type) else datetime.fromisoformat(str(period_to_raw)).date()
        except (ValueError, TypeError):
            return self._skipped("Cannot parse submission or period dates.")

        delay_days = (submitted - period_to).days

        if delay_days <= 0:
            return self._pass(
                f"Expense report submitted on time (period ended {period_to}, submitted {submitted}).",
                f"تقرير المصروفات مُقدَّم في الوقت المحدد (انتهت الفترة {period_to}، تاريخ التقديم {submitted}).",
            )

        evidence = [EvidenceItem(
            evidence_type="comparison",
            field_name="submitted_date",
            field_name_ar="تاريخ التقديم",
            expected_value=f"Within {warn_days} days of period end",
            actual_value=f"{delay_days} days late",
            description=f"Submitted {delay_days} days after period end.",
            description_ar=f"قُدِّم بعد {delay_days} يوماً من انتهاء الفترة.",
        )]

        if delay_days > fail_days:
            return self._fail(
                f"Expense report is {delay_days} days overdue (critical threshold: {fail_days} days).",
                f"تأخر تقديم تقرير المصروفات {delay_days} يوماً (الحد الحرج: {fail_days} يوماً).",
                evidence=evidence,
            )
        if delay_days > warn_days:
            return self._warning(
                f"Expense report is {delay_days} days late (warning threshold: {warn_days} days).",
                f"تقرير المصروفات متأخر {delay_days} يوماً (حد التحذير: {warn_days} يوماً).",
                evidence=evidence,
            )
        return self._pass(
            f"Expense report submitted within acceptable timeframe ({delay_days} days).",
            f"تقرير المصروفات مُقدَّم ضمن الإطار الزمني المقبول ({delay_days} يوماً).",
        )


class SplitTransactionRule(AuditRuleBase):
    """EXP-M05 — Detects split expense claims used to circumvent policy limits."""
    rule_code = "EXP-M05"
    rule_name_en = "Expense Split Transaction Detected"
    rule_name_ar = "اكتشاف تجزئة في مصروف"
    default_severity = "high"
    rule_type = "anomaly"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return True

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        split_flags = doc.get("split_transaction_flags") or []

        if split_flags:
            return self._warning(
                f"{len(split_flags)} potential split transaction(s) detected. "
                "Splitting expenses avoids policy limits.",
                f"تم اكتشاف {len(split_flags)} احتمال تجزئة مصروف. "
                "تجزئة المصروفات تُستخدم للتحايل على الحدود السياساتية.",
                evidence=[EvidenceItem(
                    evidence_type="statistical",
                    field_name="split_transaction_flags",
                    field_name_ar="مؤشرات التجزئة",
                    expected_value="No split flags",
                    actual_value=split_flags[:5],
                    description=f"{len(split_flags)} split transaction flags set.",
                    description_ar=f"{len(split_flags)} مؤشر تجزئة مُعيَّن.",
                )]
            )

        # Heuristic: multiple lines on same date + same category, each just below limit
        limits = ExpensePolicyLimitRule.DEFAULT_LIMITS
        lines = doc.get("expense_lines") or []
        from collections import defaultdict
        grouped = defaultdict(list)
        for line in lines:
            key = (str(line.get("date", "")), str(line.get("category", "other")).lower())
            grouped[key].append(float(line.get("amount", 0) or 0))

        suspicious = []
        for (dt, cat), amounts in grouped.items():
            if len(amounts) > 1:
                limit = float(limits.get(cat, limits["other"]))
                combined = sum(amounts)
                if combined > limit and all(a < limit for a in amounts):
                    suspicious.append(f"{dt}/{cat}: {amounts} (combined {combined:.0f} > limit {limit:.0f})")

        if suspicious:
            return self._warning(
                f"Potential split-to-avoid-limit: {len(suspicious)} group(s) of same-day/"
                "same-category expenses that individually pass limits but collectively exceed them.",
                f"احتمال تجزئة للتهرب من الحد: {len(suspicious)} مجموعة مصروفات "
                "تجتاز الحد بشكل منفرد لكن تتجاوزه مجتمعةً.",
                evidence=[EvidenceItem(
                    evidence_type="statistical",
                    field_name="expense_lines",
                    field_name_ar="بنود المصروفات",
                    expected_value="No combined limit breach",
                    actual_value=suspicious[:3],
                    description="Expenses grouped by date+category exceed policy limits.",
                    description_ar="مصروفات مجمَّعة بالتاريخ والفئة تتجاوز الحدود السياساتية.",
                )]
            )
        return self._pass(
            "No split transaction patterns detected.",
            "لم يتم اكتشاف أنماط تجزئة مصروفات.",
        )
