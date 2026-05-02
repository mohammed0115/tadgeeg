"""
Phase-4 bulk-upload adapter for the 10 new typed-document models.

Reads tabular files (XLSX, CSV, JSON, JSONL) directly into structured records
and instantiates the right typed-model row, completely bypassing the
OCR / OpenAI extraction path. Spreadsheets carry the data already; running
GPT-4o on them just burns tokens.

Public API
----------
    extract_phase2_records(file_path, ext, doc_type) -> list[dict]
        Parse a structured file into one normalized record per row.

    create_phase2_record(doc_type, data, base_doc, org, user) -> Model
        Instantiate the typed model from a normalized record dict.

    PHASE2_TYPES: frozenset[str]
        The doc-type keys this adapter handles.

The adapter is intentionally column-tolerant: each model field accepts a list
of column-name aliases (English + Arabic + common ERP variants). Missing
columns silently default to the model field's default.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from django.db import models as dj_models

from apps.documents.typed_models_v2 import (
    SalesOrder, Quotation, ProformaInvoice, ReceiptVoucher, CashVoucher,
    GeneralLedger, Ledger, Contract, SupplierStatement, CustomerStatement,
    JournalEntry,
)
from apps.documents.typed_models import GoodsReceiptNote, PaymentVoucher

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Shared column normaliser — kept in sync with apps.documents.typed_views
# ──────────────────────────────────────────────────────────────────────────────
def _normalize_col(name: str) -> str:
    """Lowercase, strip parenthetical suffixes, collapse whitespace/underscores."""
    s = str(name).strip().lower()
    s = re.sub(r"\s*\([^)]*\)", "", s)        # drop "(SAR)", "(15%)", etc.
    s = re.sub(r"[\s\-]+", "_", s)            # spaces/dashes → underscore
    s = re.sub(r"_+", "_", s).strip("_")
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Model registry + column aliases per doc type
# ──────────────────────────────────────────────────────────────────────────────
_DOC_MODEL = {
    "sales_order":        SalesOrder,
    "quotation":          Quotation,
    "proforma_invoice":   ProformaInvoice,
    "receipt_voucher":    ReceiptVoucher,
    "cash_voucher":       CashVoucher,
    "general_ledger":     GeneralLedger,
    "ledger":             Ledger,
    "contract":           Contract,
    "supplier_statement": SupplierStatement,
    "customer_statement": CustomerStatement,
    "journal_entry":      JournalEntry,
    # GRN + PaymentVoucher live in typed_models.py (Phase-1) but the bulk
    # adapter handles them with the same table-driven flow.
    "goods_receipt_note": GoodsReceiptNote,
    "payment_voucher":    PaymentVoucher,
}

PHASE2_TYPES = frozenset(_DOC_MODEL.keys())


# Columns aliased per model field. Any alias that normalizes to the same key
# resolves to that field. Unknown columns are ignored.
#
# Convention: list English first (preferred ERP terms), then Arabic, then
# common variants. Aliases are auto-normalised at lookup time.
_FIELD_ALIASES: dict[str, dict[str, list[str]]] = {
    "sales_order": {
        "so_number": ["so_number", "order_number", "order_no", "sales_order", "sales_order_number",
                      "رقم أمر البيع", "رقم الأمر", "رقم الطلب"],
        "so_date": ["so_date", "order_date", "date", "issue_date",
                    "تاريخ الأمر", "تاريخ الطلب", "تاريخ"],
        "expected_delivery_date": ["expected_delivery_date", "delivery_date", "ship_date",
                                   "تاريخ التسليم", "تاريخ التسليم المتوقع"],
        "customer_name": ["customer_name", "customer", "client", "client_name", "buyer",
                          "اسم العميل", "العميل"],
        "customer_vat_number": ["customer_vat_number", "vat_number", "customer_vat", "tax_id",
                                "الرقم الضريبي", "رقم العميل الضريبي"],
        "customer_id_number": ["customer_id_number", "customer_id", "client_id",
                               "رقم العميل", "هوية العميل"],
        "department": ["department", "dept", "القسم", "الإدارة"],
        "status": ["status", "state", "الحالة"],
        "currency": ["currency", "ccy", "العملة"],
        "subtotal": ["subtotal", "net_amount", "amount_before_vat", "total_before_tax",
                     "إجمالي قبل الضريبة", "المجموع الفرعي"],
        "discount_amount": ["discount", "discount_amount", "الخصم", "مبلغ الخصم"],
        "vat_amount": ["vat_amount", "vat", "tax", "tax_amount", "ضريبة القيمة المضافة", "الضريبة"],
        "total_amount": ["total_amount", "total", "grand_total", "amount", "الإجمالي", "المجموع الكلي"],
        "customer_credit_limit": ["customer_credit_limit", "credit_limit", "حد الائتمان"],
        "customer_outstanding": ["customer_outstanding", "outstanding", "balance_due", "الرصيد المستحق"],
    },
    "quotation": {
        "quotation_number": ["quotation_number", "quote_number", "quote_no", "quote_id",
                             "رقم العرض", "رقم عرض السعر"],
        "quotation_date": ["quotation_date", "quote_date", "date", "issue_date",
                           "تاريخ العرض", "تاريخ"],
        "expiry_date": ["expiry_date", "valid_until", "validity_date",
                        "تاريخ انتهاء الصلاحية", "تاريخ الانتهاء"],
        "party_type": ["party_type", "type", "النوع"],
        "party_name": ["party_name", "customer_name", "client_name", "vendor_name", "party",
                       "اسم العميل", "اسم الطرف", "العميل"],
        "party_vat_number": ["party_vat_number", "vat_number", "tax_id",
                             "الرقم الضريبي"],
        "status": ["status", "الحالة"],
        "currency": ["currency", "العملة"],
        "subtotal": ["subtotal", "net_amount", "amount_before_vat",
                     "إجمالي قبل الضريبة", "المجموع الفرعي"],
        "discount_pct": ["discount_pct", "discount_percent", "discount_percentage",
                         "نسبة الخصم"],
        "discount_amount": ["discount", "discount_amount", "الخصم"],
        "vat_amount": ["vat_amount", "vat", "tax", "ضريبة القيمة المضافة"],
        "total_amount": ["total_amount", "total", "grand_total", "amount",
                         "الإجمالي", "المجموع الكلي"],
    },
    "proforma_invoice": {
        "proforma_number": ["proforma_number", "proforma_no", "invoice_number",
                            "رقم الفاتورة المبدئية", "رقم الفاتورة"],
        "proforma_date": ["proforma_date", "invoice_date", "date", "issue_date",
                          "تاريخ الفاتورة", "تاريخ الإصدار"],
        "validity_date": ["validity_date", "valid_until", "expiry_date",
                          "تاريخ انتهاء الصلاحية"],
        "customer_name": ["customer_name", "customer", "client_name", "buyer",
                          "اسم العميل", "العميل"],
        "customer_vat_number": ["customer_vat_number", "vat_number", "tax_id",
                                "الرقم الضريبي"],
        "status": ["status", "الحالة"],
        "currency": ["currency", "العملة"],
        "subtotal": ["subtotal", "net_amount", "amount_before_vat",
                     "إجمالي قبل الضريبة"],
        "vat_amount": ["vat_amount", "vat", "tax", "ضريبة القيمة المضافة"],
        "total_amount": ["total_amount", "total", "grand_total",
                         "الإجمالي", "المجموع الكلي"],
        "is_marked_proforma": ["is_marked_proforma", "marked_proforma", "is_proforma"],
    },
    "receipt_voucher": {
        "receipt_number": ["receipt_number", "receipt_no", "voucher_number", "ref",
                           "رقم سند القبض", "رقم السند"],
        "receipt_date": ["receipt_date", "date", "issue_date", "value_date",
                         "تاريخ السند", "تاريخ القبض"],
        "payer_name": ["payer_name", "payer", "from", "received_from", "customer_name",
                       "اسم الدافع", "المستلم منه", "اسم العميل"],
        "payer_vat_number": ["payer_vat_number", "vat_number", "الرقم الضريبي"],
        "receipt_method": ["receipt_method", "method", "payment_method", "channel",
                           "طريقة الدفع", "طريقة القبض"],
        "currency": ["currency", "العملة"],
        "amount": ["amount", "received_amount", "total_amount", "value",
                   "المبلغ", "المبلغ المستلم"],
        "linked_invoice_number": ["linked_invoice_number", "invoice_number", "invoice_no",
                                  "رقم الفاتورة"],
        "bank_reference": ["bank_reference", "bank_ref", "transaction_ref", "txn_ref",
                           "مرجع البنك", "المرجع البنكي"],
        "cheque_number": ["cheque_number", "check_number", "cheque_no",
                          "رقم الشيك"],
        "is_reconciled": ["is_reconciled", "reconciled", "matched", "تمت المطابقة"],
    },
    "cash_voucher": {
        "voucher_number": ["voucher_number", "voucher_no", "ref", "voucher_id",
                           "رقم السند", "رقم سند الصرف"],
        "voucher_date": ["voucher_date", "date", "issue_date",
                         "تاريخ السند", "تاريخ"],
        "movement_type": ["movement_type", "type", "direction",
                          "نوع الحركة"],
        "counterparty_name": ["counterparty_name", "counterparty", "to", "paid_to", "from",
                              "name", "اسم الطرف", "المستفيد"],
        "reason": ["reason", "purpose", "description", "memo", "البيان", "السبب", "الوصف"],
        "currency": ["currency", "العملة"],
        "amount": ["amount", "value", "المبلغ", "القيمة"],
        "has_attachment": ["has_attachment", "attachment", "with_attachment", "مرفقات"],
        "requires_approval": ["requires_approval", "needs_approval", "تتطلب الموافقة"],
        "approval_status": ["approval_status", "approved", "حالة الموافقة"],
        "cashbox_balance_after": ["cashbox_balance_after", "balance_after", "running_balance",
                                  "رصيد الصندوق", "الرصيد بعد الحركة"],
    },
    "general_ledger": {
        "period_from": ["period_from", "from_date", "start_date", "from",
                        "من تاريخ", "تاريخ البداية"],
        "period_to": ["period_to", "to_date", "end_date", "to",
                      "إلى تاريخ", "تاريخ النهاية"],
        "fiscal_year": ["fiscal_year", "year", "fy", "السنة المالية"],
        "total_debit": ["total_debit", "debit", "total_dr",
                        "إجمالي المدين", "مجموع المدين"],
        "total_credit": ["total_credit", "credit", "total_cr",
                         "إجمالي الدائن", "مجموع الدائن"],
        "accounts_count": ["accounts_count", "accounts", "n_accounts",
                           "عدد الحسابات"],
        "movements_count": ["movements_count", "transactions_count", "entries_count",
                            "عدد الحركات", "عدد القيود"],
        "is_balanced": ["is_balanced", "balanced", "متوازن"],
    },
    "ledger": {
        "account_number": ["account_number", "account_code", "code", "account_no",
                           "رقم الحساب", "كود الحساب"],
        "account_name": ["account_name", "name", "اسم الحساب"],
        "account_type": ["account_type", "type", "category", "نوع الحساب"],
        "period_from": ["period_from", "from_date", "start_date", "من تاريخ"],
        "period_to": ["period_to", "to_date", "end_date", "إلى تاريخ"],
        "currency": ["currency", "العملة"],
        "opening_balance": ["opening_balance", "opening", "beginning_balance",
                            "الرصيد الافتتاحي"],
        "closing_balance": ["closing_balance", "closing", "ending_balance",
                            "الرصيد الختامي"],
        "total_debit": ["total_debit", "debit", "إجمالي المدين"],
        "total_credit": ["total_credit", "credit", "إجمالي الدائن"],
        "movements_count": ["movements_count", "transactions_count", "n_movements",
                            "عدد الحركات"],
    },
    "contract": {
        "contract_number": ["contract_number", "contract_no", "ref", "agreement_number",
                            "رقم العقد"],
        "title": ["title", "subject", "name", "الموضوع", "عنوان العقد"],
        "party_a": ["party_a", "first_party", "our_party",
                    "الطرف الأول", "الطرف الأول من العقد"],
        "party_b": ["party_b", "counterparty", "second_party", "vendor", "supplier", "customer",
                    "الطرف الثاني", "الطرف المقابل"],
        "party_b_type": ["party_b_type", "counterparty_type", "type", "نوع الطرف"],
        "party_b_vat_number": ["party_b_vat_number", "vat_number", "tax_id",
                               "الرقم الضريبي"],
        "start_date": ["start_date", "from_date", "begin_date",
                       "تاريخ البداية", "تاريخ البدء"],
        "end_date": ["end_date", "to_date", "expiry_date",
                     "تاريخ الانتهاء", "تاريخ النهاية"],
        "signing_date": ["signing_date", "signed_date", "date_signed",
                         "تاريخ التوقيع"],
        "is_signed": ["is_signed", "signed", "تم التوقيع"],
        "status": ["status", "state", "الحالة"],
        "currency": ["currency", "العملة"],
        "contract_value": ["contract_value", "value", "amount", "total",
                           "قيمة العقد", "إجمالي العقد"],
        "invoiced_to_date": ["invoiced_to_date", "invoiced", "billed_to_date",
                             "المفوتر حتى تاريخه"],
        "payment_terms": ["payment_terms", "terms", "شروط الدفع"],
        "has_attachment": ["has_attachment", "attachment", "مرفقات"],
    },
    "supplier_statement": {
        "supplier_name": ["supplier_name", "supplier", "vendor_name", "vendor",
                          "اسم المورد", "المورد"],
        "supplier_id": ["supplier_id", "vendor_id", "supplier_code",
                        "رقم المورد", "كود المورد"],
        "supplier_vat_number": ["supplier_vat_number", "vat_number", "tax_id",
                                "الرقم الضريبي"],
        "period_from": ["period_from", "from_date", "start_date", "من تاريخ"],
        "period_to": ["period_to", "to_date", "end_date", "إلى تاريخ"],
        "currency": ["currency", "العملة"],
        "opening_balance": ["opening_balance", "opening", "beginning_balance",
                            "الرصيد الافتتاحي"],
        "closing_balance": ["closing_balance", "closing", "ending_balance",
                            "الرصيد الختامي"],
        "total_invoiced": ["total_invoiced", "invoiced", "purchases",
                           "إجمالي المشتريات", "إجمالي الفواتير"],
        "total_paid": ["total_paid", "paid", "payments",
                       "إجمالي المدفوعات", "المسدد"],
        "balance_variance": ["balance_variance", "variance", "diff",
                             "فرق الرصيد"],
        "duplicate_count": ["duplicate_count", "duplicates",
                            "عدد المكررات"],
    },
    "customer_statement": {
        "customer_name": ["customer_name", "customer", "client_name", "client",
                          "اسم العميل", "العميل"],
        "customer_id": ["customer_id", "client_id", "customer_code",
                        "رقم العميل", "كود العميل"],
        "customer_vat_number": ["customer_vat_number", "vat_number", "tax_id",
                                "الرقم الضريبي"],
        "period_from": ["period_from", "from_date", "start_date", "من تاريخ"],
        "period_to": ["period_to", "to_date", "end_date", "إلى تاريخ"],
        "currency": ["currency", "العملة"],
        "opening_balance": ["opening_balance", "opening", "beginning_balance",
                            "الرصيد الافتتاحي"],
        "closing_balance": ["closing_balance", "closing", "ending_balance",
                            "الرصيد الختامي"],
        "total_invoiced": ["total_invoiced", "invoiced", "sales",
                           "إجمالي المبيعات", "إجمالي الفواتير"],
        "total_received": ["total_received", "received", "receipts", "collections",
                           "إجمالي المتحصلات", "المحصل"],
        "balance_variance": ["balance_variance", "variance", "diff",
                             "فرق الرصيد"],
        "duplicate_count": ["duplicate_count", "duplicates",
                            "عدد المكررات"],
    },
    "journal_entry": {
        "entry_number": ["entry_number", "je_number", "voucher_number", "ref",
                         "رقم القيد", "رقم اليومية"],
        "entry_date": ["entry_date", "date", "posting_date",
                       "تاريخ القيد", "تاريخ"],
        "description": ["description", "narration", "memo", "البيان", "الوصف"],
        "fiscal_period": ["fiscal_period", "period", "الفترة المالية"],
        "currency": ["currency", "العملة"],
        "total_debit": ["total_debit", "debit", "إجمالي المدين"],
        "total_credit": ["total_credit", "credit", "إجمالي الدائن"],
        "lines_count": ["lines_count", "lines", "n_lines", "عدد السطور"],
        "is_balanced": ["is_balanced", "balanced", "متوازن"],
        "is_manual": ["is_manual", "manual", "يدوي"],
        "has_attachment": ["has_attachment", "attachment", "مرفقات"],
        "is_period_close": ["is_period_close", "period_close", "إقفال فترة"],
        "approval_status": ["approval_status", "approved", "حالة الموافقة"],
    },
    "goods_receipt_note": {
        "grn_number": ["grn_number", "grn_no", "receipt_number", "ref",
                       "رقم سند الاستلام", "رقم الاستلام"],
        "grn_date": ["grn_date", "receipt_date", "date",
                     "تاريخ الاستلام"],
        "po_number": ["po_number", "po_no", "purchase_order",
                      "رقم أمر الشراء"],
        "invoice_number": ["invoice_number", "invoice_no",
                           "رقم الفاتورة"],
        "vendor_name": ["vendor_name", "vendor", "supplier_name", "supplier",
                        "اسم المورد", "المورد"],
        "vendor_vat_number": ["vendor_vat_number", "vat_number", "الرقم الضريبي"],
        "department": ["department", "القسم"],
        "received_by": ["received_by", "receiver", "تم الاستلام بواسطة"],
        "warehouse_location": ["warehouse_location", "warehouse", "location",
                               "المستودع"],
        "currency": ["currency", "العملة"],
        "total_ordered_qty": ["total_ordered_qty", "ordered_qty",
                              "الكمية المطلوبة"],
        "total_received_qty": ["total_received_qty", "received_qty",
                               "الكمية المستلمة"],
        "total_rejected_qty": ["total_rejected_qty", "rejected_qty",
                               "الكمية المرفوضة"],
        "total_amount": ["total_amount", "total", "amount",
                         "الإجمالي"],
        "invoice_amount": ["invoice_amount", "مبلغ الفاتورة"],
        "delivery_date": ["delivery_date", "تاريخ التسليم"],
        "delivery_overdue": ["delivery_overdue", "overdue"],
        "quality_inspection_done": ["quality_inspection_done", "qc_done",
                                    "تم الفحص"],
        "approval_status": ["approval_status", "approval", "حالة الموافقة"],
    },
    "payment_voucher": {
        "payment_number": ["payment_number", "payment_no", "voucher_number",
                           "رقم سند الصرف", "رقم السند"],
        "payment_date": ["payment_date", "date",
                         "تاريخ الصرف", "تاريخ الدفع"],
        "payment_method": ["payment_method", "method", "channel",
                           "طريقة الدفع"],
        "payee_name": ["payee_name", "payee", "to", "vendor_name",
                       "المستفيد", "اسم المستفيد"],
        "payee_vat_number": ["payee_vat_number", "vat_number", "الرقم الضريبي"],
        "payee_iban": ["payee_iban", "iban", "آيبان"],
        "currency": ["currency", "العملة"],
        "amount": ["amount", "value", "المبلغ"],
        "vat_amount": ["vat_amount", "vat", "tax", "الضريبة"],
        "total_amount": ["total_amount", "total", "grand_total",
                         "الإجمالي"],
        "linked_invoice_number": ["linked_invoice_number", "invoice_number",
                                  "رقم الفاتورة"],
        "linked_po_number": ["linked_po_number", "po_number",
                             "رقم أمر الشراء"],
        "bank_reference": ["bank_reference", "bank_ref", "txn_ref",
                           "مرجع البنك"],
        "approval_status": ["approval_status", "approval", "حالة الموافقة"],
        "is_advance_payment": ["is_advance_payment", "is_advance", "دفعة مقدمة"],
        "cost_center": ["cost_center", "مركز التكلفة"],
        "account_code": ["account_code", "كود الحساب"],
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Coercion
# ──────────────────────────────────────────────────────────────────────────────
def _to_date(val) -> Optional[Any]:
    if val in (None, ""):
        return None
    s = str(val).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _to_decimal(val) -> Decimal:
    if val in (None, ""):
        return Decimal("0")
    try:
        s = str(val).replace(",", "").strip()
        return Decimal(s) if s else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _to_bool(val) -> bool:
    if val is True or val is False:
        return val
    s = str(val or "").strip().lower()
    return s in {"1", "true", "yes", "y", "نعم", "صح", "✓"}


def _to_int(val) -> int:
    if val in (None, ""):
        return 0
    try:
        return int(float(str(val).replace(",", "").strip() or 0))
    except (ValueError, TypeError):
        return 0


def _coerce(field: dj_models.Field, raw_value):
    """Coerce a raw cell value to the model field's expected type."""
    if isinstance(field, dj_models.DateField):
        return _to_date(raw_value)
    if isinstance(field, dj_models.DecimalField):
        return _to_decimal(raw_value)
    if isinstance(field, dj_models.BooleanField):
        return _to_bool(raw_value)
    if isinstance(field, (dj_models.PositiveIntegerField, dj_models.IntegerField)):
        return _to_int(raw_value)
    if isinstance(field, dj_models.JSONField):
        if isinstance(raw_value, (list, dict)):
            return raw_value
        s = str(raw_value or "").strip()
        if not s:
            return field.get_default()
        try:
            return json.loads(s)
        except (ValueError, TypeError):
            return field.get_default()
    # CharField / TextField — keep as string
    s = "" if raw_value is None else str(raw_value).strip()
    if s.lower() in {"nan", "none", "null"}:
        s = ""
    max_len = getattr(field, "max_length", None)
    if max_len and len(s) > max_len:
        s = s[:max_len]
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Record extraction
# ──────────────────────────────────────────────────────────────────────────────
def _build_alias_index(doc_type: str) -> dict[str, str]:
    """Map normalized-alias → model_field_name for one doc type."""
    aliases = _FIELD_ALIASES.get(doc_type, {})
    index: dict[str, str] = {}
    for field_name, alias_list in aliases.items():
        # Always also accept the field name itself, normalized
        for alias in [field_name] + alias_list:
            index[_normalize_col(alias)] = field_name
    return index


