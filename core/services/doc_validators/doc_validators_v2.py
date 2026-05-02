"""
Document Validators — Phase 3 (15 new doc types)
=================================================
Adds validators for every doc type the catalog covers but that
`doc_validators.py` did not yet implement. Same handcrafted style and same
return shape as the original file (uses the helpers re-exported below).

Each validator returns a dict produced by `_compile(rules)` containing:
    rules_passed, rules_failed, validation_score, risk_level,
    failed_rule_codes, passed_rule_codes, rule_details
which is exactly what `_apply_validation_to_typed` already consumes.
"""
from __future__ import annotations

from datetime import date, timedelta

# Re-use the helpers already defined in the original validators module so we
# stay strictly compatible (same severity weights, same risk thresholds).
from .doc_validators import _rule, _compile, _dec


# ──────────────────────────────────────────────────────────────────────────────
# Helper: safe attribute access (typed-doc rows OR plain dicts both supported)
# ──────────────────────────────────────────────────────────────────────────────
def _get(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _truthy(obj, name) -> bool:
    """A value is truthy when it's present, non-empty, and non-zero."""
    v = _get(obj, name)
    if v is None or v == "":
        return False
    if isinstance(v, (int, float)) and v == 0:
        # Numeric zero is "missing" for required-field rules
        return False
    return bool(v)


def _is_future(d) -> bool:
    """True when `d` parses to a date strictly after today."""
    if d is None:
        return False
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except Exception:
            return False
    try:
        return d > date.today()
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# A. Sales Invoice — SI-001..012
# ══════════════════════════════════════════════════════════════════════════════
def validate_sales_invoice(obj) -> dict:
    rules = []

    rules.append(_rule("SI-001", "رقم فاتورة البيع موجود",
        _truthy(obj, "invoice_number"),
        "رقم فاتورة البيع مفقود",
        "high"))
    rules.append(_rule("SI-002", "تاريخ الفاتورة موجود",
        _truthy(obj, "invoice_date"),
        "تاريخ الفاتورة مفقود",
        "high"))
    rules.append(_rule("SI-003", "تاريخ الفاتورة ليس مستقبلياً غير مبرر",
        not _is_future(_get(obj, "invoice_date")),
        "تاريخ الفاتورة في المستقبل",
        "medium"))
    rules.append(_rule("SI-004", "العميل موجود",
        _truthy(obj, "customer_name"),
        "اسم العميل مفقود",
        "high"))
    rules.append(_rule("SI-005", "الرقم الضريبي للعميل موجود",
        _truthy(obj, "customer_vat_number") or not _get(obj, "customer_is_taxable", True),
        "الرقم الضريبي للعميل مطلوب للعملاء الخاضعين",
        "high"))

    subtotal = _dec(_get(obj, "subtotal", 0))
    vat = _dec(_get(obj, "vat_amount", 0))
    total = _dec(_get(obj, "total_amount", 0))
    rules.append(_rule("SI-006", "الإجمالي = البنود + الضريبة",
        abs((subtotal + vat) - total) < _dec("1.00"),
        f"الإجمالي ({total}) لا يطابق البنود + الضريبة ({subtotal + vat})",
        "critical"))
    expected_vat = subtotal * _dec("0.15")
    rules.append(_rule("SI-007", "VAT محسوبة بنسبة 15%",
        abs(vat - expected_vat) < _dec("1.00") if subtotal else True,
        f"VAT المسجّلة ({vat}) لا تطابق المتوقّع ({expected_vat})",
        "critical"))
    rules.append(_rule("SI-008", "لا تكرار بنفس الرقم والعميل",
        not _get(obj, "is_duplicate", False),
        "فاتورة مكررة بنفس الرقم والعميل",
        "critical"))
    rules.append(_rule("SI-009", "لا تكرار بنفس المبلغ والتاريخ والعميل",
        not _get(obj, "is_amount_duplicate", False),
        "فاتورة مكررة بنفس المبلغ والتاريخ والعميل",
        "high"))
    rules.append(_rule("SI-010", "حالة التحصيل مسجّلة",
        _truthy(obj, "collection_status"),
        "حالة التحصيل غير مسجّلة",
        "medium"))
    rules.append(_rule("SI-011", "العملة مدعومة",
        _get(obj, "currency", "SAR") in ("SAR", "USD", "AED", "EUR", "GBP"),
        "العملة غير مدعومة",
        "medium"))
    rules.append(_rule("SI-012", "المبلغ ضمن نطاق العميل",
        not _get(obj, "amount_unusual", False),
        "مبلغ غير طبيعي مقارنة بسجل العميل",
        "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# B. Purchase Invoice — PI-001..015
# ══════════════════════════════════════════════════════════════════════════════
def validate_purchase_invoice(obj) -> dict:
    rules = []

    rules.append(_rule("PI-001", "رقم فاتورة الشراء موجود",
        _truthy(obj, "invoice_number"),
        "رقم فاتورة الشراء مفقود",
        "high"))
    rules.append(_rule("PI-002", "تاريخ الفاتورة موجود",
        _truthy(obj, "invoice_date"),
        "تاريخ الفاتورة مفقود",
        "high"))
    rules.append(_rule("PI-003", "المورد موجود",
        _truthy(obj, "supplier_name") or _truthy(obj, "vendor_name"),
        "اسم المورد مفقود",
        "high"))
    rules.append(_rule("PI-004", "الرقم الضريبي للمورد موجود",
        _truthy(obj, "supplier_vat_number") or _truthy(obj, "vendor_vat_number"),
        "الرقم الضريبي للمورد مفقود",
        "high"))

    subtotal = _dec(_get(obj, "subtotal", 0))
    vat = _dec(_get(obj, "vat_amount", 0))
    total = _dec(_get(obj, "total_amount", 0))
    rules.append(_rule("PI-005", "الإجمالي = البنود + الضريبة",
        abs((subtotal + vat) - total) < _dec("1.00"),
        f"الإجمالي ({total}) لا يطابق البنود + الضريبة ({subtotal + vat})",
        "critical"))
    expected_vat = subtotal * _dec("0.15")
    rules.append(_rule("PI-006", "VAT محسوبة بشكل صحيح",
        abs(vat - expected_vat) < _dec("1.00") if subtotal else True,
        f"VAT المسجّلة ({vat}) لا تطابق المتوقّع ({expected_vat})",
        "critical"))
    rules.append(_rule("PI-007", "لا تكرار بنفس الرقم والمورد",
        not _get(obj, "is_duplicate", False),
        "فاتورة مكررة بنفس الرقم والمورد",
        "critical"))
    rules.append(_rule("PI-008", "لا تكرار بنفس المبلغ والتاريخ والمورد",
        not _get(obj, "is_amount_duplicate", False),
        "فاتورة مكررة بنفس المبلغ والتاريخ والمورد",
        "high"))
    rules.append(_rule("PI-009", "مرتبطة بأمر شراء",
        _truthy(obj, "po_number") or _truthy(obj, "linked_po_id"),
        "الفاتورة غير مرتبطة بأمر شراء",
        "high"))

    po_amount = _dec(_get(obj, "po_amount", 0))
    rules.append(_rule("PI-010", "مبلغ الفاتورة ≤ مبلغ أمر الشراء",
        po_amount == 0 or total <= po_amount + _dec("1.00"),
        f"مبلغ الفاتورة ({total}) يتجاوز أمر الشراء ({po_amount})",
        "high"))
    rules.append(_rule("PI-011", "مرتبطة بـ GRN عند وجود بضائع",
        not _get(obj, "needs_grn", False) or _truthy(obj, "linked_grn_id"),
        "الفاتورة بحاجة GRN ولم تربط",
        "high"))
    rules.append(_rule("PI-012", "معتمدة قبل الدفع",
        _get(obj, "approval_status") in ("approved",) or not _get(obj, "is_paid", False),
        "تم الدفع قبل الاعتماد",
        "high"))
    rules.append(_rule("PI-013", "لا دفع مزدوج",
        not _get(obj, "is_double_paid", False),
        "تم الدفع مرتين لنفس الفاتورة",
        "critical"))
    rules.append(_rule("PI-014", "مورد جديد عالي القيمة مراجَع",
        not (_get(obj, "is_new_vendor", False) and total > _dec("50000") and not _get(obj, "vendor_reviewed", False)),
        "مورد جديد عالي القيمة بدون مراجعة",
        "high"))
    rules.append(_rule("PI-015", "المبلغ ضمن سجل المورد",
        not _get(obj, "amount_unusual", False),
        "مبلغ غير طبيعي مقارنة بسجل المورد",
        "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# D. Sales Order — SO-001..010
# ══════════════════════════════════════════════════════════════════════════════
def validate_sales_order(obj) -> dict:
    rules = []
    rules.append(_rule("SO-001", "رقم أمر البيع موجود",
        _truthy(obj, "so_number"), "رقم أمر البيع مفقود", "high"))
    rules.append(_rule("SO-002", "العميل موجود",
        _truthy(obj, "customer_name"), "اسم العميل مفقود", "high"))
    rules.append(_rule("SO-003", "تاريخ أمر البيع موجود",
        _truthy(obj, "so_date"), "تاريخ أمر البيع مفقود", "high"))
    line_items = _get(obj, "line_items") or []
    rules.append(_rule("SO-004", "يحتوي على بنود",
        bool(line_items), "أمر البيع لا يحتوي على بنود", "high"))
    rules.append(_rule("SO-005", "الكميات والأسعار صحيحة",
        all((_dec(li.get("qty", 0)) > 0 and _dec(li.get("unit_price", 0)) >= 0) for li in line_items)
        if line_items else True,
        "بنود غير صحيحة (كميات أو أسعار)", "high"))
    rules.append(_rule("SO-006", "لا توجد أوامر مكررة",
        not _get(obj, "is_duplicate", False),
        "أمر بيع مكرر", "high"))

    credit_limit = _dec(_get(obj, "customer_credit_limit", 0))
    outstanding = _dec(_get(obj, "customer_outstanding", 0))
    total = _dec(_get(obj, "total_amount", 0))
    rules.append(_rule("SO-007", "ضمن حد الائتمان",
        credit_limit == 0 or (outstanding + total) <= credit_limit,
        f"العميل تجاوز حد الائتمان ({credit_limit})",
        "high"))
    rules.append(_rule("SO-008", "لا فوترة عند تجاوز الائتمان",
        not (_get(obj, "credit_exceeded", False) and _get(obj, "is_invoiced", False)),
        "تم إصدار فاتورة رغم تجاوز الائتمان", "high"))
    rules.append(_rule("SO-009", "المنتجات / الخدمة متوفّرة",
        _get(obj, "stock_available", True),
        "المنتجات أو الخدمة غير متوفّرة", "medium"))
    rules.append(_rule("SO-010", "الخصم ضمن المسموح",
        _dec(_get(obj, "discount_pct", 0)) <= _dec("30"),
        "خصم غير عادي تجاوز الحد", "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# E. Quotation — QT-001..010
# ══════════════════════════════════════════════════════════════════════════════
def validate_quotation(obj) -> dict:
    rules = []
    rules.append(_rule("QT-001", "رقم العرض موجود",
        _truthy(obj, "quotation_number"), "رقم العرض مفقود", "high"))
    rules.append(_rule("QT-002", "العميل أو المورد موجود",
        _truthy(obj, "party_name") or _truthy(obj, "customer_name") or _truthy(obj, "supplier_name"),
        "الطرف المقابل مفقود", "high"))
    rules.append(_rule("QT-003", "تاريخ العرض موجود",
        _truthy(obj, "quotation_date"), "تاريخ العرض مفقود", "high"))
    rules.append(_rule("QT-004", "تاريخ انتهاء العرض موجود",
        _truthy(obj, "expiry_date"), "تاريخ انتهاء العرض مفقود", "high"))

    expiry = _get(obj, "expiry_date")
    expired = False
    if isinstance(expiry, str):
        try: expired = date.fromisoformat(expiry[:10]) < date.today()
        except Exception: pass
    elif expiry is not None:
        try: expired = expiry < date.today()
        except Exception: pass

    rules.append(_rule("QT-005", "العرض غير منتهٍ عند تحويله لطلب",
        not (_get(obj, "is_converted", False) and (expired or _get(obj, "is_expired", False))),
        "تم تحويل عرض منتهي إلى طلب", "high"))
    line_items = _get(obj, "line_items") or []
    rules.append(_rule("QT-006", "البنود والأسعار موجودة",
        bool(line_items), "العرض لا يحتوي على بنود", "high"))
    rules.append(_rule("QT-007", "الخصم ضمن الحد",
        _dec(_get(obj, "discount_pct", 0)) <= _dec("30"),
        "خصم تجاوز الحد", "high"))
    rules.append(_rule("QT-008", "العملة موجودة",
        _truthy(obj, "currency"), "العملة مفقودة", "medium"))
    rules.append(_rule("QT-009", "لا تكرار بنفس الرقم",
        not _get(obj, "is_duplicate", False),
        "عرض سعر مكرر", "medium"))
    rules.append(_rule("QT-010", "خصم عالٍ معتمد",
        not (_dec(_get(obj, "discount_pct", 0)) > _dec("20") and not _get(obj, "discount_approved", False)),
        "خصم عالٍ بدون موافقة", "high"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# F. Proforma Invoice — PF-001..010
# ══════════════════════════════════════════════════════════════════════════════
def validate_proforma_invoice(obj) -> dict:
    rules = []
    rules.append(_rule("PF-001", "رقم الفاتورة المبدئية موجود",
        _truthy(obj, "proforma_number"), "رقم الفاتورة المبدئية مفقود", "high"))
    rules.append(_rule("PF-002", "العميل موجود",
        _truthy(obj, "customer_name"), "اسم العميل مفقود", "high"))
    rules.append(_rule("PF-003", "التاريخ موجود",
        _truthy(obj, "proforma_date"), "التاريخ مفقود", "high"))
    rules.append(_rule("PF-004", "تاريخ الصلاحية موجود",
        _truthy(obj, "validity_date"), "تاريخ الصلاحية مفقود", "high"))
    rules.append(_rule("PF-005", "ليست مسجّلة كإيراد فعلي",
        not _get(obj, "posted_as_revenue", False),
        "الفاتورة المبدئية مسجّلة كإيراد فعلي", "high"))
    rules.append(_rule("PF-006", "موسومة بوضوح كـ Proforma",
        _get(obj, "is_marked_proforma", True),
        "الفاتورة المبدئية غير موسومة بوضوح", "medium"))

    subtotal = _dec(_get(obj, "subtotal", 0))
    vat = _dec(_get(obj, "vat_amount", 0))
    total = _dec(_get(obj, "total_amount", 0))
    rules.append(_rule("PF-007", "الإجمالي والضريبة محسوبة بشكل صحيح",
        abs((subtotal + vat) - total) < _dec("1.00") if subtotal else True,
        "خطأ حسابي في الإجمالي / الضريبة", "high"))
    rules.append(_rule("PF-008", "لا دفع نهائي بدون فاتورة نهائية",
        not (_get(obj, "is_paid", False) and not _get(obj, "converted_invoice_id")),
        "تم الدفع النهائي بدون فاتورة نهائية", "high"))
    rules.append(_rule("PF-009", "لا تكرار",
        not _get(obj, "is_duplicate", False),
        "فاتورة مبدئية مكرّرة", "medium"))
    rules.append(_rule("PF-010", "تحويلها لفاتورة موثَّق",
        not _get(obj, "should_be_converted", False) or _get(obj, "converted_invoice_id"),
        "العملية تمت ولم تُحوَّل لفاتورة بيع", "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# G. GRN — GRN-001..010
# ══════════════════════════════════════════════════════════════════════════════
def validate_grn(obj) -> dict:
    rules = []
    rules.append(_rule("GRN-001", "رقم سند الاستلام موجود",
        _truthy(obj, "grn_number") or _truthy(obj, "receipt_number"),
        "رقم سند الاستلام مفقود", "high"))
    rules.append(_rule("GRN-002", "مرتبط بأمر شراء",
        _truthy(obj, "po_number") or _truthy(obj, "linked_po_id"),
        "GRN غير مرتبط بأمر شراء", "high"))
    rules.append(_rule("GRN-003", "تاريخ الاستلام موجود",
        _truthy(obj, "receipt_date"), "تاريخ الاستلام مفقود", "high"))
    rules.append(_rule("GRN-004", "المورد موجود",
        _truthy(obj, "supplier_name") or _truthy(obj, "vendor_name"),
        "اسم المورد مفقود", "high"))
    line_items = _get(obj, "line_items") or _get(obj, "items") or []
    rules.append(_rule("GRN-005", "البنود المستلمة موجودة",
        bool(line_items), "لا توجد بنود مستلمة", "high"))
    over_qty = any(_dec(li.get("qty_received", 0)) > _dec(li.get("qty_ordered", 0)) for li in line_items if isinstance(li, dict))
    rules.append(_rule("GRN-006", "الكمية المستلمة ≤ المطلوبة",
        not over_qty, "الكمية المستلمة تجاوزت المطلوبة في PO", "high"))
    rules.append(_rule("GRN-007", "لا فروقات كمية",
        not _get(obj, "has_quantity_variance", False),
        "فرق كمية بين PO و GRN", "medium"))
    rules.append(_rule("GRN-008", "لا تكرار",
        not _get(obj, "is_duplicate", False),
        "GRN مكرر", "high"))
    rules.append(_rule("GRN-009", "فاتورة بدون GRN عند اللزوم",
        not (_get(obj, "needs_grn_for_invoice", False) and not _get(obj, "linked_invoice_id")),
        "فاتورة بحاجة GRN ولم يُسجَّل", "high"))
    rules.append(_rule("GRN-010", "حالة الفحص / القبول مسجّلة",
        _truthy(obj, "inspection_status") or _truthy(obj, "acceptance_status"),
        "حالة الفحص أو القبول غير مسجّلة", "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# H. Payment Voucher — PV-001..012
# ══════════════════════════════════════════════════════════════════════════════
def validate_payment_voucher(obj) -> dict:
    rules = []
    rules.append(_rule("PV-001", "رقم سند الدفع موجود",
        _truthy(obj, "payment_number") or _truthy(obj, "voucher_number"),
        "رقم سند الدفع مفقود", "high"))
    rules.append(_rule("PV-002", "المستفيد موجود",
        _truthy(obj, "payee_name"),
        "المستفيد مفقود", "high"))
    amount = _dec(_get(obj, "amount", 0))
    rules.append(_rule("PV-003", "المبلغ > 0",
        amount > 0, "المبلغ صفر أو سالب", "critical"))
    rules.append(_rule("PV-004", "طريقة الدفع موجودة",
        _truthy(obj, "payment_method"),
        "طريقة الدفع مفقودة", "high"))
    rules.append(_rule("PV-005", "تاريخ الدفع موجود",
        _truthy(obj, "payment_date"),
        "تاريخ الدفع مفقود", "high"))
    rules.append(_rule("PV-006", "مرتبط بفاتورة أو سبب",
        _truthy(obj, "linked_invoice_id") or _truthy(obj, "linked_invoice_number") or _truthy(obj, "reason"),
        "الدفع غير مرتبط بفاتورة أو سبب", "high"))
    rules.append(_rule("PV-007", "لا دفع مزدوج",
        not _get(obj, "is_duplicate", False) and not _get(obj, "is_double_paid", False),
        "دفع مزدوج لنفس الفاتورة", "critical"))
    rules.append(_rule("PV-008", "معتمد",
        _get(obj, "approval_status") == "approved",
        "الدفع غير معتمد", "critical"))
    cash_threshold = _dec("10000")
    rules.append(_rule("PV-009", "الدفع النقدي فوق الحد معتمد",
        not (_get(obj, "payment_method") == "cash" and amount > cash_threshold and _get(obj, "approval_status") != "approved"),
        f"دفع نقدي > {cash_threshold} ريال بدون موافقة", "high"))
    rules.append(_rule("PV-010", "مطابق لكشف البنك",
        _get(obj, "bank_match_id") is not None or _get(obj, "is_reconciled", False) or _get(obj, "payment_method") == "cash",
        "الدفع غير مطابق لكشف البنك", "high"))
    rules.append(_rule("PV-011", "مستفيد جديد عالي القيمة مراجَع",
        not (_get(obj, "is_new_payee", False) and amount > _dec("50000") and not _get(obj, "payee_reviewed", False)),
        "مستفيد جديد عالي القيمة بدون مراجعة", "high"))
    rules.append(_rule("PV-012", "لا تقسيم مشبوه",
        not _get(obj, "split_payment_detected", False),
        "اكتُشف تقسيم دفعات لتجاوز الموافقة", "critical"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# I. Receipt Voucher — RV-001..010
# ══════════════════════════════════════════════════════════════════════════════
def validate_receipt_voucher(obj) -> dict:
    rules = []
    rules.append(_rule("RV-001", "رقم سند القبض موجود",
        _truthy(obj, "receipt_number"), "رقم سند القبض مفقود", "high"))
    rules.append(_rule("RV-002", "الدافع موجود",
        _truthy(obj, "payer_name"),
        "الدافع غير مسجّل", "high"))
    amount = _dec(_get(obj, "amount", 0))
    rules.append(_rule("RV-003", "المبلغ > 0",
        amount > 0, "المبلغ صفر أو سالب", "critical"))
    rules.append(_rule("RV-004", "طريقة القبض موجودة",
        _truthy(obj, "receipt_method"),
        "طريقة القبض مفقودة", "high"))
    rules.append(_rule("RV-005", "تاريخ القبض موجود",
        _truthy(obj, "receipt_date"), "تاريخ القبض مفقود", "high"))
    rules.append(_rule("RV-006", "مرتبط بفاتورة أو سبب",
        _truthy(obj, "linked_invoice_id") or _truthy(obj, "linked_invoice_number") or _truthy(obj, "reason"),
        "القبض غير مرتبط بفاتورة أو سبب", "high"))
    rules.append(_rule("RV-007", "لا تكرار",
        not _get(obj, "is_duplicate", False),
        "سند قبض مكرّر", "high"))
    rules.append(_rule("RV-008", "مطابق لكشف البنك",
        _get(obj, "bank_match_id") is not None or _get(obj, "is_reconciled", False) or _get(obj, "receipt_method") == "cash",
        "القبض غير مطابق لكشف البنك", "high"))
    variance = abs(_dec(_get(obj, "variance_vs_invoice", 0)))
    rules.append(_rule("RV-009", "بدون فرق غير مبرر مع الفاتورة",
        variance < _dec("1.00") or _truthy(obj, "variance_reason"),
        f"فرق تحصيل غير مبرر ({variance})", "medium"))
    rules.append(_rule("RV-010", "بدون تحصيل غير مبرر",
        not _get(obj, "is_unjustified", False),
        "تحصيل غير مبرر", "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# J. Cash Voucher — CV-001..010
# ══════════════════════════════════════════════════════════════════════════════
def validate_cash_voucher(obj) -> dict:
    rules = []
    rules.append(_rule("CV-001", "رقم السند النقدي موجود",
        _truthy(obj, "voucher_number"), "رقم السند النقدي مفقود", "high"))
    rules.append(_rule("CV-002", "نوع الحركة موجود",
        _get(obj, "movement_type") in ("in", "out"),
        "نوع الحركة (قبض/صرف) مفقود", "high"))
    amount = _dec(_get(obj, "amount", 0))
    rules.append(_rule("CV-003", "المبلغ > 0",
        amount > 0, "المبلغ صفر أو سالب", "critical"))
    rules.append(_rule("CV-004", "التاريخ موجود",
        _truthy(obj, "voucher_date"), "التاريخ مفقود", "high"))
    rules.append(_rule("CV-005", "السبب موجود",
        _truthy(obj, "reason"),
        "سبب الحركة غير مسجّل", "high"))
    rules.append(_rule("CV-006", "المرفق موجود",
        _get(obj, "has_attachment", False),
        "المرفق أو الإيصال مفقود", "high"))
    threshold = _dec("5000")
    rules.append(_rule("CV-007", "فوق الحد معتمد",
        not (amount > threshold and _get(obj, "approval_status") != "approved"),
        f"حركة نقدية > {threshold} ريال بدون موافقة", "high"))
    rules.append(_rule("CV-008", "لا تكرار",
        not _get(obj, "is_duplicate", False),
        "حركة نقدية مكرّرة", "high"))
    rules.append(_rule("CV-009", "مصروف غير عادي",
        not _get(obj, "is_unusual", False),
        "مصروف نقدي غير عادي", "medium"))
    cb = _get(obj, "cashbox_balance_after")
    rules.append(_rule("CV-010", "رصيد الصندوق منطقي",
        cb is None or _dec(cb) >= 0,
        "رصيد الصندوق سالب بعد الحركة", "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# L. Journal Entry — JE-001..014
# ══════════════════════════════════════════════════════════════════════════════
def validate_journal_entry(obj) -> dict:
    rules = []
    rules.append(_rule("JE-001", "رقم القيد موجود",
        _truthy(obj, "entry_number"), "رقم القيد مفقود", "high"))
    rules.append(_rule("JE-002", "تاريخ القيد موجود",
        _truthy(obj, "entry_date"), "تاريخ القيد مفقود", "high"))
    rules.append(_rule("JE-003", "الوصف موجود",
        _truthy(obj, "description"), "الوصف مفقود", "medium"))

    lines = _get(obj, "lines") or []
    rules.append(_rule("JE-004", "سطران على الأقل",
        len(lines) >= 2, "القيد يحتوي على أقل من سطرين", "critical"))
    rules.append(_rule("JE-005", "كل سطر له حساب صحيح",
        all(li.get("account_code") for li in lines if isinstance(li, dict)) if lines else True,
        "بعض السطور بدون حساب", "critical"))

    total_debit = _dec(_get(obj, "total_debit", 0))
    total_credit = _dec(_get(obj, "total_credit", 0))
    rules.append(_rule("JE-006", "المدين = الدائن",
        abs(total_debit - total_credit) < _dec("0.01"),
        f"قيد غير متوازن: مدين={total_debit}, دائن={total_credit}", "critical"))
    rules.append(_rule("JE-007", "لا قيد غير متوازن",
        abs(total_debit - total_credit) < _dec("0.01"),
        "قيد غير متوازن", "critical"))
    rules.append(_rule("JE-008", "لا تكرار",
        not _get(obj, "is_duplicate", False),
        "قيد مكرّر", "high"))
    rules.append(_rule("JE-009", "ليس مستقبلياً غير مبرر",
        not _is_future(_get(obj, "entry_date")),
        "تاريخ القيد في المستقبل", "medium"))
    rules.append(_rule("JE-010", "الحسابات في دليل الحسابات",
        not _get(obj, "has_invalid_accounts", False),
        "حسابات غير موجودة في دليل الحسابات", "high"))
    rules.append(_rule("JE-011", "بدون مبلغ غير طبيعي",
        not _get(obj, "amount_unusual", False),
        "قيد بمبلغ غير طبيعي", "medium"))
    rules.append(_rule("JE-012", "قيد يدوي عالي المخاطر",
        not (_get(obj, "is_manual", False) and _get(obj, "is_high_risk", False)),
        "قيد يدوي عالي المخاطر", "high"))
    rules.append(_rule("JE-013", "ليس في نهاية الفترة",
        not _get(obj, "is_period_end", False),
        "قيد في نهاية الفترة المالية", "medium"))
    rules.append(_rule("JE-014", "المرفق موجود إن لزم",
        not _get(obj, "requires_attachment", False) or _get(obj, "has_attachment", False),
        "قيد بدون مرفق رغم اللزوم", "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# M. General Ledger — GL-001..012
# ══════════════════════════════════════════════════════════════════════════════
def validate_general_ledger(obj) -> dict:
    rules = []
    accounts = _get(obj, "accounts") or []
    rules.append(_rule("GL-001", "حسابات موجودة",
        bool(accounts), "لا توجد حسابات في دفتر الأستاذ", "high"))
    rules.append(_rule("GL-002", "أرصدة افتتاحية موجودة",
        all("opening" in a for a in accounts) if accounts else False,
        "بعض الحسابات بدون رصيد افتتاحي", "high"))
    rules.append(_rule("GL-003", "حركات موجودة",
        _get(obj, "movements_count", 0) > 0,
        "لا توجد حركات", "medium"))

    total_debit = _dec(_get(obj, "total_debit", 0))
    total_credit = _dec(_get(obj, "total_credit", 0))
    rules.append(_rule("GL-004", "متوازن",
        abs(total_debit - total_credit) < _dec("1.00"),
        f"غير متوازن: مدين={total_debit}, دائن={total_credit}", "critical"))
    rules.append(_rule("GL-005", "كل حركة مرتبطة بقيد",
        not _get(obj, "has_orphan_movements", False),
        "حركات بدون قيود يومية", "high"))
    rules.append(_rule("GL-006", "بدون حركات يتيمة",
        not _get(obj, "has_orphan_movements", False),
        "حركات بدون قيود يومية", "high"))
    rules.append(_rule("GL-007", "أرصدة طبيعية",
        not _get(obj, "abnormal_balances", []),
        "حسابات بأرصدة غير طبيعية", "high"))
    rules.append(_rule("GL-008", "بدون فروقات Rollforward",
        not _get(obj, "rollforward_variances", []),
        "فروقات في الترحيل بين الفترات", "high"))
    rules.append(_rule("GL-009", "بدون حركات مكررة",
        not _get(obj, "duplicate_movements", []),
        "حركات مكرّرة", "medium"))
    rules.append(_rule("GL-010", "حسابات خاملة بدون حركة",
        not _get(obj, "dormant_with_activity", []),
        "حسابات خاملة عليها حركة", "medium"))
    rules.append(_rule("GL-011", "تغيرات طبيعية",
        not _get(obj, "abnormal_changes", []),
        "تغيرات غير طبيعية في الحسابات", "medium"))
    rules.append(_rule("GL-012", "Benford طبيعي",
        not _get(obj, "benford_anomaly", False),
        "شذوذ في توزيع بنفورد", "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# N. Ledger — LDG-001..010
# ══════════════════════════════════════════════════════════════════════════════
def validate_ledger(obj) -> dict:
    rules = []
    rules.append(_rule("LDG-001", "رقم الحساب موجود",
        _truthy(obj, "account_number"), "رقم الحساب مفقود", "high"))
    rules.append(_rule("LDG-002", "اسم الحساب موجود",
        _truthy(obj, "account_name"), "اسم الحساب مفقود", "medium"))
    opening = _get(obj, "opening_balance")
    rules.append(_rule("LDG-003", "الرصيد الافتتاحي موجود",
        opening is not None, "الرصيد الافتتاحي مفقود", "high"))

    movements = _get(obj, "movements") or []
    rules.append(_rule("LDG-004", "كل حركة لها تاريخ ووصف ومبلغ",
        all(m.get("date") and m.get("description") and (m.get("debit") or m.get("credit"))
            for m in movements if isinstance(m, dict)) if movements else True,
        "بعض الحركات بدون تاريخ/وصف/مبلغ", "high"))

    op = _dec(opening or 0)
    debit = _dec(_get(obj, "total_debit", 0))
    credit = _dec(_get(obj, "total_credit", 0))
    closing = _dec(_get(obj, "closing_balance", 0))
    expected = op + debit - credit
    rules.append(_rule("LDG-005", "الرصيد الختامي صحيح",
        abs(closing - expected) < _dec("1.00"),
        f"الرصيد الختامي ({closing}) لا يطابق المتوقّع ({expected})", "critical"))
    rules.append(_rule("LDG-006", "كل حركة لها مرجع",
        all(m.get("ref") or m.get("reference") for m in movements if isinstance(m, dict)) if movements else True,
        "حركات بدون مرجع", "medium"))
    rules.append(_rule("LDG-007", "بدون حركات مكرّرة",
        not _get(obj, "has_duplicate_movements", False),
        "حركات مكرّرة", "medium"))
    rules.append(_rule("LDG-008", "بدون حركات غير طبيعية",
        not _get(obj, "has_unusual_movements", False),
        "حركات غير طبيعية", "medium"))
    rules.append(_rule("LDG-009", "الحركات مرتبطة بقيود",
        not _get(obj, "has_orphan_movements", False),
        "حركات بدون قيود يومية", "high"))
    rules.append(_rule("LDG-010", "بدون أرصدة سالبة غير مبررة",
        closing >= 0 or _get(obj, "negative_allowed", False),
        f"رصيد ختامي سالب ({closing}) غير مبرر", "high"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# O. Contract — CTR-001..013
# ══════════════════════════════════════════════════════════════════════════════
def validate_contract(obj) -> dict:
    rules = []
    rules.append(_rule("CTR-001", "رقم العقد موجود",
        _truthy(obj, "contract_number"), "رقم العقد مفقود", "high"))
    rules.append(_rule("CTR-002", "أطراف العقد موجودة",
        _truthy(obj, "party_a") and _truthy(obj, "party_b"),
        "أطراف العقد غير مسجّلة", "high"))
    rules.append(_rule("CTR-003", "تاريخ البداية موجود",
        _truthy(obj, "start_date"), "تاريخ البداية مفقود", "high"))
    rules.append(_rule("CTR-004", "تاريخ النهاية موجود",
        _truthy(obj, "end_date"), "تاريخ النهاية مفقود", "high"))
    value = _dec(_get(obj, "contract_value", 0))
    rules.append(_rule("CTR-005", "قيمة العقد موجودة",
        value > 0, "قيمة العقد غير محدّدة", "high"))
    rules.append(_rule("CTR-006", "العقد موقّع",
        _get(obj, "is_signed", False),
        "العقد غير موقّع", "critical"))

    end = _get(obj, "end_date")
    expired = False
    if isinstance(end, str):
        try: expired = date.fromisoformat(end[:10]) < date.today()
        except Exception: pass
    elif end is not None:
        try: expired = end < date.today()
        except Exception: pass

    rules.append(_rule("CTR-007", "العقد المنتهي بدون فواتير جديدة",
        not (expired and _get(obj, "has_new_invoices", False)),
        "تم إصدار فواتير على عقد منتهي", "high"))
    rules.append(_rule("CTR-008", "الفاتورة داخل مدة العقد",
        not _get(obj, "has_out_of_period_invoice", False),
        "فاتورة خارج مدة العقد", "high"))

    invoiced = _dec(_get(obj, "invoiced_to_date", 0))
    rules.append(_rule("CTR-009", "إجمالي الفواتير ≤ قيمة العقد",
        invoiced <= value + _dec("1.00") or value == 0,
        f"إجمالي الفواتير ({invoiced}) تجاوز قيمة العقد ({value})", "high"))
    rules.append(_rule("CTR-010", "شروط الدفع واضحة",
        _truthy(obj, "payment_terms"),
        "شروط الدفع غير محدّدة", "medium"))
    rules.append(_rule("CTR-011", "مرفق العقد موجود",
        _get(obj, "has_attachment", False),
        "العقد بدون مرفق", "medium"))
    mods = _get(obj, "value_modifications") or []
    unappr = [m for m in mods if isinstance(m, dict) and not m.get("approver")]
    rules.append(_rule("CTR-012", "تعديل القيمة معتمد",
        not unappr,
        "تعديل قيمة العقد بدون موافقة", "high"))
    rules.append(_rule("CTR-013", "الطرف المقابل يطابق الفاتورة",
        not _get(obj, "counterparty_mismatch", False),
        "مورد أو عميل غير مطابق لأطراف العقد", "high"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# S. Supplier Statement — SS-001..012
# ══════════════════════════════════════════════════════════════════════════════
def validate_supplier_statement(obj) -> dict:
    rules = []
    rules.append(_rule("SS-001", "اسم المورد موجود",
        _truthy(obj, "supplier_name"), "اسم المورد مفقود", "high"))
    rules.append(_rule("SS-002", "رقم المورد أو الضريبي موجود",
        _truthy(obj, "supplier_id") or _truthy(obj, "supplier_vat_number"),
        "رقم المورد مفقود", "high"))
    rules.append(_rule("SS-003", "الفترة موجودة",
        _truthy(obj, "period_from") and _truthy(obj, "period_to"),
        "فترة الكشف مفقودة", "high"))
    opening = _get(obj, "opening_balance")
    rules.append(_rule("SS-004", "الرصيد الافتتاحي موجود",
        opening is not None, "الرصيد الافتتاحي مفقود", "high"))

    movements = _get(obj, "movements") or []
    rules.append(_rule("SS-005", "حركات موجودة",
        bool(movements), "لا توجد حركات", "medium"))

    op = _dec(opening or 0)
    invoiced = _dec(_get(obj, "total_invoiced", 0))
    paid = _dec(_get(obj, "total_paid", 0))
    closing = _dec(_get(obj, "closing_balance", 0))
    expected = op + invoiced - paid
    rules.append(_rule("SS-006", "الرصيد الختامي صحيح",
        abs(closing - expected) < _dec("1.00"),
        f"الرصيد الختامي ({closing}) لا يطابق المتوقّع ({expected})", "critical"))
    rules.append(_rule("SS-007", "فواتير المورد مطابقة",
        _get(obj, "invoices_matched", 0) == len(movements) or _get(obj, "match_rate", 1.0) >= 0.95,
        "فواتير المورد لا تطابق النظام", "high"))
    rules.append(_rule("SS-008", "المدفوعات مطابقة",
        _get(obj, "payments_match_rate", 1.0) >= 0.95,
        "المدفوعات لا تطابق سندات الدفع", "high"))
    missing_inv = _get(obj, "invoices_missing_in_system") or []
    rules.append(_rule("SS-009", "بدون فواتير غير مسجّلة",
        not missing_inv, "فواتير في كشف المورد غير موجودة في النظام", "high"))
    missing_pay = _get(obj, "payments_missing_on_statement") or []
    rules.append(_rule("SS-010", "بدون مدفوعات غير ظاهرة",
        not missing_pay, "مدفوعات في النظام غير موجودة في كشف المورد", "high"))

    variance = abs(_dec(_get(obj, "balance_variance", 0)))
    rules.append(_rule("SS-011", "بدون فروقات رصيد",
        variance < _dec("1.00"), f"فرق رصيد ({variance})", "high"))
    rules.append(_rule("SS-012", "بدون معاملات مكررة",
        _get(obj, "duplicate_count", 0) == 0,
        "معاملات مكرّرة", "medium"))

    return _compile(rules)


# ══════════════════════════════════════════════════════════════════════════════
# T. Customer Statement — CS-001..012
# ══════════════════════════════════════════════════════════════════════════════
def validate_customer_statement(obj) -> dict:
    rules = []
    rules.append(_rule("CS-001", "اسم العميل موجود",
        _truthy(obj, "customer_name"), "اسم العميل مفقود", "high"))
    rules.append(_rule("CS-002", "رقم العميل أو الضريبي موجود",
        _truthy(obj, "customer_id") or _truthy(obj, "customer_vat_number"),
        "رقم العميل مفقود", "high"))
    rules.append(_rule("CS-003", "الفترة موجودة",
        _truthy(obj, "period_from") and _truthy(obj, "period_to"),
        "فترة الكشف مفقودة", "high"))
    opening = _get(obj, "opening_balance")
    rules.append(_rule("CS-004", "الرصيد الافتتاحي موجود",
        opening is not None, "الرصيد الافتتاحي مفقود", "high"))

    movements = _get(obj, "movements") or []
    rules.append(_rule("CS-005", "حركات موجودة",
        bool(movements), "لا توجد حركات", "medium"))

    op = _dec(opening or 0)
    invoiced = _dec(_get(obj, "total_invoiced", 0))
    received = _dec(_get(obj, "total_received", 0))
    closing = _dec(_get(obj, "closing_balance", 0))
    expected = op + invoiced - received
    rules.append(_rule("CS-006", "الرصيد الختامي صحيح",
        abs(closing - expected) < _dec("1.00"),
        f"الرصيد الختامي ({closing}) لا يطابق المتوقّع ({expected})", "critical"))
    rules.append(_rule("CS-007", "فواتير العميل مطابقة",
        _get(obj, "invoices_match_rate", 1.0) >= 0.95,
        "فواتير العميل لا تطابق النظام", "high"))
    rules.append(_rule("CS-008", "المقبوضات مطابقة",
        _get(obj, "receipts_match_rate", 1.0) >= 0.95,
        "المقبوضات لا تطابق سندات القبض", "high"))
    missing_inv = _get(obj, "invoices_missing_in_system") or []
    rules.append(_rule("CS-009", "بدون فواتير غير مسجّلة",
        not missing_inv, "فواتير في كشف العميل غير موجودة في النظام", "high"))
    missing_rcpt = _get(obj, "receipts_missing_on_statement") or []
    rules.append(_rule("CS-010", "بدون مقبوضات غير ظاهرة",
        not missing_rcpt, "مقبوضات في النظام غير موجودة في كشف العميل", "high"))

    variance = abs(_dec(_get(obj, "balance_variance", 0)))
    rules.append(_rule("CS-011", "بدون فروقات رصيد",
        variance < _dec("1.00"), f"فرق رصيد ({variance})", "high"))
    rules.append(_rule("CS-012", "بدون معاملات مكررة",
        _get(obj, "duplicate_count", 0) == 0,
        "معاملات مكرّرة", "medium"))

    return _compile(rules)


# ──────────────────────────────────────────────────────────────────────────────
# Public router — to be merged into doc_validators.VALIDATORS
# ──────────────────────────────────────────────────────────────────────────────
VALIDATORS_V2 = {
    "sales_invoice":      validate_sales_invoice,
    "purchase_invoice":   validate_purchase_invoice,
    "sales_order":        validate_sales_order,
    "quotation":          validate_quotation,
    "proforma_invoice":   validate_proforma_invoice,
    "grn":                validate_grn,
    "payment_voucher":    validate_payment_voucher,
    "receipt_voucher":    validate_receipt_voucher,
    "cash_voucher":       validate_cash_voucher,
    "journal_entry":      validate_journal_entry,
    "general_ledger":     validate_general_ledger,
    "ledger":             validate_ledger,
    "contract":           validate_contract,
    "supplier_statement": validate_supplier_statement,
    "customer_statement": validate_customer_statement,
}
