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


# ─── Extended Bank Statement Rules ───────────────────────────────────────────

class BenfordsLawBankRule(AuditRuleBase):
    """BNK-M02 — Benford's Law analysis on bank transaction amounts."""
    rule_code = "BNK-M02"
    rule_name_en = "Benford's Law Anomaly in Transactions"
    rule_name_ar = "شذوذ قانون بنفورد في المعاملات البنكية"
    default_severity = "high"
    rule_type = "anomaly"

    CRITICAL_MAD = 0.015
    WARNING_MAD  = 0.010

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.get("benford_deviation") is not None or
                len(doc.get("transactions") or []) >= 30)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        critical_mad = float(self.get_config("critical_mad", self.CRITICAL_MAD))
        warning_mad  = float(self.get_config("warning_mad",  self.WARNING_MAD))
        mad = doc.get("benford_deviation")

        if mad is None:
            try:
                import math
                from collections import Counter
                amounts = [abs(float(tx.get("amount", 0) or 0))
                           for tx in (doc.get("transactions") or [])
                           if tx.get("amount") not in (None, 0, "")]
                if len(amounts) < 30:
                    return self._skipped("Insufficient transactions for Benford's analysis.")
                expected = {str(d): math.log10(1 + 1/d) for d in range(1, 10)}
                first_digits = []
                for a in amounts:
                    s = str(a).replace(".", "").lstrip("0")
                    if s:
                        first_digits.append(s[0])
                counter = Counter(first_digits)
                total = len(first_digits)
                if not total:
                    return self._skipped("No valid amounts for Benford analysis.")
                observed = {d: counter.get(d, 0) / total for d in [str(i) for i in range(1, 10)]}
                mad = sum(abs(observed.get(d, 0) - expected[d]) for d in expected) / 9
            except Exception:
                return self._skipped("Error computing Benford distribution.")

        mad = float(mad)
        evidence = [EvidenceItem(
            evidence_type="statistical",
            field_name="benford_deviation",
            field_name_ar="انحراف بنفورد",
            expected_value=f"MAD < {warning_mad}",
            actual_value=f"MAD = {mad:.4f}",
            description=f"Benford MAD = {mad:.4f}",
            description_ar=f"انحراف بنفورد = {mad:.4f}",
        )]

        if mad >= critical_mad:
            return self._fail(
                f"Benford's Law: MAD {mad:.4f} ≥ critical {critical_mad}. Possible transaction fraud.",
                f"قانون بنفورد: MAD {mad:.4f} ≥ الحد الحرج {critical_mad}. احتمال احتيال في المعاملات.",
                evidence=evidence,
            )
        if mad >= warning_mad:
            return self._warning(
                f"Benford's Law: MAD {mad:.4f} exceeds warning threshold {warning_mad}.",
                f"قانون بنفورد: MAD {mad:.4f} يتجاوز حد التحذير {warning_mad}.",
                evidence=evidence,
            )
        return self._pass(
            f"Benford's Law: digit distribution is normal (MAD = {mad:.4f}).",
            f"قانون بنفورد: توزيع الأرقام طبيعي (MAD = {mad:.4f}).",
        )


class RoundAmountClusterRule(AuditRuleBase):
    """BNK-M03 — Flags accounts with unusually many round-number transactions."""
    rule_code = "BNK-M03"
    rule_name_en = "Unusual Round-Amount Transaction Cluster"
    rule_name_ar = "تجمّع غير معتاد من المعاملات ذات مبالغ مُقرَّبة"
    default_severity = "medium"
    rule_type = "anomaly"

    WARN_RATIO    = 0.30   # 30% of transactions are round numbers
    WARN_MIN_COUNT = 5

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.get("round_amount_count") is not None or
                isinstance(doc.get("transactions"), list))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        warn_ratio = float(self.get_config("warn_ratio", self.WARN_RATIO))
        min_count  = int(self.get_config("warn_min_count", self.WARN_MIN_COUNT))
        round_count = doc.get("round_amount_count")
        tx_count    = doc.get("transaction_count") or len(doc.get("transactions") or [])

        if round_count is None:
            transactions = doc.get("transactions") or []
            round_count = sum(
                1 for tx in transactions
                if float(tx.get("amount", 0) or 0) % 1000 == 0 and float(tx.get("amount", 0) or 0) != 0
            )
            tx_count = len(transactions)

        if tx_count == 0:
            return self._skipped("No transactions to analyse.")

        ratio = round_count / tx_count if tx_count else 0
        evidence = [EvidenceItem(
            evidence_type="statistical",
            field_name="round_amount_count",
            field_name_ar="عدد المعاملات ذات المبالغ المُقرَّبة",
            expected_value=f"< {warn_ratio:.0%} of transactions",
            actual_value=f"{round_count}/{tx_count} ({ratio:.0%})",
            description=f"{round_count} round-amount transactions out of {tx_count}.",
            description_ar=f"{round_count} معاملة بمبالغ مُقرَّبة من أصل {tx_count}.",
        )]

        if round_count >= min_count and ratio >= warn_ratio:
            return self._warning(
                f"{round_count} round-number transactions ({ratio:.0%} of total). "
                "Unusual clustering may indicate fictitious or manipulated entries.",
                f"{round_count} معاملة بمبالغ مُقرَّبة ({ratio:.0%} من الإجمالي). "
                "التجمّع غير العادي قد يدل على قيود وهمية أو متلاعَب بها.",
                evidence=evidence,
            )
        return self._pass(
            f"Round-amount ratio {ratio:.0%} is within normal range.",
            f"نسبة المبالغ المُقرَّبة {ratio:.0%} ضمن النطاق الطبيعي.",
        )