def _normalize_record(raw: dict, doc_type: str) -> dict:
    """Map raw {column → value} dict to {model_field → coerced_value}."""
    if doc_type not in _DOC_MODEL:
        raise ValueError(f"bulk_adapter does not handle doc_type: {doc_type}")

    Model = _DOC_MODEL[doc_type]
    alias_index = _build_alias_index(doc_type)
    out: dict = {}
    for col, val in raw.items():
        norm = _normalize_col(str(col))
        field_name = alias_index.get(norm)
        if not field_name:
            continue
        try:
            field = Model._meta.get_field(field_name)
        except Exception:
            continue
        out[field_name] = _coerce(field, val)
    return out


def _read_dataframe(file_path: str, ext: str):
    """Load XLSX/CSV/JSON/JSONL into a list of dicts (one per row/record)."""
    import pandas as pd

    ext = ext.lower()
    if ext in {".xlsx", ".xls"}:
        df = pd.read_excel(file_path, sheet_name=0, dtype=str, keep_default_na=False)
    elif ext == ".csv":
        df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    elif ext == ".jsonl":
        rows = []
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    elif ext == ".json":
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("records", "items", "data", "rows"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]  # treat top-level dict as one record
        return []
    else:
        return []

    # Keep raw column names — _normalize_col handles case + whitespace at lookup.
    return df.to_dict(orient="records")


