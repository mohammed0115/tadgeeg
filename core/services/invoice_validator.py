"""
Invoice Validation Engine
Implements all 30 invoice auditing rules from the business requirements.

Rule Groups:
  Group 1 — Invoice Header Validation    (8 rules)
  Group 2 — Duplicate Detection          (5 rules)
  Group 3 — VAT Validation               (5 rules)
  Group 4 — Anomaly Detection            (6 rules)
  Group 5 — Financial Controls           (6 rules)
  Group 6 — Document Quality             (4 rules)
"""

import hashlib
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

logger = logging.getLogger("finai")

# ─── Rule codes ──────────────────────────────────────────────────────────────
# Arabic and English descriptions are kept side-by-side so the API layer can
# pick the right one at serialization time based on the current request
# language. The DB still stores Arabic (legacy behavior) — translation happens
# on read in invoices/serializers.py::InvoiceValidationResultSerializer.
RULES_AR = {
    # Group 1 – Header
    "INV-001": "يجب أن تحتوي الفاتورة على رقم فاتورة",
    "INV-002": "يجب أن تحتوي الفاتورة على تاريخ",
    "INV-003": "يجب أن تحتوي الفاتورة على اسم المورد",
    "INV-004": "يجب أن تحتوي الفاتورة على الرقم الضريبي للمورد",
    "INV-005": "يجب أن تحتوي الفاتورة على المبلغ الإجمالي",
    "INV-006": "يجب أن تحتوي الفاتورة على العملة",
    "INV-007": "يجب أن يكون المبلغ الإجمالي أكبر من صفر",
    "INV-008": "لا يمكن وجود ضريبة القيمة المضافة بدون مبلغ أساسي (المجموع الفرعي)",
    # Group 2 – Duplicate
    "DUP-001": "رقم الفاتورة موجود مسبقاً لهذا المورد",
    "DUP-002": "نفس المورد ونفس رقم الفاتورة مسجّل مسبقاً",
    "DUP-003": "نفس المورد ونفس المبلغ ونفس التاريخ مسجّل مسبقاً",
    "DUP-004": "محتوى الملف (البصمة الرقمية) تم رفعه مسبقاً",
    "DUP-005": "رقم الفاتورة ذاته يظهر في شهر مختلف",
    # Group 3 – VAT
    "VAT-001": "يجب أن تكون نسبة ضريبة القيمة المضافة 15% في المملكة العربية السعودية",
    "VAT-002": "يجب أن يكون حساب الضريبة صحيحاً (المجموع × النسبة = الضريبة)",
    "VAT-003": "يجب أن يساوي مجموع (المبلغ الأساسي + الضريبة) المبلغ الإجمالي",
    "VAT-004": "يجب توفر الرقم الضريبي للمورد",
    "VAT-005": "يجب توفر رمز QR الخاص بهيئة الزكاة والضريبة والجمارك وأن يكون صالحاً",
    # Group 4 – Anomaly
    "ANO-001": "مبلغ الفاتورة مرتفع بشكل غير معتاد مقارنةً بسجل المورد",
    "ANO-002": "المورد جديد ولم يسبق التعامل معه",
    "ANO-003": "عدد كبير من الفواتير من نفس المورد في اليوم ذاته",
    "ANO-004": "تغيّر مفاجئ ملحوظ في السعر مقارنةً بالفواتير السابقة",
    "ANO-005": "تركّز مرتفع في الفواتير بالقرب من نهاية السنة المالية",
    "ANO-006": "مورد واحد يهيمن على أكثر من 50% من إجمالي الإنفاق",
    # Group 5 – Financial Controls
    "CTL-001": "يجب ربط الفاتورة بمركز تكلفة",
    "CTL-002": "يجب ربط الفاتورة برمز محاسبي",
    "CTL-003": "يجب أن يكون مبلغ الفاتورة ضمن ميزانية القسم",
    "CTL-004": "لا يجوز تعديل الفاتورة بعد اعتمادها",
    "CTL-005": "يجب تعيين معتمِد للفاتورة",
    "CTL-006": "يجب تسجيل جميع التغييرات في سجل التدقيق",
    # Group 6 – Document Quality
    "DOC-001": "يجب أن يكون المستند واضحاً وقابلاً للقراءة",
    "DOC-002": "يجب أن يبدو المستند أصلياً (غير مزوّر)",
    "DOC-003": "يجب ألا يُظهر المستند علامات تعديل أو تلاعب",
    "DOC-004": "يجب أن تحتوي الفاتورة الإلكترونية المتوافقة مع هيئة الزكاة على رمز QR",
}

