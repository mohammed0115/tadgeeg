"""VAT-02 + VAT-03: VAT calculation correctness"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

class VATCalculationRule(AuditRuleBase):
    rule_code = "VAT-02"
    rule_name_en = "VAT Calculation Correct"
    rule_name_ar = "صحة حساب الضريبة المضافة"
    default_severity = "high"
    rule_type = "validation"

    DEFAULT_TOLERANCE = Decimal("1.00")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return (doc.get("subtotal") is not None and
                doc.get("vat_amount") is not None and
                doc.total_amount is not None)

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        tolerance = self.safe_decimal(self.get_config("tolerance", "1.00"))
        subtotal = self.safe_decimal(doc.get("subtotal"))
        vat_amount = self.safe_decimal(doc.get("vat_amount"))
        total = self.safe_decimal(doc.total_amount)

        expected_total = subtotal + vat_amount
        discrepancy = abs(expected_total - total)

        evidence = [EvidenceItem(
            evidence_type="calculation",
            field_name="total_amount",
            field_name_ar="المبلغ الإجمالي",
            expected_value=float(expected_total),
            actual_value=float(total),
            description=f"subtotal({subtotal}) + vat({vat_amount}) = {expected_total}, document shows {total}",
            description_ar=f"الأساس({subtotal}) + الضريبة({vat_amount}) = {expected_total}، المستند يُظهر {total}",
        )]

        if discrepancy > tolerance:
            return self._fail(
                f"VAT calculation error: discrepancy of {discrepancy} {doc.currency or 'SAR'}.",
                f"خطأ في حساب الضريبة: الفارق {discrepancy} {doc.currency or 'ريال'}.",
                evidence=evidence,
            )
        return self._pass(
            "Subtotal + VAT equals total amount within tolerance.",
            "مجموع الأساس والضريبة يساوي الإجمالي ضمن حد التفاوت.",
        )


class VATRateRule(AuditRuleBase):
    rule_code = "VAT-01"
    rule_name_en = "VAT Rate Correct (15%)"
    rule_name_ar = "نسبة الضريبة صحيحة (15%)"
    default_severity = "high"
    rule_type = "compliance"

    EXPECTED_RATE = Decimal("15.0")
    TOLERANCE = Decimal("0.5")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("vat_rate") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        rate = self.safe_decimal(doc.get("vat_rate"))
        expected = self.safe_decimal(self.get_config("expected_vat_rate", "15.0"))
        tolerance = self.safe_decimal(self.get_config("vat_rate_tolerance", "0.5"))

        if abs(rate - expected) > tolerance:
            return self._fail(
                f"VAT rate is {rate}% but expected {expected}% (±{tolerance}%).",
                f"نسبة الضريبة {rate}% لكن المتوقع {expected}% (±{tolerance}%).",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="vat_rate",
                    field_name_ar="نسبة الضريبة",
                    expected_value=float(expected),
                    actual_value=float(rate),
                    description=f"VAT rate {rate}% deviates from standard {expected}%.",
                    description_ar=f"نسبة الضريبة {rate}% تختلف عن المعيار {expected}%.",
                )]
            )
        return self._pass(f"VAT rate {rate}% is correct.", f"نسبة الضريبة {rate}% صحيحة.")


class VATNumberFormatRule(AuditRuleBase):
    rule_code = "VAT-04"
    rule_name_en = "VAT Number Format Valid"
    rule_name_ar = "صيغة الرقم الضريبي صحيحة"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.tax_id is not None or doc.get("vendor_vat_number") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        vat_num = doc.tax_id or doc.get("vendor_vat_number") or doc.get("vat_number") or ""
        vat_num = str(vat_num).strip()

        if not vat_num:
            return self._fail(
                "VAT/Tax number is missing.",
                "الرقم الضريبي مفقود.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="vat_number",
                    field_name_ar="الرقم الضريبي",
                    expected_value="15-digit number starting with 3",
                    actual_value=None,
                    description="VAT number not found.",
                    description_ar="لم يتم العثور على الرقم الضريبي.",
                )]
            )

        # SA VAT number: 15 digits, starts with 3
        is_valid = vat_num.isdigit() and len(vat_num) == 15 and vat_num.startswith("3")

        if not is_valid:
            return self._fail(
                f"VAT number '{vat_num}' does not match SA format (15 digits starting with 3).",
                f"الرقم الضريبي '{vat_num}' لا يتوافق مع صيغة الزكاة السعودية (15 رقمًا تبدأ بـ 3).",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="vat_number",
                    field_name_ar="الرقم الضريبي",
                    expected_value="15-digit starting with 3",
                    actual_value=vat_num,
                    description=f"Format validation failed for '{vat_num}'.",
                    description_ar=f"فشل التحقق من صيغة الرقم '{vat_num}'.",
                )]
            )
        return self._pass(
            f"VAT number '{vat_num}' is valid.",
            f"الرقم الضريبي '{vat_num}' صحيح.",
        )


class ZATCAQRCodeRule(AuditRuleBase):
    rule_code = "VAT-05"
    rule_name_en = "ZATCA QR Code Valid"
    rule_name_ar = "صلاحية رمز QR للزكاة"
    default_severity = "medium"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.document_type in ("sales_invoice", "sales_receipt")

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        has_qr = doc.get("has_qr_code", False)
        qr_valid = doc.get("qr_code_valid", False)

        if not has_qr:
            return self._warning(
                "ZATCA QR code is missing from the document.",
                "رمز QR الخاص بالزكاة غير موجود في المستند.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="has_qr_code",
                    field_name_ar="وجود رمز QR",
                    expected_value=True,
                    actual_value=False,
                    description="QR code not detected on document.",
                    description_ar="لم يتم الكشف عن رمز QR في المستند.",
                )]
            )

        if not qr_valid:
            return self._fail(
                "ZATCA QR code is present but its content is invalid.",
                "رمز QR موجود لكن محتواه غير صالح.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="qr_code_valid",
                    field_name_ar="صلاحية رمز QR",
                    expected_value=True,
                    actual_value=False,
                    description="QR code failed content validation.",
                    description_ar="فشل التحقق من محتوى رمز QR.",
                )]
            )

        return self._pass("ZATCA QR code is present and valid.", "رمز QR موجود وصالح.")