class WeekendTransactionRule(AuditRuleBase):
    """BNK-M04 — Flags bank statements with many weekend transactions (Fri/Sat in GCC)."""
    rule_code = "BNK-M04"
    rule_name_en = "Unusual Weekend Transaction Activity"
    rule_name_ar = "نشاط غير معتاد في معاملات عطلة الأسبوع"
    default_severity = "medium"
    rule_type = "anomaly"

    WARN_COUNT = 3

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.get("weekend_tx_count") is not None or
                isinstance(doc.get("transactions"), list))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        warn_count = int(self.get_config("warn_count", self.WARN_COUNT))
        weekend_count = doc.get("weekend_tx_count")

        if weekend_count is None:
            transactions = doc.get("transactions") or []
            from datetime import datetime
            weekend_count = 0
            for tx in transactions:
                try:
                    d = str(tx.get("date", ""))
                    if d:
                        dt = datetime.fromisoformat(d)
                        if dt.weekday() in (4, 5):  # Fri/Sat
                            weekend_count += 1
                except (ValueError, TypeError):
                    pass

        evidence = [EvidenceItem(
            evidence_type="statistical",
            field_name="weekend_tx_count",
            field_name_ar="عدد معاملات العطلة",
            expected_value=f"< {warn_count}",
            actual_value=weekend_count,
            description=f"{weekend_count} transactions on weekend days.",
            description_ar=f"{weekend_count} معاملة في أيام العطلة.",
        )]

        if weekend_count >= warn_count:
            return self._warning(
                f"{weekend_count} transactions on weekend days (Friday/Saturday). "
                "Weekend transactions may indicate unauthorised activity.",
                f"{weekend_count} معاملة في أيام العطلة (الجمعة/السبت). "
                "معاملات العطلة قد تدل على نشاط غير مصرَّح به.",
                evidence=evidence,
            )
        return self._pass(
            f"Weekend transaction count ({weekend_count}) is within normal range.",
            f"عدد معاملات العطلة ({weekend_count}) ضمن النطاق الطبيعي.",
        )


class LateNightTransactionRule(AuditRuleBase):
    """BNK-M05 — Flags transactions processed in late-night hours (23:00–05:00)."""
    rule_code = "BNK-M05"
    rule_name_en = "Late-Night Transaction Detected"
    rule_name_ar = "معاملات في ساعات متأخرة من الليل"
    default_severity = "medium"
    rule_type = "anomaly"

    WARN_COUNT   = 2
    LATE_START_H = 23
    LATE_END_H   = 5

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.get("late_night_tx_count") is not None or
                isinstance(doc.get("transactions"), list))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        warn_count = int(self.get_config("warn_count", self.WARN_COUNT))
        late_count = doc.get("late_night_tx_count")

        if late_count is None:
            transactions = doc.get("transactions") or []
            from datetime import datetime
            late_count = 0
            for tx in transactions:
                try:
                    t = tx.get("time") or tx.get("datetime") or ""
                    if t:
                        dt = datetime.fromisoformat(str(t))
                        h = dt.hour
                        if h >= self.LATE_START_H or h < self.LATE_END_H:
                            late_count += 1
                except (ValueError, TypeError):
                    pass

        evidence = [EvidenceItem(
            evidence_type="statistical",
            field_name="late_night_tx_count",
            field_name_ar="عدد المعاملات الليلية",
            expected_value=f"< {warn_count}",
            actual_value=late_count,
            description=f"{late_count} transactions between 23:00–05:00.",
            description_ar=f"{late_count} معاملة بين الساعة 23:00 و05:00.",
        )]

        if late_count >= warn_count:
            return self._warning(
                f"{late_count} transaction(s) processed during late-night hours (23:00–05:00). "
                "After-hours transactions carry elevated fraud risk.",
                f"{late_count} معاملة مُعالَجة في ساعات متأخرة من الليل (23:00–05:00). "
                "معاملات خارج أوقات العمل تحمل مخاطر احتيال أعلى.",
                evidence=evidence,
            )
        return self._pass(
            f"Late-night transaction count ({late_count}) is within acceptable range.",
            f"عدد المعاملات الليلية ({late_count}) ضمن النطاق المقبول.",
        )