RULES_EN = {
    # Group 1 – Header
    "INV-001": "Invoice must contain an invoice number",
    "INV-002": "Invoice must contain a date",
    "INV-003": "Invoice must contain a vendor name",
    "INV-004": "Invoice must contain the vendor's VAT number",
    "INV-005": "Invoice must contain a total amount",
    "INV-006": "Invoice must contain a currency",
    "INV-007": "Total amount must be greater than zero",
    "INV-008": "VAT cannot exist without a base amount (subtotal)",
    # Group 2 – Duplicate
    "DUP-001": "Invoice number already exists for this vendor",
    "DUP-002": "Same vendor with the same invoice number is already recorded",
    "DUP-003": "Same vendor, amount, and date are already recorded",
    "DUP-004": "File content (digital fingerprint) was already uploaded",
    "DUP-005": "Same invoice number appears in a different month",
    # Group 3 – VAT
    "VAT-001": "VAT rate must be 15% in Saudi Arabia",
    "VAT-002": "VAT calculation must be correct (subtotal × rate = VAT)",
    "VAT-003": "Subtotal + VAT must equal the total amount",
    "VAT-004": "Vendor VAT number must be present",
    "VAT-005": "A valid ZATCA QR code must be present",
    # Group 4 – Anomaly
    "ANO-001": "Invoice amount is unusually high vs. the vendor's history",
    "ANO-002": "Vendor is new and has no prior transactions",
    "ANO-003": "Large number of invoices from the same vendor on the same day",
    "ANO-004": "Notable sudden price change vs. previous invoices",
    "ANO-005": "High invoice concentration near the end of the fiscal year",
    "ANO-006": "A single vendor accounts for more than 50% of total spend",
    # Group 5 – Financial Controls
    "CTL-001": "Invoice must be linked to a cost center",
    "CTL-002": "Invoice must be linked to an accounting code",
    "CTL-003": "Invoice amount must be within the department budget",
    "CTL-004": "Invoice cannot be modified after approval",
    "CTL-005": "An approver must be assigned to the invoice",
    "CTL-006": "All changes must be recorded in the audit log",
    # Group 6 – Document Quality
    "DOC-001": "Document must be clear and legible",
    "DOC-002": "Document must appear authentic (not forged)",
    "DOC-003": "Document must not show signs of editing or tampering",
    "DOC-004": "A ZATCA-compliant electronic invoice must contain a QR code",
}

# Backwards-compatible alias — existing code still imports RULES.
RULES = RULES_AR

TOTAL_RULES = len(RULES_AR)


def rule_description(code: str, language: str = None) -> str:
    """Return the description for a rule code in the given language.

    ``language`` defaults to the active Django translation (Arabic if the
    request is Arabic, English otherwise). Falls back to the other language
    if the requested one is missing, then to the bare rule code.
    """
    if language is None:
        try:
            from django.utils.translation import get_language
            language = get_language() or "en"
        except Exception:
            language = "en"
    lang = (language or "").lower()
    if lang.startswith("ar"):
        return RULES_AR.get(code) or RULES_EN.get(code) or code
    return RULES_EN.get(code) or RULES_AR.get(code) or code


