"""BNK-M01: Balance Reconciliation — opening + credits - debits = closing"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class BalanceReconciliationRule(AuditRuleBase):
    rule_code = "BNK-M01"
    rule_name_en = "Balance Reconciliation"
    rule_name_ar = "مطابقة الرصيد البنكي"
    default_severity = "critical"
    rule_type = "reconciliation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        required = ["opening_balance", "closing_balance", "total_credits", "total_debits"]
        return all(doc.get(k) is not None for k in required)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        tolerance = self.safe_decimal(self.get_config("tolerance", "0.01"))
        opening = self.safe_decimal(doc.get("opening_balance"))
        credits = self.safe_decimal(doc.get("total_credits"))
        debits = self.safe_decimal(doc.get("total_debits"))
        closing = self.safe_decimal(doc.get("closing_balance"))

        calculated_closing = opening + credits - debits
        discrepancy = abs(calculated_closing - closing)

        evidence = [EvidenceItem(
            evidence_type="calculation",
            field_name="closing_balance",
            field_name_ar="الرصيد الختامي",
            expected_value=float(calculated_closing),
            actual_value=float(closing),
            description=f"Opening({opening}) + Credits({credits}) - Debits({debits}) = {calculated_closing}, statement shows {closing}",
            description_ar=f"الافتتاحي({opening}) + الإيداعات({credits}) - السحوبات({debits}) = {calculated_closing}، الكشف يُظهر {closing}",
        )]

        if discrepancy > tolerance:
            return self._fail(
                f"Bank balance does not reconcile. Discrepancy: {discrepancy} {doc.currency or 'SAR'}.",
                f"الرصيد البنكي لا يتطابق. الفارق: {discrepancy} {doc.currency or 'ريال'}.",
                evidence=evidence,
            )
        return self._pass(
            "Bank balance reconciles correctly.",
            "الرصيد البنكي يتطابق بشكل صحيح.",
        )


class DuplicateTransactionRule(AuditRuleBase):
    rule_code = "BNK-M06"
    rule_name_en = "Duplicate Bank Transactions"
    rule_name_ar = "معاملات بنكية مكررة"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        transactions = doc.get("transactions", [])
        return isinstance(transactions, list) and len(transactions) > 1

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        transactions = doc.get("transactions", [])
        seen = {}
        duplicates = []

        for tx in transactions:
            key = (
                str(tx.get("amount", "")),
                str(tx.get("date", "")),
                str(tx.get("description", ""))[:50],
            )
            if key in seen:
                duplicates.append(key)
            else:
                seen[key] = True

        if duplicates:
            return self._fail(
                f"Found {len(duplicates)} duplicate transaction(s) (same amount, date, description).",
                f"وُجد {len(duplicates)} معاملة مكررة (نفس المبلغ والتاريخ والوصف).",
                evidence=[EvidenceItem(
                    evidence_type="comparison",
                    field_name="transactions",
                    field_name_ar="المعاملات",
                    expected_value="All transactions unique",
                    actual_value=f"{len(duplicates)} duplicates",
                    description=f"Duplicate transactions detected: {duplicates[:3]}",
                    description_ar=f"معاملات مكررة: {duplicates[:3]}",
                )]
            )

        # Also check pre-computed flag
        dup_count = doc.get("duplicate_tx_count", 0) or 0
        if dup_count > 0:
            return self._fail(
                f"System detected {dup_count} duplicate transaction(s).",
                f"النظام اكتشف {dup_count} معاملة مكررة.",
            )

        return self._pass(
            "No duplicate transactions detected.",
            "لا توجد معاملات مكررة.",
        )


class IBANFormatRule(AuditRuleBase):
    rule_code = "BNK-M08"
    rule_name_en = "IBAN Format Invalid"
    rule_name_ar = "صيغة IBAN غير صحيحة"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return bool(doc.get("iban"))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        iban = str(doc.get("iban", "")).strip().replace(" ", "")

        # SA IBAN: SA + 2 check digits + 18 alphanumeric = 22 chars total
        is_valid = (
            len(iban) == 24 and
            iban[:2].upper() == "SA" and
            iban[2:4].isdigit() and
            iban[4:].isalnum()
        )

        if not is_valid:
            return self._fail(
                f"IBAN '{iban}' does not match Saudi IBAN format (SA + 22 characters).",
                f"رقم IBAN '{iban}' لا يتوافق مع صيغة الآيبان السعودي (SA + 22 حرفًا).",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="iban",
                    field_name_ar="رقم IBAN",
                    expected_value="SA followed by 22 alphanumeric chars (24 total)",
                    actual_value=iban,
                    description=f"IBAN format validation failed. Length: {len(iban)}",
                    description_ar=f"فشل التحقق من صيغة IBAN. الطول: {len(iban)}",
                )]
            )
        return self._pass(f"IBAN '{iban}' format is valid.", f"صيغة IBAN '{iban}' صحيحة.")


class StructuringDetectionRule(AuditRuleBase):
    rule_code = "BNK-M07"
    rule_name_en = "Structuring Detection (AML)"
    rule_name_ar = "اكتشاف التجزئة المتعمدة (غسيل أموال)"
    default_severity = "critical"
    rule_type = "compliance"

    # SA AML reporting threshold: SAR 60,000
    THRESHOLD = 60000
    STRUCTURING_WINDOW = 0.9  # 90% of threshold

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return isinstance(doc.get("transactions", []), list)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        threshold = float(self.get_config("structuring_threshold", self.THRESHOLD))
        window = float(self.get_config("structuring_window", self.STRUCTURING_WINDOW))
        lower = threshold * window

        transactions = doc.get("transactions", [])
        suspicious = [
            tx for tx in transactions
            if lower <= float(tx.get("amount", 0) or 0) < threshold
        ]

        if len(suspicious) >= 3:
            amounts = [float(tx.get("amount", 0)) for tx in suspicious[:5]]
            return self._fail(
                f"Structuring detected: {len(suspicious)} transactions between {lower:,.0f}–{threshold:,.0f} {doc.currency or 'SAR'} (just below AML threshold).",
                f"تم اكتشاف تجزئة متعمدة: {len(suspicious)} معاملة بين {lower:,.0f}–{threshold:,.0f} {doc.currency or 'ريال'} (أقل من حد الإبلاغ لمكافحة غسيل الأموال).",
                evidence=[EvidenceItem(
                    evidence_type="statistical",
                    field_name="transactions",
                    field_name_ar="المعاملات",
                    expected_value=f"< 3 transactions near {threshold:,.0f} threshold",
                    actual_value=f"{len(suspicious)} transactions: {amounts}",
                    description=f"{len(suspicious)} transactions clustered just below AML threshold {threshold:,.0f}.",
                    description_ar=f"{len(suspicious)} معاملة مجمّعة أسفل حد الإبلاغ {threshold:,.0f}.",
                )]
            )

        return self._pass(
            "No structuring patterns detected.",
            "لا توجد أنماط تجزئة متعمدة.",
        )
