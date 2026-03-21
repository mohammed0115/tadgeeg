"""REC-M01, REC-M03: Sales receipt audit rules"""
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class QRCodeContentRule(AuditRuleBase):
    rule_code = "REC-M01"
    rule_name_en = "QR Code Content Invalid"
    rule_name_ar = "محتوى رمز QR غير صالح"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("has_qr_code", False)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        qr_valid = doc.get("qr_code_valid", False)
        qr_data = doc.get("qr_code_data", {}) or {}

        if not qr_valid:
            return self._fail(
                "QR code is present but content validation failed (TLV fields may not match document data).",
                "رمز QR موجود لكن التحقق من محتواه فشل (حقول TLV قد لا تطابق بيانات المستند).",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="qr_code_valid",
                    field_name_ar="صلاحية رمز QR",
                    expected_value=True,
                    actual_value=False,
                    description="QR code TLV content validation failed.",
                    description_ar="فشل التحقق من محتوى رمز QR (صيغة TLV).",
                )]
            )
        return self._pass(
            "QR code content is valid per ZATCA TLV specification.",
            "محتوى رمز QR صالح وفق مواصفات ZATCA.",
        )


class CashReceiptLimitRule(AuditRuleBase):
    rule_code = "REC-M03"
    rule_name_en = "Receipt Amount Exceeds Cash Limit"
    rule_name_ar = "مبلغ الإيصال يتجاوز حد الدفع النقدي"
    default_severity = "high"
    rule_type = "compliance"

    # Saudi AML threshold: SAR 60,000 for cash transactions
    CASH_LIMIT = 60000

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.total_amount is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        amount = float(doc.total_amount or 0)
        limit = float(self.get_config("cash_limit", self.CASH_LIMIT))
        receipt_type = str(doc.get("receipt_type", "")).lower()

        # Only applies to cash receipts
        payment_method = str(doc.get("payment_method", "cash")).lower()
        if payment_method not in ("cash", "نقدي", ""):
            return self._not_applicable(
                f"Cash limit check not applicable to '{payment_method}' payment method."
            )

        if amount > limit:
            return self._fail(
                f"Cash receipt amount {amount:,.2f} {doc.currency or 'SAR'} exceeds AML threshold of {limit:,.0f}.",
                f"مبلغ الإيصال النقدي {amount:,.2f} {doc.currency or 'ريال'} يتجاوز حد مكافحة غسيل الأموال {limit:,.0f}.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="total_amount",
                    field_name_ar="المبلغ الإجمالي",
                    expected_value=f"<= {limit:,.0f}",
                    actual_value=amount,
                    description=f"Cash receipt {amount:,.2f} exceeds AML reporting threshold {limit:,.0f}.",
                    description_ar=f"الإيصال النقدي {amount:,.2f} يتجاوز حد الإبلاغ لمكافحة غسيل الأموال {limit:,.0f}.",
                )]
            )
        return self._pass(
            f"Receipt amount {amount:,.2f} is within the cash limit {limit:,.0f}.",
            f"مبلغ الإيصال {amount:,.2f} ضمن حد الدفع النقدي المسموح {limit:,.0f}.",
        )
