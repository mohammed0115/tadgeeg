"""
VAT-01 / VAT-02 / VAT-04 / VAT-05 — GCC-aware VAT validation rules.

Supported countries and their VAT rates / number formats:
  SA — Saudi Arabia  : 15%, TRN = 15 digits starting with 3
  AE — UAE           : 5%,  TRN = 15 digits
  BH — Bahrain       : 10%, TRN = 9 digits
  KW — Kuwait        : 0%,  no VAT registration required
  OM — Oman          : 5%,  TRN = 10 chars starting with OM
  QA — Qatar         : 0%,  no VAT registration required
"""
import re
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem

# ─── GCC VAT configuration ────────────────────────────────────────────────────

_GCC_VAT_RATES: dict[str, Decimal] = {
    "SA": Decimal("15.0"),
    "AE": Decimal("5.0"),
    "BH": Decimal("10.0"),
    "KW": Decimal("0.0"),
    "OM": Decimal("5.0"),
    "QA": Decimal("0.0"),
}

# Each entry: label, validator callable, format description
_GCC_VAT_PATTERNS: dict[str, dict] = {
    "SA": {
        "label":     "ZATCA TRN (Saudi Arabia)",
        "format":    "15 digits starting with 3",
        "validator": lambda n: n.isdigit() and len(n) == 15 and n.startswith("3"),
    },
    "AE": {
        "label":     "FTA TRN (UAE)",
        "format":    "15 digits",
        "validator": lambda n: n.isdigit() and len(n) == 15,
    },
    "BH": {
        "label":     "NBR TRN (Bahrain)",
        "format":    "9 digits",
        "validator": lambda n: n.isdigit() and len(n) == 9,
    },
    "OM": {
        "label":     "OTA TRN (Oman)",
        "format":    "OM + 8 digits",
        "validator": lambda n: bool(re.fullmatch(r"OM\d{8}", n.upper())),
    },
    # KW and QA have no VAT → handled as NOT_APPLICABLE in the rule
}

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
        country = (doc.get_org("country") or "SA").upper()

        # KW and QA have 0% VAT — no VAT rate validation needed
        if country in ("KW", "QA"):
            return self._not_applicable(f"VAT is not applicable in {country}.")

        country_rate = _GCC_VAT_RATES.get(country, Decimal("15.0"))
        expected = self.safe_decimal(self.get_config("expected_vat_rate", str(country_rate)))
        tolerance = self.safe_decimal(self.get_config("vat_rate_tolerance", "0.5"))

        if abs(rate - expected) > tolerance:
            return self._fail(
                f"VAT rate is {rate}% but expected {expected}% (±{tolerance}%) for {country}.",
                f"نسبة الضريبة {rate}% لكن المتوقع {expected}% (±{tolerance}%) لـ {country}.",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="vat_rate",
                    field_name_ar="نسبة الضريبة",
                    expected_value=float(expected),
                    actual_value=float(rate),
                    description=f"VAT rate {rate}% deviates from standard {expected}% for {country}.",
                    description_ar=f"نسبة الضريبة {rate}% تختلف عن المعيار {expected}% لـ {country}.",
                )]
            )
        return self._pass(f"VAT rate {rate}% is correct for {country}.", f"نسبة الضريبة {rate}% صحيحة لـ {country}.")


class VATNumberFormatRule(AuditRuleBase):
    rule_code = "VAT-04"
    rule_name_en = "VAT Number Format Valid"
    rule_name_ar = "صيغة الرقم الضريبي صحيحة"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.tax_id is not None or doc.get("vendor_vat_number") is not None

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        country = (doc.get_org("country") or "SA").upper()

        # KW and QA have no VAT registration requirement
        if country in ("KW", "QA"):
            return self._not_applicable(f"VAT registration number is not required in {country}.")

        vat_num = doc.tax_id or doc.get("vendor_vat_number") or doc.get("vat_number") or ""
        vat_num = str(vat_num).strip()

        pattern_cfg = _GCC_VAT_PATTERNS.get(country)
        # Fallback to SA if country not in GCC patterns dict
        if pattern_cfg is None:
            pattern_cfg = _GCC_VAT_PATTERNS["SA"]
            country = "SA"

        if not vat_num:
            return self._fail(
                f"VAT/Tax number is missing ({pattern_cfg['label']}).",
                f"الرقم الضريبي مفقود ({pattern_cfg['label']}).",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="vat_number",
                    field_name_ar="الرقم الضريبي",
                    expected_value=pattern_cfg["format"],
                    actual_value=None,
                    description="VAT number not found.",
                    description_ar="لم يتم العثور على الرقم الضريبي.",
                )]
            )

        is_valid = pattern_cfg["validator"](vat_num)

        if not is_valid:
            return self._fail(
                f"VAT number '{vat_num}' does not match {pattern_cfg['label']} format ({pattern_cfg['format']}).",
                f"الرقم الضريبي '{vat_num}' لا يتوافق مع صيغة {pattern_cfg['label']} ({pattern_cfg['format']}).",
                evidence=[EvidenceItem(
                    evidence_type="field_value",
                    field_name="vat_number",
                    field_name_ar="الرقم الضريبي",
                    expected_value=pattern_cfg["format"],
                    actual_value=vat_num,
                    description=f"Format validation failed for '{vat_num}' against {pattern_cfg['label']}.",
                    description_ar=f"فشل التحقق من صيغة الرقم '{vat_num}' لـ {pattern_cfg['label']}.",
                )]
            )
        return self._pass(
            f"VAT number '{vat_num}' is valid ({pattern_cfg['label']}).",
            f"الرقم الضريبي '{vat_num}' صحيح ({pattern_cfg['label']}).",
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
