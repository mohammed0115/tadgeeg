"""Unified document-type audit adapter.

Each non-invoice document type (PurchaseOrder, BankStatement, Payroll, …)
already stores its own validation results directly on the document row:
    failed_rule_codes  — list[str] of failed rule codes
    rules_failed       — int
    rules_passed       — int
    validation_score   — float (0-100)
    risk_level         — low | medium | high | critical
    validation_details — dict (optional)

The earlier `XxxValidation` tables turned out to be a separate, mostly empty,
legacy schema. This adapter reads the live values straight from the document
model so the report reflects what the user actually sees on the document
detail page.

Returns the same shape the report view consumes from the invoice path so
downstream code (`_build_high_risk_violations`, `findings_service`) needs
no per-type branching.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

# ─── Rule catalog ───────────────────────────────────────────────────────────
# Auto-extracted from core/services/doc_validators/doc_validators.py.
# Format: code -> (title_ar, severity)

DOC_RULES: dict[str, tuple[str, str]] = {
    # Purchase Order — PO-001..PO-010
    "PO-001": ("رقم أمر الشراء موجود",                                 "high"),
    "PO-002": ("تاريخ أمر الشراء صحيح",                                "high"),
    "PO-003": ("اسم المورد موجود",                                     "high"),
    "PO-004": ("رقم ضريبي للمورد صحيح",                                "critical"),
    "PO-005": ("حساب ضريبة القيمة المضافة صحيح (15%)",                 "critical"),
    "PO-006": ("الإجمالي = المبلغ قبل الضريبة + الضريبة",              "critical"),
    "PO-007": ("المبلغ ضمن الميزانية المعتمدة",                        "high"),
    "PO-008": ("يوجد موافق على الأمر",                                 "high"),
    "PO-009": ("لا يوجد فرق في الأسعار مع الفاتورة",                   "high"),
    "PO-010": ("مركز التكلفة موجود",                                   "medium"),
    # Bank Statement — BNK-001..BNK-009
    "BNK-001": ("تطابق رصيد الختام",                                   "critical"),
    "BNK-002": ("لا توجد معاملات كبيرة غير مبررة",                     "high"),
    "BNK-003": ("لا توجد معاملات مكررة",                               "critical"),
    "BNK-004": ("توزيع المبالغ يتوافق مع قانون بنفورد",                "high"),
    "BNK-005": ("نسبة المبالغ المدوّرة معقولة",                        "medium"),
    "BNK-006": ("لا توجد معاملات في عطل نهاية الأسبوع",                "medium"),
    "BNK-007": ("رقم الحساب المصرفي موجود",                            "high"),
    "BNK-008": ("فترة الكشف محددة وصحيحة",                             "high"),
    "BNK-009": ("رقم IBAN سعودي صحيح",                                 "medium"),
    # Payroll — PAY-001..PAY-009
    "PAY-001": ("لا يوجد تكرار في أرقام الهوية الوطنية",               "critical"),
    "PAY-002": ("لا يوجد موظفون وهميون محتملون",                       "critical"),
    "PAY-003": ("حساب صافي الراتب صحيح (إجمالي - الخصومات)",           "critical"),
    "PAY-004": ("التأمينات الاجتماعية (GOSI) موجودة",                  "high"),
    "PAY-005": ("لا توجد زيادات راتب مفاجئة (>30%)",                   "high"),
    "PAY-006": ("جميع الموظفين لديهم حسابات بنكية",                    "medium"),
    "PAY-007": ("فترة كشف الرواتب محددة",                              "medium"),
    "PAY-008": ("الإجمالي يتطابق مع مجموع السجلات",                    "high"),
    "PAY-009": ("عدد الموظفين متسق",                                   "medium"),
    # Expense Report — EXP-001..EXP-008
    "EXP-001": ("جميع المصروفات مدعومة بإيصالات",                      "high"),
    "EXP-002": ("لا يوجد تكرار في المطالبات",                          "critical"),
    "EXP-003": ("المصروفات ضمن حدود السياسة",                          "medium"),
    "EXP-004": ("التقرير معتمد من مسؤول",                              "high"),
    "EXP-005": ("لا يوجد تقسيم مشبوه للمصروفات",                       "high"),
    "EXP-006": ("التواريخ محددة وصحيحة",                               "medium"),
    "EXP-007": ("حساب ضريبة القيمة المضافة صحيح",                      "medium"),
    "EXP-008": ("إجمالي المطالبة يتطابق مع مجموع السجلات",             "high"),
    # VAT Return — VATR-001..VATR-008
    "VATR-001": ("الرقم الضريبي للممول صحيح",                          "critical"),
    "VATR-002": ("ضريبة المخرجات = المبيعات × 15%",                    "critical"),
    "VATR-003": ("ضريبة المدخلات قيمة موجبة",                          "high"),
    "VATR-004": ("صافي الضريبة المستحقة = مخرجات - مدخلات",            "critical"),
    "VATR-005": ("لا يوجد فارق في ضريبة المخرجات",                     "high"),
    "VATR-006": ("لا يوجد فارق في ضريبة المدخلات",                     "high"),
    "VATR-007": ("الإقرار مقدَّم في الموعد المحدد",                    "high"),
    "VATR-008": ("فترة الإقرار محددة",                                 "medium"),
    # Fixed Asset — AST-001..AST-009
    "AST-001": ("لا توجد قيم دفترية سالبة",                            "critical"),
    "AST-002": ("الإهلاك المتراكم لا يتجاوز التكلفة الأصلية",          "critical"),
    "AST-003": ("معدلات الإهلاك ضمن النطاق المقبول",                   "high"),
    "AST-004": ("لا تكرار في أرقام الأصول",                            "high"),
    "AST-005": ("جميع الأصول لها أرقام تعريفية",                       "medium"),
    "AST-006": ("القيمة الدفترية = التكلفة - الإهلاك المتراكم",        "critical"),
    "AST-007": ("العمر الإنتاجي للأصول معقول (3-50 سنة)",              "medium"),
    "AST-008": ("إجمالي التكاليف متسق مع السجلات",                     "high"),
    "AST-009": ("تواريخ الشراء صحيحة وغير مستقبلية",                   "medium"),
    "AST-010": ("الأراضي لا تخضع للإهلاك (IAS 16.58)",                  "critical"),
    "AST-011": ("العمر الإنتاجي ضمن النطاق الموصى به للفئة",            "high"),
    "AST-012": ("اتساق طريقة الإهلاك داخل كل فئة",                     "high"),
    "AST-013": ("حساب الإهلاك السنوي صحيح (القسط الثابت)",             "high"),
    "AST-014": ("حد الرسملة محترم (لا أصول < 1000 ر.س)",                "medium"),
    "AST-015": ("تصنيف الأصول واضح ومعبَّأ",                            "medium"),
    "AST-016": ("الأصول المُهلكة بالكامل قيمتها الدفترية صفر",          "critical"),
    "AST-017": ("عدد الأصول المُعلَن يطابق السجلات",                    "medium"),
    # Sales Receipt — REC-001..REC-008
    "REC-001": ("رقم الإيصال موجود",                                   "high"),
    "REC-002": ("تاريخ الإيصال صحيح",                                  "high"),
    "REC-003": ("معدل ضريبة القيمة المضافة = 15%",                     "critical"),
    "REC-004": ("مبلغ الضريبة = المبلغ قبل الضريبة × 15%",             "critical"),
    "REC-005": ("رمز QR الزاتكا موجود",                                "high"),
    "REC-006": ("رمز QR صحيح ويطابق بيانات الإيصال",                   "critical"),
    "REC-007": ("الإيصال غير مكرر",                                    "critical"),
    "REC-008": ("الرقم الضريبي للبائع موجود",                          "critical"),
}


@dataclass
class _DocSpec:
    """How to query and present one non-invoice document type."""
    model_path:       str   # "apps.documents.models:PurchaseOrder"
    number_field:     str   # the field used as the human-readable identifier
    amount_fields:    tuple  # candidate field names for "total amount" (first non-zero wins)
    vendor_fields:    tuple  # candidate field names for vendor/owner/party display
    date_field:       str | None


_SPECS: dict[str, _DocSpec] = {
    # Original 7 types
    "purchase_order": _DocSpec(
        model_path="apps.documents.models:PurchaseOrder",
        number_field="po_number",
        amount_fields=("total_amount", "subtotal"),
        vendor_fields=("vendor_name",),
        date_field="po_date",
    ),
    "bank_statement": _DocSpec(
        model_path="apps.documents.models:BankStatement",
        number_field="account_number",
        amount_fields=("closing_balance", "total_credits"),
        vendor_fields=("bank_name", "account_name"),
        date_field="statement_period_to",
    ),
    "payroll": _DocSpec(
        model_path="apps.documents.models:PayrollSheet",
        number_field="payroll_period_from",
        amount_fields=("total_gross_salary", "total_net_salary"),
        vendor_fields=("company_name", "department"),
        date_field="payment_date",
    ),
    "expense_report": _DocSpec(
        model_path="apps.documents.models:ExpenseReport",
        number_field="report_number",
        amount_fields=("total_claimed",),
        vendor_fields=("employee_name", "department"),
        date_field="submitted_date",
    ),
    "vat_return": _DocSpec(
        model_path="apps.documents.models:VATReturn",
        number_field="vat_number",
        amount_fields=("net_vat_payable", "output_vat"),
        vendor_fields=("taxpayer_name",),
        date_field="filing_date",
    ),
    "fixed_asset": _DocSpec(
        model_path="apps.documents.models:FixedAsset",
        number_field="fiscal_year",
        amount_fields=("total_cost", "total_book_value"),
        vendor_fields=("company_name", "department"),
        date_field="created_at",
    ),
    "sales_receipt": _DocSpec(
        model_path="apps.documents.models:SalesReceipt",
        number_field="receipt_number",
        amount_fields=("total_amount", "subtotal"),
        vendor_fields=("seller_name", "customer_name"),
        date_field="receipt_date",
    ),

    # Phase-2 additions (10 new doc types)
    "sales_order": _DocSpec(
        model_path="apps.documents.models:SalesOrder",
        number_field="so_number",
        amount_fields=("total_amount", "subtotal"),
        vendor_fields=("customer_name",),
        date_field="so_date",
    ),
    "quotation": _DocSpec(
        model_path="apps.documents.models:Quotation",
        number_field="quotation_number",
        amount_fields=("total_amount", "subtotal"),
        vendor_fields=("party_name",),
        date_field="quotation_date",
    ),
    "proforma_invoice": _DocSpec(
        model_path="apps.documents.models:ProformaInvoice",
        number_field="proforma_number",
        amount_fields=("total_amount", "subtotal"),
        vendor_fields=("customer_name",),
        date_field="proforma_date",
    ),
    "receipt_voucher": _DocSpec(
        model_path="apps.documents.models:ReceiptVoucher",
        number_field="receipt_number",
        amount_fields=("amount",),
        vendor_fields=("payer_name",),
        date_field="receipt_date",
    ),
    "cash_voucher": _DocSpec(
        model_path="apps.documents.models:CashVoucher",
        number_field="voucher_number",
        amount_fields=("amount",),
        vendor_fields=("counterparty_name",),
        date_field="voucher_date",
    ),
    "general_ledger": _DocSpec(
        model_path="apps.documents.models:GeneralLedger",
        number_field="fiscal_year",
        amount_fields=("total_debit", "total_credit"),
        vendor_fields=(),
        date_field="period_to",
    ),
    "ledger": _DocSpec(
        model_path="apps.documents.models:Ledger",
        number_field="account_number",
        amount_fields=("closing_balance", "total_debit"),
        vendor_fields=("account_name",),
        date_field="period_to",
    ),
    "contract": _DocSpec(
        model_path="apps.documents.models:Contract",
        number_field="contract_number",
        amount_fields=("contract_value", "invoiced_to_date"),
        vendor_fields=("party_b", "title"),
        date_field="start_date",
    ),
    "supplier_statement": _DocSpec(
        model_path="apps.documents.models:SupplierStatement",
        number_field="supplier_id",
        amount_fields=("closing_balance", "total_invoiced"),
        vendor_fields=("supplier_name",),
        date_field="period_to",
    ),
    "customer_statement": _DocSpec(
        model_path="apps.documents.models:CustomerStatement",
        number_field="customer_id",
        amount_fields=("closing_balance", "total_invoiced"),
        vendor_fields=("customer_name",),
        date_field="period_to",
    ),

    # GRN + PaymentVoucher already exist as models — wire them in too.
    "grn": _DocSpec(
        model_path="apps.documents.models:GoodsReceiptNote",
        number_field="grn_number",
        amount_fields=("total_amount",),
        vendor_fields=("supplier_name",),
        date_field="receipt_date",
    ),
    "payment_voucher": _DocSpec(
        model_path="apps.documents.models:PaymentVoucher",
        number_field="payment_number",
        amount_fields=("total_amount", "amount"),
        vendor_fields=("payee_name",),
        date_field="payment_date",
    ),
    # Alias: tax_vat_document → VATReturn (same underlying model)
    "tax_vat_document": _DocSpec(
        model_path="apps.documents.models:VATReturn",
        number_field="vat_number",
        amount_fields=("net_vat_payable", "output_vat"),
        vendor_fields=("taxpayer_name",),
        date_field="filing_date",
    ),
}


def _resolve_model(spec: _DocSpec):
    mod_path, cls_name = spec.model_path.split(":")
    import importlib
    mod = importlib.import_module(mod_path)
    return getattr(mod, cls_name)


def _coerce(val) -> Any:
    """Make Decimal/datetime values JSON-friendly."""
    if val is None:
        return None
    try:
        # Decimal → float
        from decimal import Decimal
        if isinstance(val, Decimal):
            return float(val)
    except Exception:
        pass
    if hasattr(val, "isoformat"):
        return val.isoformat() if not isinstance(val, str) else val
    return val


class _ValidationView:
    """Duck-typed object matching what `_build_high_risk_violations` and
    `findings_service.build_findings_register` consume from validations:

      .invoice          (object with .id, .invoice_number, .total_amount, .vendor_name, .invoice_date)
      .failed_rule_codes  (list of rule codes)
      .validation_details (dict, optional)
    """
    __slots__ = ("invoice", "failed_rule_codes", "validation_details")

    def __init__(self, invoice, failed_rule_codes, validation_details=None):
        self.invoice = invoice
        self.failed_rule_codes = failed_rule_codes
        self.validation_details = validation_details or {}


class _DocView:
    """Tiny shim presenting a non-invoice document with the field names the
    existing report code expects.
    """
    __slots__ = (
        "id", "invoice_number", "total_amount", "vendor_name",
        "invoice_date", "currency", "risk_score", "risk_level",
    )

    def __init__(self, doc_obj, spec: _DocSpec):
        self.id = str(doc_obj.id)

        # Number/identifier
        num = getattr(doc_obj, spec.number_field, None)
        self.invoice_number = str(num) if num else str(doc_obj.id)[:8]

        # Amount: pick first non-zero candidate
        amount = 0.0
        for f in spec.amount_fields:
            v = getattr(doc_obj, f, None)
            if v:
                try:
                    amount = float(v)
                    if amount:
                        break
                except (TypeError, ValueError):
                    pass
        self.total_amount = amount

        # Vendor: first non-empty candidate
        vendor = ""
        for f in spec.vendor_fields:
            v = getattr(doc_obj, f, None)
            if v:
                vendor = str(v)
                break
        self.vendor_name = vendor or "—"

        # Date
        d = getattr(doc_obj, spec.date_field, None) if spec.date_field else None
        self.invoice_date = _coerce(d) or "-"

        self.currency = getattr(doc_obj, "currency", None) or "SAR"
        # The doc model already stores risk_score / risk_level from the validator
        self.risk_score = float(getattr(doc_obj, "validation_score", 0) or 0)
        self.risk_level = getattr(doc_obj, "risk_level", None) or "low"


def is_supported(doc_type: str) -> bool:
    return doc_type in _SPECS


def build_for_doc_type(org, doc_type: str) -> dict | None:
    """Return the unified report payload for a non-invoice doc type.

    Reads `failed_rule_codes`, `rules_failed`, `validation_score`, `risk_level`
    directly from the document model. Returns None for unsupported types.
    """
    spec = _SPECS.get(doc_type)
    if spec is None:
        return None
    Model = _resolve_model(spec)

    # Pull the columns we need only — these models can carry hundreds of rows
    # of line_items / JSON blobs we don't want hydrated. Some doc types lack
    # `currency` (e.g. VATReturn), so we filter the candidate field list
    # against the actual model schema before passing it to `.only()`.
    actual_fields = {f.name for f in Model._meta.get_fields()}
    candidate_fields = [
        "id",
        "validation_score",
        "rules_passed",
        "rules_failed",
        "failed_rule_codes",
        "validation_details",
        "risk_level",
        "currency",
        spec.number_field,
        *spec.amount_fields,
        *spec.vendor_fields,
        *((spec.date_field,) if spec.date_field else ()),
    ]
    only_fields = [f for f in candidate_fields if f in actual_fields]
    qs = Model.objects.filter(organization=org).only(*only_fields)

    rule_failures: Counter = Counter()
    validations: list[_ValidationView] = []
    risk_rows: list[_DocView] = []
    rules_failed_total = 0
    rules_passed_total = 0
    doc_count = 0
    total_amount = 0.0
    currencies: set[str] = set()

    for doc in qs:
        doc_count += 1
        rules_failed_total += int(getattr(doc, "rules_failed", 0) or 0)
        rules_passed_total += int(getattr(doc, "rules_passed", 0) or 0)

        codes = list(getattr(doc, "failed_rule_codes", []) or [])
        for code in codes:
            rule_failures[code] += 1

        details = getattr(doc, "validation_details", None) or {}
        view = _DocView(doc, spec)
        validations.append(_ValidationView(view, codes, details if isinstance(details, dict) else {}))

        total_amount += float(view.total_amount or 0)
        if view.currency:
            currencies.add(view.currency)

        if view.risk_level in ("high", "critical"):
            risk_rows.append(view)

    rules_applied_total = rules_failed_total + rules_passed_total
    compliance_pct = (
        round(rules_passed_total / rules_applied_total * 100, 1) if rules_applied_total else 0
    )
    primary_currency = next(iter(currencies)) if len(currencies) == 1 else "SAR"

    # Sort risk rows by score descending and trim
    risk_rows.sort(key=lambda r: -r.risk_score)
    top_risk = [{
        "id":             r.id,
        "invoice_number": r.invoice_number,
        "vendor_name":    r.vendor_name,
        "total_amount":   r.total_amount,
        "currency":       r.currency,
        "invoice_date":   r.invoice_date,
        "risk_level":     r.risk_level,
        "risk_score":     r.risk_score,
    } for r in risk_rows[:15]]

    top_failed = [
        {
            "rule_code":   code,
            "failures":    count,
            "description": DOC_RULES.get(code, (code, "medium"))[0],
        }
        for code, count in rule_failures.most_common(15)
    ]

    # ── Counterparty (vendor / seller / etc.) analysis ───────────────────
    # Aggregates spend / volume / risk per counterparty. Works for any doc
    # type that has at least one of the candidate vendor fields (PO, Invoice,
    # SalesReceipt etc.). Returns [] when none of them exist (e.g. Payroll).
    vendor_rows: list[dict] = []
    counterparty_field = next(
        (f for f in spec.vendor_fields if f in actual_fields),
        None,
    )
    amount_field = next(
        (f for f in spec.amount_fields if f in actual_fields),
        None,
    )
    if counterparty_field and amount_field:
        from django.db.models import Count, Sum, Avg, Q
        agg_qs = (
            Model.objects.filter(organization=org)
            .exclude(**{f"{counterparty_field}__in": ["", None]})
            .values(counterparty_field)
            .annotate(
                invoice_count=Count("id"),
                vendor_total=Sum(amount_field),
                avg_amount=Avg(amount_field),
                flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
            )
            .order_by("-vendor_total")[:15]
        )
        rows = list(agg_qs)
        total_spend = sum(float(r.get("vendor_total") or 0) for r in rows) or 1.0
        for r in rows:
            total = float(r.get("vendor_total") or 0)
            vendor_rows.append({
                "vendor_name":     r[counterparty_field] or "—",
                "invoice_count":   r["invoice_count"],
                "vendor_total":    round(total, 2),
                "avg_amount":      round(float(r.get("avg_amount") or 0), 2),
                "flagged":         r["flagged"],
                "spend_share_pct": round(total / total_spend * 100, 2),
            })

    return {
        "documents":       doc_count,
        "total_amount":    round(total_amount, 2),
        "currency":        primary_currency,
        "rules_applied":   rules_applied_total,
        "rules_passed":    rules_passed_total,
        "rules_failed":    rules_failed_total,
        "compliance_pct":  compliance_pct,
        "top_failed":      top_failed,
        "top_risk":        top_risk,
        "validations":     validations,
        "vendor_analysis": vendor_rows,
        # Expose the full rule catalog so the view can pass it where invoice
        # code currently passes RULES — keeps `_build_high_risk_violations`
        # capable of rendering doc-type-specific rule descriptions.
        "rule_catalog":    {code: title for code, (title, _sev) in DOC_RULES.items()},
    }