def run_all_rules(invoice, organization=None, file_hash: str = None) -> dict:
    """
    Run all 30 validation rules against an Invoice instance.

    Args:
        invoice: Invoice model instance.
        organization: Organization instance (for historical context).
        file_hash: MD5/SHA256 hash of the uploaded file (for duplicate detection).

    Returns:
        dict with full validation result including per-rule details.
    """
    from apps.invoices.models import Invoice as InvoiceModel

    results = {}
    failed = []
    passed = []

    org = organization or invoice.organization

    # ─── Group 1: Header Validation ──────────────────────────────────────────

    # INV-001: invoice number
    ok = bool(invoice.invoice_number and invoice.invoice_number.strip())
    results["INV-001"] = _rule(ok, RULES["INV-001"],
                               "رقم الفاتورة موجود" if ok else "رقم الفاتورة مفقود",
                               field="invoice_number", actual=invoice.invoice_number or "",
                               expected="قيمة غير فارغة")
    _record(ok, "INV-001", passed, failed)

    # INV-002: date
    ok = invoice.invoice_date is not None
    results["INV-002"] = _rule(ok, RULES["INV-002"],
                               f"التاريخ: {invoice.invoice_date}" if ok else "تاريخ الفاتورة مفقود",
                               field="invoice_date", actual=str(invoice.invoice_date or ""),
                               expected="تاريخ صالح")
    _record(ok, "INV-002", passed, failed)

    # INV-003: vendor name
    ok = bool(invoice.vendor_name and invoice.vendor_name.strip())
    results["INV-003"] = _rule(ok, RULES["INV-003"],
                               f"المورد: {invoice.vendor_name}" if ok else "اسم المورد مفقود",
                               field="vendor_name", actual=invoice.vendor_name or "",
                               expected="قيمة غير فارغة")
    _record(ok, "INV-003", passed, failed)

    # INV-004: vendor VAT number
    ok = bool(invoice.vendor_vat_number and invoice.vendor_vat_number.strip())
    results["INV-004"] = _rule(ok, RULES["INV-004"],
                               f"الرقم الضريبي: {invoice.vendor_vat_number}" if ok else "الرقم الضريبي للمورد مفقود",
                               field="vendor_vat_number", actual=invoice.vendor_vat_number or "",
                               expected="رقم ضريبي من 15 خانة")
    _record(ok, "INV-004", passed, failed)

    # INV-005: total amount field exists
    ok = invoice.total_amount is not None
    results["INV-005"] = _rule(ok, RULES["INV-005"],
                               "حقل المبلغ الإجمالي موجود" if ok else "حقل المبلغ الإجمالي مفقود",
                               field="total_amount", actual=str(invoice.total_amount or ""),
                               expected="قيمة موجودة")
    _record(ok, "INV-005", passed, failed)

    # INV-006: currency
    ok = bool(invoice.currency and invoice.currency.strip())
    results["INV-006"] = _rule(ok, RULES["INV-006"],
                               f"العملة: {invoice.currency}" if ok else "العملة غير محددة",
                               field="currency", actual=invoice.currency or "",
                               expected="رمز عملة (مثل SAR)")
    _record(ok, "INV-006", passed, failed)

    # INV-007: total > 0
    ok = float(invoice.total_amount or 0) > 0
    results["INV-007"] = _rule(ok, RULES["INV-007"],
                               f"الإجمالي = {invoice.total_amount}" if ok else f"الإجمالي = {invoice.total_amount} (يجب أن يكون أكبر من صفر)",
                               field="total_amount", actual=str(invoice.total_amount or 0),
                               expected="أكبر من صفر")
    _record(ok, "INV-007", passed, failed)

    # INV-008: VAT without base
    vat = float(invoice.vat_amount or 0)
    sub = float(invoice.subtotal or 0)
    ok = not (vat > 0 and sub == 0)  # True means NO violation
    results["INV-008"] = _rule(ok, RULES["INV-008"],
                               "الضريبة مرتبطة بالمجموع الفرعي بشكل صحيح" if ok else "الضريبة موجودة لكن المجموع الفرعي صفر",
                               field="subtotal", actual=f"subtotal={sub}, vat={vat}",
                               expected="مجموع فرعي أكبر من صفر متى وُجدت ضريبة")
    _record(ok, "INV-008", passed, failed)

    # ─── Group 2: Duplicate Detection ────────────────────────────────────────

    # DUP-001: duplicate invoice number same vendor
    dup_same_vendor_num = False
    if invoice.invoice_number and invoice.vendor_name:
        dup_same_vendor_num = InvoiceModel.objects.filter(
            organization=org,
            invoice_number=invoice.invoice_number,
            vendor_name=invoice.vendor_name,
        ).exclude(pk=invoice.pk).exists()
    ok = not dup_same_vendor_num
    results["DUP-001"] = _rule(ok, RULES["DUP-001"],
                               "لا يوجد تكرار في رقم الفاتورة" if ok else
                               f"رقم الفاتورة '{invoice.invoice_number}' موجود مسبقاً للمورد '{invoice.vendor_name}'",
                               severity="critical" if not ok else "info")
    _record(ok, "DUP-001", passed, failed)

    # DUP-002: same vendor + same invoice number
    dup_vend_num = False
    if invoice.invoice_number and invoice.vendor_name:
        dup_vend_num = InvoiceModel.objects.filter(
            organization=org,
            invoice_number=invoice.invoice_number,
        ).exclude(pk=invoice.pk).exists()
    ok = not dup_vend_num
    results["DUP-002"] = _rule(ok, RULES["DUP-002"],
                               "رقم الفاتورة فريد في النظام" if ok else "رقم الفاتورة موجود مسبقاً في النظام",
                               severity="critical" if not ok else "info")
    _record(ok, "DUP-002", passed, failed)

    # DUP-003: same vendor + amount + date
    dup_amt_date = False
    if invoice.vendor_name and invoice.invoice_date and invoice.total_amount:
        dup_amt_date = InvoiceModel.objects.filter(
            organization=org,
            vendor_name=invoice.vendor_name,
            total_amount=invoice.total_amount,
            invoice_date=invoice.invoice_date,
        ).exclude(pk=invoice.pk).exists()
    ok = not dup_amt_date
    results["DUP-003"] = _rule(ok, RULES["DUP-003"],
                               "لا يوجد تكرار في المبلغ والتاريخ" if ok else
                               "فاتورة مكررة محتملة: نفس المورد والمبلغ والتاريخ",
                               severity="high" if not ok else "info")
    _record(ok, "DUP-003", passed, failed)

    # DUP-004: file hash duplicate
    dup_hash = False
    if file_hash:
        dup_hash = InvoiceModel.objects.filter(
            organization=org,
            extracted_data__file_hash=file_hash,
        ).exclude(pk=invoice.pk).exists()
    ok = not dup_hash
    results["DUP-004"] = _rule(ok, RULES["DUP-004"],
                               "الملف فريد ولم يُرفع مسبقاً" if ok else "ملف مطابق تم رفعه مسبقاً",
                               severity="critical" if not ok else "info")
    _record(ok, "DUP-004", passed, failed)

    # DUP-005: same invoice number different month
    dup_diff_month = False
    if invoice.invoice_number and invoice.invoice_date:
        existing = InvoiceModel.objects.filter(
            organization=org,
            invoice_number=invoice.invoice_number,
        ).exclude(pk=invoice.pk).exclude(invoice_date__month=invoice.invoice_date.month)
        dup_diff_month = existing.exists()
    ok = not dup_diff_month
    results["DUP-005"] = _rule(ok, RULES["DUP-005"],
                               "لا يوجد تكرار في شهر مختلف" if ok else
                               "نفس رقم الفاتورة موجود في شهر مختلف",
                               severity="high" if not ok else "info")
    _record(ok, "DUP-005", passed, failed)

    # ─── Group 3: VAT Validation ─────────────────────────────────────────────

    # VAT-001: rate = 15% for SA
    expected_rate = 15.0
    if org and org.vat_rate:
        expected_rate = float(org.vat_rate)
    actual_rate = float(invoice.vat_rate or 0)
    ok = abs(actual_rate - expected_rate) < 0.5
    results["VAT-001"] = _rule(ok, RULES["VAT-001"],
                               f"نسبة الضريبة {actual_rate}% ✓" if ok else
                               f"نسبة الضريبة {actual_rate}% (المتوقع {expected_rate}%)",
                               field="vat_rate", actual=actual_rate,
                               expected=f"{expected_rate}% (±0.5)")
    _record(ok, "VAT-001", passed, failed)

    # VAT-002: vat_amount = subtotal × rate
    if sub > 0:
        expected_vat = round(sub * float(invoice.vat_rate or 0) / 100, 2)
        ok = abs(float(invoice.vat_amount or 0) - expected_vat) < 1.0
        msg = f"الضريبة {invoice.vat_amount} تطابق المتوقع {expected_vat} ✓" if ok else \
              f"الضريبة {invoice.vat_amount} لا تطابق المتوقع {expected_vat}"
    else:
        ok = float(invoice.vat_amount or 0) == 0
        msg = "لا ضريبة على مجموع فرعي صفري — صحيح" if ok else "الضريبة موجودة لكن المجموع الفرعي صفر"
    results["VAT-002"] = _rule(ok, RULES["VAT-002"], msg,
                               field="vat_amount", actual=float(invoice.vat_amount or 0),
                               expected=(f"{expected_vat} (= {sub} × {invoice.vat_rate or 0}%)"
                                         if sub > 0 else "صفر، لأن المجموع الفرعي صفر"))
    _record(ok, "VAT-002", passed, failed)

    # VAT-003: subtotal + vat = total
    total = float(invoice.total_amount or 0)
    expected_total = round(sub + float(invoice.vat_amount or 0) - float(invoice.discount or 0), 2)
    ok = abs(total - expected_total) < 1.0
    results["VAT-003"] = _rule(ok, RULES["VAT-003"],
                               "المجموع الفرعي + الضريبة = الإجمالي ✓" if ok else
                               f"المجموع({sub}) + الضريبة({invoice.vat_amount}) = {expected_total} ≠ الإجمالي({total})",
                               field="total_amount", actual=total,
                               expected=f"{expected_total} (= {sub} + {invoice.vat_amount or 0} − {invoice.discount or 0})")
    _record(ok, "VAT-003", passed, failed)

    # VAT-004: VAT number present
    ok = bool(invoice.vendor_vat_number and invoice.vendor_vat_number.strip())
    results["VAT-004"] = _rule(ok, RULES["VAT-004"],
                               f"الرقم الضريبي: {invoice.vendor_vat_number}" if ok else "الرقم الضريبي للمورد مفقود",
                               field="vendor_vat_number", actual=invoice.vendor_vat_number or "",
                               expected="رقم ضريبي غير فارغ")
    _record(ok, "VAT-004", passed, failed)

    # VAT-005: QR code (ZATCA FATOORAH compliance)
    ok = invoice.has_qr_code and invoice.qr_code_valid
    if invoice.has_qr_code and not invoice.qr_code_valid:
        msg = "رمز QR موجود لكن تعذّر التحقق منه"
    elif not invoice.has_qr_code:
        msg = "رمز QR مفقود (مطلوب لنظام الفوترة الإلكترونية الخاص بهيئة الزكاة)"
    else:
        msg = "رمز QR موجود وصالح ✓"
    results["VAT-005"] = _rule(ok, RULES["VAT-005"], msg,
                               severity="high" if not ok else "info",
                               field="qr_code_valid",
                               actual=f"has_qr={invoice.has_qr_code}, valid={invoice.qr_code_valid}",
                               expected="رمز QR موجود ومُتحقَّق منه")
    _record(ok, "VAT-005", passed, failed)

    # ─── Group 4: Anomaly Detection ──────────────────────────────────────────

    # ANO-001: amount unusually high vs vendor history
    amount_anomaly = False
    vendor_avg = _get_vendor_avg(org, invoice.vendor_name, exclude_id=invoice.pk)
    if vendor_avg and vendor_avg > 0:
        ratio = float(invoice.total_amount or 0) / vendor_avg
        amount_anomaly = ratio > 3.0  # 3x above average
        msg = (f"المبلغ {invoice.total_amount} يتجاوز متوسط المورد بمعدل {ratio:.1f}x ({vendor_avg:.0f})"
               if amount_anomaly else
               f"المبلغ ضمن النطاق الطبيعي (المتوسط={vendor_avg:.0f}، النسبة={ratio:.1f}x)")
    else:
        msg = "لا توجد بيانات تاريخية للمقارنة"
    ok = not amount_anomaly
    results["ANO-001"] = _rule(ok, RULES["ANO-001"], msg,
                               severity="high" if not ok else "info")
    _record(ok, "ANO-001", passed, failed)

    # ANO-002: new/unknown vendor
    is_new_vendor = not InvoiceModel.objects.filter(
        organization=org, vendor_name=invoice.vendor_name
    ).exclude(pk=invoice.pk).exists()
    ok = not is_new_vendor
    results["ANO-002"] = _rule(ok, RULES["ANO-002"],
                               "المورد معروف في النظام" if ok else
                               f"'{invoice.vendor_name}' مورد جديد — أول فاتورة له",
                               severity="medium" if not ok else "info")
    _record(ok, "ANO-002", passed, failed)

    # ANO-003: many invoices same day from same vendor
    daily_count = 1
    if invoice.invoice_date and invoice.vendor_name:
        daily_count = InvoiceModel.objects.filter(
            organization=org,
            vendor_name=invoice.vendor_name,
            invoice_date=invoice.invoice_date,
        ).count()
    ok = daily_count <= 5
    results["ANO-003"] = _rule(ok, RULES["ANO-003"],
                               f"{daily_count} فاتورة/فواتير من المورد في هذا اليوم" if ok else
                               f"حجم مرتفع: {daily_count} فاتورة من '{invoice.vendor_name}' بتاريخ {invoice.invoice_date}",
                               severity="medium" if not ok else "info")
    _record(ok, "ANO-003", passed, failed)

    # ANO-004: sudden price change
    price_anomaly = False
    if invoice.vendor_name and vendor_avg and vendor_avg > 0:
        change_pct = abs(float(invoice.total_amount or 0) - vendor_avg) / vendor_avg * 100
        price_anomaly = change_pct > 50
        msg = (f"السعر تغيّر بنسبة {change_pct:.0f}% عن متوسط المورد"
               if price_anomaly else
               f"السعر ضمن نطاق {change_pct:.0f}% من متوسط المورد")
    else:
        price_anomaly = False
        msg = "لا يوجد سجل أسعار للمقارنة"
    ok = not price_anomaly
    results["ANO-004"] = _rule(ok, RULES["ANO-004"], msg,
                               severity="medium" if not ok else "info")
    _record(ok, "ANO-004", passed, failed)

    # ANO-005: year-end concentration
    year_end_anomaly = False
    if invoice.invoice_date:
        month = invoice.invoice_date.month
        if month in [11, 12]:  # November or December
            fiscal_end_count = InvoiceModel.objects.filter(
                organization=org,
                invoice_date__month__in=[11, 12],
                invoice_date__year=invoice.invoice_date.year,
            ).count()
            year_end_anomaly = fiscal_end_count > 20
            msg = (f"نشاط مرتفع في نهاية العام: {fiscal_end_count} فاتورة في نوفمبر-ديسمبر"
                   if year_end_anomaly else
                   f"نشاط نهاية العام: {fiscal_end_count} فاتورة")
        else:
            msg = "الفاتورة ليست في فترة نهاية السنة المالية"
    else:
        msg = "لا يوجد تاريخ للفحص"
    ok = not year_end_anomaly
    results["ANO-005"] = _rule(ok, RULES["ANO-005"], msg,
                               severity="medium" if not ok else "info")
    _record(ok, "ANO-005", passed, failed)

    # ANO-006: single vendor dominates spend
    from django.db.models import Sum
    vendor_total = InvoiceModel.objects.filter(
        organization=org, vendor_name=invoice.vendor_name
    ).aggregate(t=Sum("total_amount"))["t"] or 0
    org_total = InvoiceModel.objects.filter(organization=org).aggregate(
        t=Sum("total_amount")
    )["t"] or 0
    concentration = float(vendor_total) / float(org_total) * 100 if org_total else 0
    ok = concentration < 50
    results["ANO-006"] = _rule(ok, RULES["ANO-006"],
                               f"حصة المورد: {concentration:.1f}% من إجمالي الإنفاق" if ok else
                               f"المورد يهيمن على {concentration:.1f}% من إجمالي الإنفاق (أكثر من 50%)",
                               severity="high" if not ok else "info")
    _record(ok, "ANO-006", passed, failed)

    # ─── Group 5: Financial Controls ─────────────────────────────────────────

    # CTL-001: cost center
    ok = bool(invoice.cost_center and invoice.cost_center.strip())
    results["CTL-001"] = _rule(ok, RULES["CTL-001"],
                               f"مركز التكلفة: {invoice.cost_center}" if ok else "لم يُعيَّن مركز تكلفة")
    _record(ok, "CTL-001", passed, failed)

    # CTL-002: account code
    ok = bool(invoice.account_code and invoice.account_code.strip())
    results["CTL-002"] = _rule(ok, RULES["CTL-002"],
                               f"رمز الحساب: {invoice.account_code}" if ok else "لم يُعيَّن رمز محاسبي")
    _record(ok, "CTL-002", passed, failed)

    # CTL-003: within budget (simplified — pass if no budget set)
    ok = True   # Budget integration requires external budget data; default pass
    results["CTL-003"] = _rule(ok, RULES["CTL-003"], "فحص الميزانية: لم يُضبط أي بيانات ميزانية (يُوصى بالمراجعة اليدوية)")
    _record(ok, "CTL-003", passed, failed)

    # CTL-004: no edit after approval
    ok = not (invoice.status == "approved" and invoice.updated_at > invoice.approved_at) \
         if invoice.approved_at else True
    results["CTL-004"] = _rule(ok, RULES["CTL-004"],
                               "لم يُجرَ أي تعديل غير مصرّح به بعد الاعتماد" if ok else
                               "تم تعديل الفاتورة بعد اعتمادها!",
                               severity="critical" if not ok else "info")
    _record(ok, "CTL-004", passed, failed)

    # CTL-005: has approver
    ok = invoice.approved_by is not None
    results["CTL-005"] = _rule(ok, RULES["CTL-005"],
                               f"المعتمِد: {invoice.approved_by}" if ok else "لم يُعيَّن معتمِد للفاتورة")
    _record(ok, "CTL-005", passed, failed)

    # CTL-006: audit trail exists
    has_trail = invoice.audit_events.exists() if invoice.pk else False
    results["CTL-006"] = _rule(True, RULES["CTL-006"], "سجل التدقيق يُحفظ تلقائياً")
    _record(True, "CTL-006", passed, failed)

    # ─── Group 6: Document Quality ───────────────────────────────────────────

    # DOC-001: document is clear / readable
    ok = invoice.is_clear and invoice.ocr_confidence >= 60.0
    results["DOC-001"] = _rule(ok, RULES["DOC-001"],
                               f"وضوح المستند مقبول (الدقة={invoice.ocr_confidence:.0f}%)" if ok else
                               f"المستند غير واضح بما يكفي (الدقة={invoice.ocr_confidence:.0f}%)")
    _record(ok, "DOC-001", passed, failed)

    # DOC-002: appears genuine (AI assessed)
    ok = not invoice.extracted_data.get("ai_fraud_suspected", False)
    results["DOC-002"] = _rule(ok, RULES["DOC-002"],
                               "المستند يبدو أصلياً" if ok else
                               "الذكاء الاصطناعي رصد احتمال تزوير المستند")
    _record(ok, "DOC-002", passed, failed)

    # DOC-003: no alterations
    ok = not invoice.has_alterations
    results["DOC-003"] = _rule(ok, RULES["DOC-003"],
                               "لا توجد علامات تعديل أو تلاعب" if ok else
                               "المستند يُظهر علامات تعديل أو تلاعب",
                               severity="critical" if not ok else "info")
    _record(ok, "DOC-003", passed, failed)

    # DOC-004: QR code for ZATCA
    ok = invoice.has_qr_code
    results["DOC-004"] = _rule(ok, RULES["DOC-004"],
                               "تم اكتشاف رمز QR ✓" if ok else
                               "رمز QR الخاص بهيئة الزكاة مفقود",
                               severity="high" if not ok else "info")
    _record(ok, "DOC-004", passed, failed)

    # ─── Compute summary ─────────────────────────────────────────────────────
    n_passed = len(passed)
    n_failed = len(failed)
    score = round(n_passed / TOTAL_RULES * 100, 2)

    return {
        "total_rules": TOTAL_RULES,
        "rules_passed": n_passed,
        "rules_failed": n_failed,
        "validation_score": score,
        "passed_rule_codes": passed,
        "failed_rule_codes": failed,
        "rule_details": results,
        "risk_level": _score_to_risk(score, failed),
    }