def extract_phase2_records(file_path: str, ext: str, doc_type: str) -> list[dict]:
    """Parse a structured file into normalized records for the given Phase-2 doc type."""
    if doc_type not in _DOC_MODEL:
        return []
    try:
        raw_rows = _read_dataframe(file_path, ext)
    except Exception as exc:
        logger.warning("[bulk_adapter] read failed: %s", exc)
        return []

    out: list[dict] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        norm = _normalize_record(raw, doc_type)
        if any(v not in (None, "", 0, Decimal("0"), False, []) for v in norm.values()):
            out.append(norm)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Record creation
# ──────────────────────────────────────────────────────────────────────────────
def create_phase2_record(doc_type: str, data: dict, base_doc, org, user):
    """Create one typed-model row from a normalized record dict."""
    Model = _DOC_MODEL[doc_type]

    # Filter to fields the model actually has + AuditMixin foreign keys
    valid_fields = {f.name for f in Model._meta.get_fields() if hasattr(f, "name")}
    payload = {k: v for k, v in data.items() if k in valid_fields}

    return Model.objects.create(
        organization=org,
        document=base_doc,
        uploaded_by=user,
        **payload,
    )


def create_phase2_records_bulk(
    doc_type: str,
    records: Iterable[dict],
    base_doc,
    org,
    user,
) -> list:
    """Batch-create multiple rows for the same doc-type. Returns the row instances."""
    return [create_phase2_record(doc_type, rec, base_doc, org, user) for rec in records]
