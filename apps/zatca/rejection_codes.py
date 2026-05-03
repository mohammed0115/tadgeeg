"""
Translatable lookup of the most-frequently-hit ZATCA rejection codes.

This is a curated subset of the published BR-KSA / BR-CO / KSA / Schema
codes — the ones that account for ~90% of rejections in practice. It is
seeded into the ``RejectionCode`` table the first time the dashboard is
opened (idempotent), so a fresh deployment doesn't show empty codes.

Source: ZATCA Phase-2 Detailed Technical Guidelines §10
("Validation rules and KPIs"), version 2.0 (Aug 2023).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("finai.zatca")


# Each entry: (code, category, severity, en_title, ar_title, en_description, ar_description, en_fix, ar_fix)
SEED_CODES: list[tuple] = [
    ("BR-KSA-01", "BR-KSA", "error",
     "Invoice number cannot exceed 50 characters",
     "رقم الفاتورة لا يجب أن يتجاوز 50 خانة",
     "ZATCA limits invoice numbers to 50 alphanumeric chars.",
     "يلزم نظام ZATCA بأن رقم الفاتورة لا يتجاوز 50 حرفاً.",
     "Truncate or reformat the invoice_number field to ≤50 chars.",
     "اختصر أو أعد تنسيق رقم الفاتورة ليصبح 50 حرفاً أو أقل."),

    ("BR-KSA-02", "BR-KSA", "error",
     "Invoice issue date must equal the date in the seller's local time zone",
     "تاريخ إصدار الفاتورة يجب أن يطابق التاريخ المحلي للبائع",
     "IssueDate diverged from the seller's local clock — usually a UTC offset bug.",
     "تاريخ الإصدار اختلف عن التوقيت المحلي للبائع، عادةً ما يكون السبب اختلاف التوقيت العالمي.",
     "Set IssueDate using Asia/Riyadh time, not UTC.",
     "ضبط تاريخ الفاتورة بتوقيت آسيا/الرياض وليس التوقيت العالمي UTC."),

    ("BR-KSA-09", "BR-KSA", "error",
     "Seller VAT registration number must be 15 digits",
     "الرقم الضريبي للبائع يجب أن يكون 15 رقماً",
     "Saudi TRN format is 15 digits, starting and ending with 3.",
     "الرقم الضريبي السعودي يتكون من 15 رقماً يبدأ وينتهي بالرقم 3.",
     "Validate vendor_vat_number with R014 before submitting.",
     "تحقق من رقم ضريبة المورد عبر R014 قبل الإرسال."),

    ("BR-KSA-15", "BR-KSA", "error",
     "Invoice type code must be one of (0100, 0200, 0110, 0220, 0211)",
     "رمز نوع الفاتورة يجب أن يكون أحد القيم المعتمدة",
     "InvoiceTypeCode @name attribute must be a valid ZATCA code.",
     "خاصية InvoiceTypeCode @name يجب أن تكون قيمة معتمدة من الهيئة.",
     "Use 0100 for B2B, 0200 for B2C — the submitter sets this.",
     "استخدم 0100 للفواتير بين الشركات و0200 للفواتير الاستهلاكية."),

    ("BR-KSA-22", "BR-KSA", "error",
     "Previous Invoice Hash must reference the previous invoice in the chain",
     "تجزئة الفاتورة السابقة يجب أن تشير إلى الفاتورة السابقة في السلسلة",
     "PIH chain broken — first invoice should be 32 zero bytes; subsequent invoices use the prior cleared hash.",
     "سلسلة PIH مكسورة — أول فاتورة يجب أن تكون 32 بايت صفرية، وما يليها يستخدم تجزئة الفاتورة المعتمدة السابقة.",
     "Make sure submit_invoice() reads the previous InvoiceSubmission's invoice_hash.",
     "تأكد أن submit_invoice() يقرأ invoice_hash من الفاتورة السابقة."),

    ("BR-CO-04", "BR-CO", "error",
     "Each invoice line must have a tax category and percent",
     "كل بند يجب أن يحتوي على فئة ضريبة ونسبة",
     "Mandatory TaxCategory + Percent missing on at least one line.",
     "فئة الضريبة والنسبة إلزاميتان على كل بند، وكان أحد البنود ينقصه ذلك.",
     "Re-run R009 (VAT rate validity) before submitting.",
     "أعد تشغيل قاعدة R009 (صحة نسبة الضريبة) قبل الإرسال."),

    ("BR-CO-13", "BR-CO", "error",
     "TaxableAmount = LineExtensionAmount × (1 - allowance%)",
     "المبلغ الخاضع للضريبة = صافي البند × (1 - نسبة الخصم)",
     "Line maths inconsistent — ZATCA recomputes and rejects on mismatch.",
     "حسابات البند غير متطابقة — تقوم ZATCA بإعادة الحساب وترفض الفاتورة عند الاختلاف.",
     "Have the line totals match (1 - allowance) × line_extension exactly.",
     "اجعل مجموع البنود يساوي صافي البند مضروباً في (1 - نسبة الخصم)."),

    ("KSA-01",    "KSA",    "error",
     "QR code missing or invalid TLV encoding",
     "رمز QR مفقود أو ترميز TLV غير صحيح",
     "ZATCA could not decode the QR — usually wrong TLV tag length.",
     "تعذر على ZATCA فك ترميز QR — عادةً بسبب طول قيمة tag غير صحيح.",
     "Use apps.zatca.ubl.build_tlv_qr() to generate a compliant QR.",
     "استخدم apps.zatca.ubl.build_tlv_qr لإنتاج رمز QR صحيح."),

    ("KSA-02",    "KSA",    "error",
     "Cryptographic stamp signature failed verification",
     "فشل التحقق من التوقيع الرقمي",
     "The signature in the UBL block doesn't match the document hash with the EGS public key.",
     "التوقيع في كتلة UBL لا يطابق تجزئة المستند باستخدام المفتاح العام للجهاز.",
     "Re-onboard the EGS device or check that the right private key signed the XML.",
     "أعد تسجيل جهاز EGS أو تحقق من استخدام المفتاح الخاص الصحيح في توقيع XML."),

    ("KSA-13",    "KSA",    "error",
     "Cryptographic stamp identifier (CSID) is invalid or expired",
     "معرف الختم الرقمي (CSID) غير صالح أو منتهٍ",
     "The CSID secret used in the Authorization header doesn't match an active cert.",
     "الـ CSID المستخدم في رأس Authorization لا يطابق شهادة فعّالة.",
     "Renew the EGS device — the dashboard's “Renew” button calls renew_egs_device().",
     "جدد جهاز EGS من زر Renew في لوحة الامتثال."),

    ("BR-S-08",   "BR-S",   "error",
     "Standard-rated VAT total must equal sum of line VAT totals",
     "إجمالي الضريبة المعيارية يجب أن يساوي مجموع ضرائب البنود",
     "Header TaxAmount diverged from the lines — usually a rounding bug.",
     "إجمالي الضريبة في رأس الفاتورة لا يساوي مجموع ضرائب البنود — عادة بسبب التقريب.",
     "Re-run R011 (line-item reconciliation) and R009 (VAT rate validity).",
     "أعد تشغيل قاعدتي R011 و R009 قبل الإرسال."),

    ("Schema-01", "Schema", "error",
     "XML does not validate against the UBL 2.1 schema",
     "ملف XML لا يطابق مخطط UBL 2.1",
     "Top-level XML structure has missing or out-of-order elements.",
     "هيكل XML العام به عناصر مفقودة أو ترتيب غير صحيح.",
     "Use apps.zatca.ubl.render_invoice_xml — its element order matches the spec.",
     "استخدم apps.zatca.ubl.render_invoice_xml — ترتيب عناصره مطابق للمواصفة."),
]


def seed_rejection_codes() -> int:
    """Idempotently insert the seed list. Returns the number of new rows
    created (not updated)."""
    from apps.zatca.models import RejectionCode

    created = 0
    for row in SEED_CODES:
        code, category, severity, en_t, ar_t, en_d, ar_d, en_f, ar_f = row
        _, was_created = RejectionCode.objects.update_or_create(
            code=code,
            defaults={
                "category":       category,
                "severity":       severity,
                "title_en":       en_t,
                "title_ar":       ar_t,
                "description_en": en_d,
                "description_ar": ar_d,
                "fix_hint_en":    en_f,
                "fix_hint_ar":    ar_f,
                "is_active":      True,
            },
        )
        if was_created:
            created += 1
    return created


def translate_response_errors(errors: list[dict], lang: str = "en") -> list[dict]:
    """Enrich each error dict in ``errors`` with translated title + fix.

    ``errors`` is the list ZATCA returns under ``validationResults.errorMessages``;
    each entry has ``code`` + ``message``. We look up the code in the
    RejectionCode table and append the translated explanation.
    """
    if not errors:
        return []
    from apps.zatca.models import RejectionCode

    codes = {e.get("code", "") for e in errors if isinstance(e, dict)}
    seen  = {r.code: r for r in RejectionCode.objects.filter(code__in=codes)}

    out: list[dict] = []
    for err in errors:
        if not isinstance(err, dict):
            out.append({"code": "?", "raw": str(err)})
            continue
        code = err.get("code", "")
        match = seen.get(code)
        out.append({
            "code":         code,
            "raw_message":  err.get("message", ""),
            "title":        getattr(match, f"title_{lang}", "") if match else "",
            "description":  getattr(match, f"description_{lang}", "") if match else "",
            "fix_hint":     getattr(match, f"fix_hint_{lang}", "") if match else "",
            "category":     match.category if match else "",
            "severity":     match.severity if match else "error",
        })
    return out