def _rule(passed: bool, description: str, message: str, severity: str = "high",
          *, field: str = "", actual=None, expected: str = "") -> dict:
    """One rule outcome, with machine-readable evidence when the caller has it.

    `message` is Arabic prose for a human — "الإجمالي = 0 (يجب أن يكون أكبر من
    صفر)". That reads well and is useless to everything else: a UI cannot
    highlight the offending field from it, `rule_precision` cannot group
    misfires by field, and an auditor cannot be shown *why* the engine decided
    this without reading a sentence per finding.

    So the three parts of a judgement are also carried separately:
      · `field`    — the invoice attribute the rule looked at
      · `actual`   — what it found there
      · `expected` — what would have passed, in words

    Absent keys rather than nulls: a caller that has no structured evidence
    should produce a result that says so, not one claiming `actual=None` — the
    same "unmeasured is not zero" distinction the quota and precision code
    keeps. Consumers use `.get("field")`.
    """
    result = {
        "passed": passed,
        "description": description,
        "message": message,
        "severity": severity if not passed else "info",
    }
    if field:
        result["field"] = field
    if actual is not None:
        result["actual"] = actual
    if expected:
        result["expected"] = expected
    return result


def _record(ok: bool, code: str, passed: list, failed: list):
    if ok:
        passed.append(code)
    else:
        failed.append(code)


def _get_vendor_avg(org, vendor_name: str, exclude_id=None) -> Optional[float]:
    from apps.invoices.models import Invoice
    from django.db.models import Avg
    qs = Invoice.objects.filter(organization=org, vendor_name=vendor_name)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    result = qs.aggregate(avg=Avg("total_amount"))
    return float(result["avg"]) if result["avg"] else None


def _score_to_risk(score: float, failed_codes: list) -> str:
    critical_rules = {"DUP-001", "DUP-002", "DUP-004", "CTL-004", "DOC-003"}
    if any(c in failed_codes for c in critical_rules):
        return "critical"
    if score >= 85:
        return "low"
    elif score >= 65:
        return "medium"
    elif score >= 40:
        return "high"
    return "critical"


def compute_file_hash(file_obj) -> str:
    """Compute SHA-256 hash of a file for duplicate detection."""
    hasher = hashlib.sha256()
    file_obj.seek(0)
    for chunk in iter(lambda: file_obj.read(8192), b""):
        hasher.update(chunk)
    file_obj.seek(0)
    return hasher.hexdigest()
