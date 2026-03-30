"""
Typed Document Views
=====================
Universal upload endpoint that routes to the correct model + validator
based on `document_type` field.

New endpoints:
  POST /api/v1/documents/upload/typed/        ← smart upload (any doc type)
  GET  /api/v1/documents/purchase-orders/
  GET  /api/v1/documents/purchase-orders/<id>/
  POST /api/v1/documents/purchase-orders/<id>/approve/
  GET  /api/v1/documents/bank-statements/
  GET  /api/v1/documents/bank-statements/<id>/
  GET  /api/v1/documents/payroll/
  GET  /api/v1/documents/payroll/<id>/
  GET  /api/v1/documents/expense-reports/
  GET  /api/v1/documents/expense-reports/<id>/
  GET  /api/v1/documents/vat-returns/
  GET  /api/v1/documents/vat-returns/<id>/
  GET  /api/v1/documents/fixed-assets/
  GET  /api/v1/documents/fixed-assets/<id>/
  GET  /api/v1/documents/sales-receipts/
  GET  /api/v1/documents/sales-receipts/<id>/
  GET  /api/v1/documents/stats/               ← counts by type
"""

import io
import os
import time
import logging
from django.utils.translation import gettext as _
import zipfile
from decimal import Decimal

from django.utils import timezone
from django.core.files.base import ContentFile
from django.db.models import Count, Sum, Avg, Q
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter

from core.services.ocr_service import extract_text_tesseract, pdf_to_images
from core.services.doc_ai_service import extract_document
from core.services.doc_validators import run_document_validation
from core.services.zip_validator import validate_zip_bomb, ZipValidationError
from core.utils.audit import log_action
from apps.authentication.models import AuditLog
from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .models import Document
from .typed_models import (
    PurchaseOrder, PurchaseOrderValidation,
    BankStatement, BankStatementValidation,
    PayrollSheet, PayrollValidation,
    ExpenseReport, ExpenseReportValidation,
    VATReturn, VATReturnValidation,
    FixedAsset, FixedAssetValidation,
    SalesReceipt, SalesReceiptValidation,
    DOCUMENT_TYPE_MAP, DOCUMENT_TYPE_LABELS_AR,
    DOCUMENT_TYPE_LABELS,
)
from .typed_serializers import (
    PurchaseOrderSerializer, PurchaseOrderListSerializer,
    BankStatementSerializer, BankStatementListSerializer,
    PayrollSheetSerializer, PayrollSheetListSerializer,
    ExpenseReportSerializer, ExpenseReportListSerializer,
    VATReturnSerializer, VATReturnListSerializer,
    FixedAssetSerializer, FixedAssetListSerializer,
    SalesReceiptSerializer, SalesReceiptListSerializer,
)

logger = logging.getLogger("finai")

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".zip", ".csv", ".json", ".jsonl", ".xlsx", ".xls"}

VALID_TYPES = list(DOCUMENT_TYPE_MAP.keys())


# ── OCR helper (shared with invoice pipeline) ──────────────────────────────────

def _run_ocr(file_path: str, ext: str) -> tuple[str, float]:
    """
    Extract text based on file type:
    - For images/PDF: Use Tesseract OCR
    - For structured data (CSV/JSON/XLSX): Use parsers
    """
    try:
        # For structured data files, use parsers instead of OCR
        if ext in {".csv", ".json", ".jsonl", ".xlsx", ".xls"}:
            from core.services.parsers.csv_parser import CSVParser
            from core.services.parsers.json_parser import JSONParser
            from core.services.parsers.excel_parser import ExcelParser
            
            parser = None
            if ext == ".csv":
                parser = CSVParser()
            elif ext in {".json", ".jsonl"}:
                parser = JSONParser()
            elif ext in {".xlsx", ".xls"}:
                parser = ExcelParser()
            
            if parser:
                result = parser.parse(file_path)
                if result.success:
                    text = result.raw_text or ""
                    if result.structured:
                        import json
                        text += "\n\n[STRUCTURED DATA]\n" + json.dumps(result.structured, ensure_ascii=False, indent=2)[:10000]
                    return text, 1.0  # 100% confidence for structured data
            return "", 0.0
        
        # For images and PDFs, use Tesseract OCR
        image_paths = pdf_to_images(file_path) if ext == ".pdf" else [file_path]
        result = extract_text_tesseract(image_paths[0])
        return result.get("text", ""), result.get("confidence", 0.0)
    except Exception as e:
        logger.warning(f"Text extraction failed: {e}")
        return "", 0.0


def _save_date(val):
    if not val:
        return None
    try:
        from datetime import datetime
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(str(val), fmt).date()
            except ValueError:
                continue
    except Exception:
        return None


def _safe_decimal(val):
    try:
        return Decimal(str(val)) if val else Decimal("0")
    except Exception:
        return Decimal("0")


# ── Pandas direct extraction for XLSX / CSV / JSON ────────────────────────────

_STRUCTURED_EXTS = {".xlsx", ".xls", ".csv", ".json", ".jsonl"}


def _first_nonempty(series):
    """Return first non-empty string value from a pandas Series, or ''."""
    if series is None:
        return ""
    for v in series:
        s = str(v).strip()
        if s:
            return s
    return ""


import re as _re

def _normalize_col_name(name: str) -> str:
    """
    Normalize column name for fuzzy matching:
    - lowercase
    - strip parenthetical suffixes like (SAR), (15%), (سنة), (%)
    - collapse spaces, dashes, underscores to single underscore
    """
    s = str(name).strip().lower()
    s = _re.sub(r'\s*\([^)]*\)', '', s)   # remove (SAR), (15%), etc.
    s = _re.sub(r'[\s\-]+', '_', s)        # spaces/dashes → underscore
    s = _re.sub(r'_+', '_', s).strip('_') # collapse multiple underscores
    return s


def _col(df, *candidates):
    """Return the first matching column Series by normalized name, or None."""
    cols_norm = {_normalize_col_name(c): c for c in df.columns}
    for name in candidates:
        real = cols_norm.get(_normalize_col_name(name))
        if real is not None:
            return df[real]
    return None


def _row_get(row, *candidates):
    """
    Normalized row value lookup — strips (SAR)/(%) suffixes, case-insensitive.
    """
    row_norm = {_normalize_col_name(str(k)): v for k, v in row.items()}
    for name in candidates:
        key = _normalize_col_name(name)
        val = row_norm.get(key)
        if val is not None and str(val).strip() not in ("", "nan", "none", "0.0", "0"):
            return val
    return None


def _sum_col(df, *candidates):
    """Sum the first matching numeric column."""
    series = _col(df, *candidates)
    if series is None:
        return 0.0
    total = 0.0
    for v in series:
        try:
            total += float(str(v).replace(",", "").strip() or "0")
        except Exception:
            pass
    return round(total, 2)


def _load_dataframe(file_path: str, ext: str):
    """Load file into a pandas DataFrame, normalising column names to lowercase."""
    import pandas as pd
    import json as _json

    if ext in {".xlsx", ".xls"}:
        df = pd.read_excel(file_path, sheet_name=0, dtype=str, keep_default_na=False)
    elif ext == ".csv":
        df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    elif ext == ".jsonl":
        with open(file_path, encoding="utf-8") as f:
            rows = [_json.loads(line) for line in f if line.strip()]
        df = pd.DataFrame(rows).astype(str)
    else:  # .json
        with open(file_path, encoding="utf-8") as f:
            data = _json.load(f)
        if isinstance(data, list):
            df = pd.DataFrame(data).astype(str)
        elif isinstance(data, dict):
            rows = data.get("records", data.get("items", data.get("data", [data])))
            df = pd.DataFrame(rows if isinstance(rows, list) else [rows]).astype(str)
        else:
            return None

    df.columns = [str(c).lower().strip() for c in df.columns]
    return df if not df.empty else None


def _extract_from_pandas(file_path: str, ext: str, doc_type: str) -> dict:
    """
    Read XLSX/CSV/JSON with pandas and map columns directly to typed model fields.
    Returns a partial ai_data dict — caller merges with OpenAI result.
    """
    try:
        df = _load_dataframe(file_path, ext)
        if df is None:
            return {}

        if doc_type == "purchase_order":
            line_items = []
            for _, row in df.iterrows():
                # description: "وصف الصنف" OR "اسم الصنف" from actual sample file
                desc = str(_row_get(row,
                    "وصف الصنف", "اسم الصنف",          # actual sample columns
                    "description", "item", "item_name",
                    "الوصف", "البند", "اسم البند") or "")
                qty = float(_safe_decimal(_row_get(row,
                    "الكمية", "qty", "quantity", "كمية") or 0))
                unit_price = float(_safe_decimal(_row_get(row,
                    "سعر الوحدة (SAR)", "سعر الوحدة",
                    "unit_price", "price", "السعر") or 0))
                subtotal_line = float(_safe_decimal(_row_get(row,
                    "إجمالي قبل الضريبة",               # actual sample column (no SAR suffix)
                    "subtotal", "amount_before_vat") or 0))
                vat_line = float(_safe_decimal(_row_get(row,
                    "ضريبة القيمة (15%)", "ضريبة القيمة",  # actual sample column
                    "vat_amount", "vat", "tax") or 0))
                total_line = float(_safe_decimal(_row_get(row,
                    "الإجمالي الكلي (SAR)", "الإجمالي الكلي",  # actual sample column
                    "total", "total_amount", "المجموع") or 0))
                # Auto-compute missing values
                if not total_line and (subtotal_line or unit_price):
                    total_line = round((subtotal_line or unit_price * qty) + vat_line, 2)
                if not subtotal_line and unit_price and qty:
                    subtotal_line = round(unit_price * qty, 2)
                item = {
                    "description": desc,
                    "qty":         qty,
                    "unit_price":  unit_price,
                    "subtotal":    subtotal_line,
                    "vat_amount":  vat_line,
                    "total":       total_line,
                }
                if desc or unit_price or qty:
                    line_items.append(item)

            total   = _sum_col(df,
                "الإجمالي الكلي (SAR)", "الإجمالي الكلي",
                "total", "total_amount")
            vat     = _sum_col(df,
                "ضريبة القيمة (15%)", "ضريبة القيمة",
                "vat_amount", "vat", "tax")
            subtotal = _sum_col(df,
                "إجمالي قبل الضريبة",
                "subtotal", "amount_before_vat")
            if not subtotal and total and vat:
                subtotal = round(total - vat, 2)
            return {
                "po_number":         _first_nonempty(_col(df,
                    "رقم أمر الشراء", "po_number", "reference", "ref")),
                "po_date":           _first_nonempty(_col(df,
                    "تاريخ الإصدار", "date", "po_date", "invoice_date")),
                "delivery_date":     _first_nonempty(_col(df,
                    "تاريخ التسليم المطلوب", "delivery_date", "due_date")),
                "vendor_name":       _first_nonempty(_col(df,
                    "اسم المورد", "vendor_name", "vendor", "supplier")),
                "vendor_vat_number": _first_nonempty(_col(df,
                    "رقم ضريبة المورد", "vendor_vat_number", "vat_number")),
                "cost_center":       _first_nonempty(_col(df,
                    "مركز التكلفة", "cost_center")),
                "account_code":      _first_nonempty(_col(df,
                    "رمز الحساب", "account_code")),
                "currency":          _first_nonempty(_col(df, "currency", "العملة")) or "SAR",
                "total_amount":      total,
                "vat_amount":        vat,
                "subtotal":          subtotal,
                "line_items":        line_items,
                "ai_summary":        f"تم استيراد {len(line_items)} بند من الملف المهيكل",
            }

        if doc_type == "bank_statement":
            transactions = []
            for _, row in df.iterrows():
                debit  = float(_safe_decimal(_row_get(row,
                    "مدين (SAR)", "مدين", "debit", "withdrawals", "المدين") or 0))
                credit = float(_safe_decimal(_row_get(row,
                    "دائن (SAR)", "دائن", "credit", "deposits", "الدائن") or 0))
                amt    = float(_safe_decimal(_row_get(row, "amount", "المبلغ") or 0))
                if not debit and not credit and amt:
                    if amt < 0:
                        debit = abs(amt)
                    else:
                        credit = amt
                t = {
                    "date":        str(_row_get(row,
                        "تاريخ المعاملة", "date", "txn_date", "تاريخ") or ""),
                    "description": str(_row_get(row,
                        "وصف المعاملة",              # actual sample column
                        "البيان", "description", "narration", "الوصف") or ""),
                    "debit":       debit,
                    "credit":      credit,
                    "amount":      credit - debit if (credit or debit) else 0.0,
                    "balance":     float(_safe_decimal(_row_get(row,
                        "الرصيد (SAR)", "الرصيد", "balance") or 0)),
                    "ref":         str(_row_get(row,
                        "رقم المرجع", "reference", "ref", "المرجع") or ""),
                }
                transactions.append(t)
            credits = sum(t["credit"] for t in transactions)
            debits  = sum(t["debit"]  for t in transactions)
            return {
                "bank_name":         _first_nonempty(_col(df,
                    "اسم البنك", "bank_name", "bank")),
                "account_number":    _first_nonempty(_col(df,
                    "رقم الحساب", "account_number", "account")),
                "transaction_count": len(transactions),
                "total_credits":     round(credits, 2),
                "total_debits":      round(debits, 2),
                "transactions":      transactions,
                "currency":          _first_nonempty(_col(df,
                    "رمز العملة", "currency", "العملة")) or "SAR",
                "ai_summary":        f"تم استيراد {len(transactions)} معاملة من الملف المهيكل",
            }

        if doc_type == "payroll":
            employees = []
            for _, row in df.iterrows():
                basic = float(_safe_decimal(_row_get(row,
                    "الراتب الأساسي (SAR)", "الراتب الأساسي",
                    "gross", "gross_salary") or 0))
                total_gross = float(_safe_decimal(_row_get(row,
                    "إجمالي الراتب (SAR)", "إجمالي الراتب",
                    "total_salary") or basic))
                deductions = float(_safe_decimal(_row_get(row,
                    "الاستقطاعات (SAR)", "الاستقطاعات",
                    "deductions", "الخصومات") or 0))
                net = float(_safe_decimal(_row_get(row,
                    "صافي الراتب (SAR)", "صافي الراتب",
                    "net", "net_salary") or 0))
                # Sum individual allowances if no single allowances column
                housing    = float(_safe_decimal(_row_get(row, "بدل السكن (SAR)", "بدل السكن", "housing_allowance") or 0))
                transport  = float(_safe_decimal(_row_get(row, "بدل المواصلات (SAR)", "بدل المواصلات", "transport_allowance") or 0))
                comms      = float(_safe_decimal(_row_get(row, "بدل اتصالات (SAR)", "بدل اتصالات", "comms_allowance") or 0))
                other_all  = float(_safe_decimal(_row_get(row, "بدلات أخرى (SAR)", "بدلات أخرى", "other_allowances") or 0))
                allowances = housing + transport + comms + other_all or float(_safe_decimal(
                    _row_get(row, "البدلات", "allowances", "إجمالي البدلات") or 0))
                e = {
                    "name":         str(_row_get(row,
                        "اسم الموظف", "name", "employee_name") or ""),
                    "id":           str(_row_get(row,
                        "رقم الموظف", "رقم الهوية / الإقامة",
                        "id", "employee_id") or ""),
                    "gross":        total_gross or basic,
                    "net":          net,
                    "allowances":   allowances,
                    "deductions":   deductions,
                    "gosi":         float(_safe_decimal(_row_get(row,
                        "gosi", "التأمينات", "اشتراك التأمينات") or 0)),
                    "bank_account": str(_row_get(row,
                        "رقم الحساب البنكي", "bank_account", "iban") or ""),
                }
                if e["name"] or e["gross"]:
                    employees.append(e)
            return {
                "employee_count":     len(employees),
                "total_gross_salary": _sum_col(df,
                    "إجمالي الراتب (SAR)", "إجمالي الراتب",
                    "gross", "gross_salary"),
                "total_net_salary":   _sum_col(df,
                    "صافي الراتب (SAR)", "صافي الراتب",
                    "net", "net_salary"),
                "total_allowances":   (
                    _sum_col(df, "بدل السكن (SAR)", "بدل السكن") +
                    _sum_col(df, "بدل المواصلات (SAR)", "بدل المواصلات") +
                    _sum_col(df, "بدل اتصالات (SAR)", "بدل اتصالات") +
                    _sum_col(df, "بدلات أخرى (SAR)", "بدلات أخرى") or
                    _sum_col(df, "البدلات", "allowances")
                ),
                "total_deductions":   _sum_col(df,
                    "الاستقطاعات (SAR)", "الاستقطاعات", "deductions"),
                "total_gosi":         _sum_col(df, "gosi", "التأمينات"),
                "employees":          employees,
                "currency":           "SAR",
                "ai_summary":         f"تم استيراد {len(employees)} موظف من الملف المهيكل",
            }

        if doc_type == "expense_report":
            lines = []
            for _, row in df.iterrows():
                receipt_raw = str(_row_get(row,
                    "هل يوجد إيصال؟",           # actual sample column
                    "receipt_attached", "receipt", "إيصال") or "نعم")
                receipt_attached = receipt_raw.strip() not in ("لا", "no", "false", "0", "")
                l = {
                    "date":             str(_row_get(row,
                        "تاريخ المصروف",             # actual sample column
                        "date", "expense_date") or ""),
                    "description":      str(_row_get(row,
                        "وصف المصروف",               # actual sample column
                        "description", "purpose", "الوصف", "البند") or ""),
                    "amount":           float(_safe_decimal(_row_get(row,
                        "المبلغ (SAR)", "المبلغ",    # actual sample column
                        "amount") or 0)),
                    "vat_amount":       float(_safe_decimal(_row_get(row,
                        "ضريبة القيمة (SAR)", "ضريبة القيمة",  # actual sample column
                        "vat", "tax") or 0)),
                    "total":            float(_safe_decimal(_row_get(row,
                        "الإجمالي (SAR)", "الإجمالي",  # actual sample column
                        "total", "total_amount") or 0)),
                    "category":         str(_row_get(row,
                        "نوع المصروف",               # actual sample column
                        "category", "type", "الفئة") or "other"),
                    "receipt_attached": receipt_attached,
                    "receipt_number":   str(_row_get(row,
                        "رقم المطالبة", "receipt_number", "رقم_الإيصال") or ""),
                }
                if l["description"] or l["amount"]:
                    lines.append(l)
            missing = sum(1 for l in lines if not l["receipt_attached"])
            return {
                "employee_name":        _first_nonempty(_col(df,
                    "اسم الموظف", "employee_name")),
                "employee_id":          _first_nonempty(_col(df,
                    "رقم الموظف", "employee_id")),
                "total_claimed":        _sum_col(df,
                    "المبلغ (SAR)", "المبلغ", "amount"),
                "vat_included":         _sum_col(df,
                    "ضريبة القيمة (SAR)", "ضريبة القيمة", "vat"),
                "expense_lines":        lines,
                "missing_receipts_count": missing,
                "currency":             "SAR",
                "ai_summary":           f"تم استيراد {len(lines)} مصروف من الملف المهيكل",
            }

        if doc_type in ("vat_return", "tax_declaration"):
            # VAT return: one row per filing period
            first = df.iloc[0].to_dict() if len(df) > 0 else {}
            def _fv(*cols):
                return _row_get(first, *cols)
            return {
                "taxpayer_name":            str(_fv(
                    "اسم الشركة",                        # actual sample column
                    "اسم المنشأة", "taxpayer_name", "company_name") or ""),
                "vat_number":               str(_fv(
                    "رقم تسجيل ضريبة القيمة",           # actual sample column
                    "الرقم الضريبي", "vat_number") or ""),
                "zatca_reference":          str(_fv(
                    "رقم الإقرار", "zatca_reference", "ref") or ""),
                "period_from":              str(_fv("period_from", "from") or ""),
                "period_to":               str(_fv("period_to", "to") or ""),
                "filing_date":             str(_fv(
                    "تاريخ التقديم", "filing_date", "submission_date") or ""),
                "standard_rated_sales":    float(_safe_decimal(_fv(
                    "إجمالي المبيعات الخاضعة (SAR)",    # actual sample column
                    "المبيعات الخاضعة", "standard_rated_sales") or 0)),
                "output_vat":              float(_safe_decimal(_fv(
                    "ضريبة المخرجات (SAR)",              # actual sample column
                    "ضريبة المخرجات", "output_vat") or 0)),
                "standard_rated_purchases": float(_safe_decimal(_fv(
                    "إجمالي المشتريات الخاضعة (SAR)",   # actual sample column
                    "المشتريات الخاضعة", "standard_rated_purchases") or 0)),
                "input_vat":               float(_safe_decimal(_fv(
                    "ضريبة المدخلات (SAR)",              # actual sample column
                    "ضريبة المدخلات", "input_vat") or 0)),
                "net_vat_payable":         float(_safe_decimal(_fv(
                    "صافي الضريبة المستحقة (SAR)",       # actual sample column
                    "صافي الضريبة المستحقة", "net_vat_payable") or 0)),
                "vat_paid":                float(_safe_decimal(_fv(
                    "مبلغ السداد (SAR)", "vat_paid", "amount_paid") or 0)),
                "ai_summary":              "تم استيراد إقرار ضريبي من الملف المهيكل",
            }

        if doc_type == "fixed_asset":
            assets = []
            for _, row in df.iterrows():
                cost = float(_safe_decimal(_row_get(row,
                    "تكلفة الاقتناء", "تكلفة الاقتناء (SAR)",
                    "cost", "acquisition_cost", "التكلفة") or 0))
                acc_dep = float(_safe_decimal(_row_get(row,
                    "مجمع الإهلاك", "مجمع الإهلاك (SAR)",
                    "accumulated_depreciation", "إهلاك_مجمع") or 0))
                book_val = float(_safe_decimal(_row_get(row,
                    "القيمة الدفترية", "القيمة الدفترية (SAR)",
                    "book_value", "net_book_value", "القيمة_الدفترية") or 0))
                if not book_val and cost:
                    book_val = round(cost - acc_dep, 2)
                asset_name = str(_row_get(row,
                    "اسم الأصل", "asset_name", "name") or "")
                a = {
                    "asset_id":                  str(_row_get(row,
                        "رقم الأصل", "asset_id", "id") or ""),
                    "name":                      asset_name,
                    "category":                  str(_row_get(row,
                        "فئة الأصل",                     # actual sample column
                        "category", "asset_category", "الفئة") or ""),
                    "purchase_date":             str(_row_get(row,
                        "تاريخ الاقتناء",                # actual sample column
                        "purchase_date", "acquisition_date") or ""),
                    "useful_life_years":         float(_safe_decimal(_row_get(row,
                        "العمر الإنتاجي (سنة)",          # actual sample column
                        "العمر الإنتاجي", "useful_life_years", "useful_life") or 0)),
                    "method":                    str(_row_get(row,
                        "طريقة الإهلاك",                 # actual sample column
                        "method", "depreciation_method") or "straight_line"),
                    "annual_depreciation":       float(_safe_decimal(_row_get(row,
                        "الإهلاك السنوي", "annual_depreciation") or 0)),
                    "cost":                      cost,
                    "accumulated_depreciation":  acc_dep,
                    "book_value":                book_val,
                    "is_fully_depreciated":      book_val <= 0 and cost > 0,
                }
                if asset_name or cost:
                    assets.append(a)
            negative_bv = sum(1 for a in assets if a["book_value"] < 0)
            over_dep    = sum(1 for a in assets if a["accumulated_depreciation"] > a["cost"] > 0)
            missing_ids = sum(1 for a in assets if not a["asset_id"])
            ids_seen, dupes = set(), 0
            for a in assets:
                if a["asset_id"]:
                    if a["asset_id"] in ids_seen:
                        dupes += 1
                    ids_seen.add(a["asset_id"])
            return {
                "asset_count":                   len(assets),
                "total_cost":                    _sum_col(df,
                    "تكلفة الاقتناء", "تكلفة الاقتناء (SAR)", "cost"),
                "total_accumulated_depreciation": _sum_col(df,
                    "مجمع الإهلاك", "مجمع الإهلاك (SAR)", "accumulated_depreciation"),
                "total_book_value":               _sum_col(df,
                    "القيمة الدفترية", "القيمة الدفترية (SAR)", "book_value"),
                "assets":                         assets,
                "negative_book_value_count":      negative_bv,
                "over_depreciated_count":         over_dep,
                "missing_asset_id_count":         missing_ids,
                "duplicate_asset_id_count":       dupes,
                "ai_summary":                     f"تم استيراد {len(assets)} أصل ثابت من الملف المهيكل",
            }

        if doc_type == "sales_receipt":
            line_items = []
            for _, row in df.iterrows():
                unit_price = float(_safe_decimal(_row_get(row,
                    "سعر الوحدة (SAR)", "سعر الوحدة",    # actual sample column
                    "unit_price", "price") or 0))
                qty = float(_safe_decimal(_row_get(row,
                    "الكمية", "qty", "quantity") or 1))
                subtotal = float(_safe_decimal(_row_get(row,
                    "إجمالي قبل الضريبة (SAR)", "إجمالي قبل الضريبة",  # actual sample
                    "subtotal", "amount_before_vat") or 0))
                if not subtotal and unit_price:
                    subtotal = round(unit_price * qty, 2)
                vat_amount = float(_safe_decimal(_row_get(row,
                    "ضريبة القيمة (SAR)", "ضريبة القيمة",  # actual sample column
                    "vat_amount", "tax") or 0))
                total = float(_safe_decimal(_row_get(row,
                    "الإجمالي المدفوع (SAR)",              # actual sample column
                    "الإجمالي الكلي (SAR)", "الإجمالي الكلي",
                    "total", "total_amount") or 0))
                if not total:
                    total = round(subtotal + vat_amount, 2)
                item = {
                    "description": str(_row_get(row,
                        "الصنف / الخدمة",               # actual sample column
                        "description", "item", "الوصف", "البند") or ""),
                    "qty":         qty,
                    "unit_price":  unit_price,
                    "subtotal":    subtotal,
                    "vat_rate":    float(_safe_decimal(_row_get(row,
                        "نسبة الضريبة (%)", "نسبة الضريبة",  # actual sample
                        "vat_rate", "tax_rate") or 15)),
                    "vat_amount":  vat_amount,
                    "total":       total,
                }
                if item["description"] or unit_price:
                    line_items.append(item)
            total_subtotal = sum(i["subtotal"]   for i in line_items)
            total_vat      = sum(i["vat_amount"] for i in line_items)
            total_amount   = sum(i["total"]      for i in line_items)
            return {
                "receipt_number": _first_nonempty(_col(df,
                    "رقم الإيصال", "receipt_number")),
                "receipt_date":   _first_nonempty(_col(df,
                    "تاريخ البيع", "receipt_date", "date")),
                "zatca_uuid":     _first_nonempty(_col(df,
                    "رقم الفاتورة ZATCA", "zatca_uuid", "zatca_reference")),
                "has_qr_code":    bool(_first_nonempty(_col(df, "رمز QR", "qr_code"))),
                "subtotal":       round(total_subtotal, 2),
                "vat_amount":     round(total_vat, 2),
                "total_amount":   round(total_amount, 2),
                "line_items":     line_items,
                "currency":       "SAR",
                "ai_summary":     f"تم استيراد {len(line_items)} سطر من الملف المهيكل",
            }

        # Generic fallback: return first row as flat dict
        first = df.iloc[0].to_dict() if len(df) > 0 else {}
        return {"ai_summary": f"تم استيراد {len(df)} سجل", **{k: v for k, v in first.items() if v}}

    except Exception as e:
        logger.warning(f"[pandas extract] {e}")
        return {}


# ── Canonical data persistence ────────────────────────────────────────────────

def _save_canonical(ai_data: dict, doc_type: str, model_name: str, object_id) -> None:
    """
    Persist a DocumentCanonicalData record for any typed document.
    Called immediately after _create_typed_record. Never raises — failure is
    logged and silently swallowed so it cannot interrupt the upload pipeline.
    """
    try:
        from core.services.canonical_mapper import CanonicalMapper
        CanonicalMapper().save_canonical(
            raw_data        = ai_data,
            document_type   = doc_type,
            typed_model_name= model_name,
            typed_object_id = object_id,
        )
    except Exception as exc:
        logger.warning("[canonical] save failed for %s/%s: %s", doc_type, object_id, exc)


# ── Core processing pipeline ───────────────────────────────────────────────────

def _process_typed_document(file_obj, filename: str, doc_type: str, org, user, request=None) -> dict:
    """
    Full pipeline for one non-invoice document:
      1. Save base Document record (and ensure file is written)
      2. Extract text (OCR or parsers)
      3. AI extraction (type-specific prompt)
      4. Create typed model record
      5. Run type-specific validation rules
      6. Return result summary
    """
    start = time.time()
    ext = os.path.splitext(filename)[1].lower()
    file_data = file_obj.read()

    # ── 1. Base Document ────────────────────────────────────────────────────
    base_doc = Document.objects.create(
        organization=org,
        uploaded_by=user,
        file=ContentFile(file_data, name=filename),
        original_filename=filename,
        file_size=len(file_data),
        mime_type=getattr(file_obj, "content_type", ""),
        document_type=doc_type,
        processing_status=Document.ProcessingStatus.PROCESSING,
    )

    # Ensure the file is saved to disk before we try to parse it
    file_path = base_doc.file.path
    if not os.path.exists(file_path):
        # If using remote storage, write to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_data)
            file_path = tmp.name

    # ── 2. Extract Text ─────────────────────────────────────────────────────
    raw_text, ocr_confidence = _run_ocr(file_path, ext)
    img_path = file_path

    if ext == ".pdf":
        imgs = pdf_to_images(img_path)
        if imgs:
            img_path = imgs[0]

    # ── 3. AI Extraction ────────────────────────────────────────────────────
    # For structured files: pandas direct extraction is primary; OpenAI supplements
    if ext in _STRUCTURED_EXTS:
        pandas_data = _extract_from_pandas(file_path, ext, doc_type)
        try:
            ai_data = extract_document(doc_type, img_path, raw_text)
        except Exception as e:
            logger.warning(f"AI extraction failed for {filename}: {e}")
            ai_data = {}
        # Merge: pandas wins for fields it found (non-empty), OpenAI fills the rest
        merged = {**ai_data}
        for k, v in pandas_data.items():
            if v or v == 0:  # keep pandas value if non-empty (or zero for amounts)
                merged[k] = v
        ai_data = merged
    else:
        try:
            ai_data = extract_document(doc_type, img_path, raw_text)
        except Exception as e:
            logger.warning(f"AI extraction failed for {filename}: {e}")
            ai_data = {}

    # ── 4. Create typed model ───────────────────────────────────────────────
    typed_obj = _create_typed_record(doc_type, ai_data, base_doc, org, user)

    # ── 4b. Persist canonical snapshot ──────────────────────────────────────
    _save_canonical(ai_data, doc_type, typed_obj.__class__.__name__, typed_obj.id)

    # ── 5. Validation ───────────────────────────────────────────────────────
    val_result = run_document_validation(doc_type, typed_obj)

    # Merge OpenAI audit results into validation_details
    ai_audit = {
        "validation_results":  ai_data.get("_validation_results", []),
        "anomalies":           ai_data.get("_anomalies", []),
        "compliance_review":   ai_data.get("_compliance_review", {}),
        "recommendations":     ai_data.get("_recommendations", []),
        "field_confidence":    ai_data.get("_field_confidence", {}),
        "overall_confidence":  ai_data.get("_overall_confidence", 1.0),
        "language_detected":   ai_data.get("_language_detected", ""),
        "ai_risk_level":       ai_data.get("_overall_risk_level", ""),
        "rule_details":        val_result["rule_details"],
    }

    # Use the higher risk level between AI audit and rule engine
    ai_risk   = ai_data.get("_overall_risk_level", "low")
    rule_risk = val_result["risk_level"]
    _risk_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    final_risk = ai_risk if _risk_rank.get(ai_risk, 0) >= _risk_rank.get(rule_risk, 0) else rule_risk

    # Update typed object with validation results
    typed_obj.validation_score  = val_result["validation_score"]
    typed_obj.risk_level        = final_risk
    typed_obj.rules_passed      = val_result["rules_passed"]
    typed_obj.rules_failed      = val_result["rules_failed"]
    typed_obj.failed_rule_codes = val_result["failed_rule_codes"]
    typed_obj.validation_details= ai_audit
    typed_obj.ai_summary        = ai_data.get("ai_summary", "")
    typed_obj.audit_status      = (
        "flagged" if final_risk in ["high", "critical"] else "validated"
    )
    typed_obj.save()

    # Update base document status
    base_doc.ocr_confidence    = ocr_confidence
    base_doc.processing_status = Document.ProcessingStatus.COMPLETED
    base_doc.save(update_fields=["ocr_confidence", "processing_status"])

    elapsed = int((time.time() - start) * 1000)

    return {
        "document_id":      str(typed_obj.id),
        "base_document_id": str(base_doc.id),
        "document_type":    doc_type,
        "document_type_ar":    DOCUMENT_TYPE_LABELS_AR.get(doc_type, doc_type),
        "document_type_label": str(DOCUMENT_TYPE_LABELS.get(doc_type, doc_type)),
        "filename":         filename,
        "success":          True,
        "validation_score": val_result["validation_score"],
        "risk_level":       val_result["risk_level"],
        "rules_failed":     val_result["failed_rule_codes"],
        "status":           typed_obj.audit_status,
        "processing_ms":    elapsed,
    }


def _create_typed_record(doc_type: str, ai_data: dict, base_doc, org, user):
    """Instantiate and save the correct typed model from extracted AI data."""

    common = dict(organization=org, document=base_doc, uploaded_by=user)

    def _s(key, default=""):
        """Get string from ai_data, converting None to default."""
        return ai_data.get(key) or default

    if doc_type == "purchase_order":
        return PurchaseOrder.objects.create(
            **common,
            po_number         = _s("po_number"),
            po_date           = _save_date(ai_data.get("po_date")),
            delivery_date     = _save_date(ai_data.get("delivery_date")),
            vendor_name       = _s("vendor_name"),
            vendor_vat_number = _s("vendor_vat_number"),
            vendor_cr_number  = _s("vendor_cr_number"),
            requester_name    = _s("requester_name"),
            department        = _s("department"),
            cost_center       = _s("cost_center"),
            account_code      = _s("account_code"),
            currency          = _s("currency", "SAR"),
            subtotal          = _safe_decimal(ai_data.get("subtotal")),
            vat_amount        = _safe_decimal(ai_data.get("vat_amount")),
            total_amount      = _safe_decimal(ai_data.get("total_amount")),
            line_items        = ai_data.get("line_items") or [],
        )

    if doc_type == "bank_statement":
        return BankStatement.objects.create(
            **common,
            bank_name              = _s("bank_name"),
            account_number         = _s("account_number"),
            account_name           = _s("account_name"),
            iban                   = _s("iban"),
            currency               = _s("currency", "SAR"),
            statement_period_from  = _save_date(ai_data.get("statement_period_from")),
            statement_period_to    = _save_date(ai_data.get("statement_period_to")),
            opening_balance        = _safe_decimal(ai_data.get("opening_balance")),
            closing_balance        = _safe_decimal(ai_data.get("closing_balance")),
            total_credits          = _safe_decimal(ai_data.get("total_credits")),
            total_debits           = _safe_decimal(ai_data.get("total_debits")),
            calculated_closing     = _safe_decimal(ai_data.get("calculated_closing")),
            balance_matches        = bool(ai_data.get("balance_matches", True)),
            transaction_count      = int(ai_data.get("transaction_count") or 0),
            transactions           = ai_data.get("transactions") or [],
        )

    if doc_type == "payroll":
        return PayrollSheet.objects.create(
            **common,
            payroll_period_from   = _save_date(ai_data.get("payroll_period_from")),
            payroll_period_to     = _save_date(ai_data.get("payroll_period_to")),
            payment_date          = _save_date(ai_data.get("payment_date")),
            department            = _s("department"),
            company_name          = _s("company_name"),
            currency              = _s("currency", "SAR"),
            employee_count        = int(ai_data.get("employee_count") or 0),
            total_gross_salary    = _safe_decimal(ai_data.get("total_gross_salary")),
            total_allowances      = _safe_decimal(ai_data.get("total_allowances")),
            total_deductions      = _safe_decimal(ai_data.get("total_deductions")),
            total_gosi            = _safe_decimal(ai_data.get("total_gosi")),
            total_net_salary      = _safe_decimal(ai_data.get("total_net_salary")),
            employees             = ai_data.get("employees") or [],
            duplicate_employee_ids= ai_data.get("duplicate_employee_ids") or [],
            calculation_errors    = ai_data.get("calculation_errors") or [],
        )

    if doc_type == "expense_report":
        return ExpenseReport.objects.create(
            **common,
            report_number        = _s("report_number"),
            employee_name        = _s("employee_name"),
            employee_id          = _s("employee_id"),
            department           = _s("department"),
            report_period_from   = _save_date(ai_data.get("report_period_from")),
            report_period_to     = _save_date(ai_data.get("report_period_to")),
            submitted_date       = _save_date(ai_data.get("submitted_date")),
            currency             = _s("currency", "SAR"),
            purpose              = _s("purpose"),
            total_claimed        = _safe_decimal(ai_data.get("total_claimed")),
            vat_included         = _safe_decimal(ai_data.get("vat_included")),
            expense_lines        = ai_data.get("expense_lines") or [],
            missing_receipts_count = int(ai_data.get("missing_receipts_count") or 0),
        )

    if doc_type in ("vat_return", "tax_declaration"):
        return VATReturn.objects.create(
            **common,
            taxpayer_name            = _s("taxpayer_name"),
            vat_number               = _s("vat_number"),
            cr_number                = _s("cr_number"),
            period_from              = _save_date(ai_data.get("period_from")),
            period_to                = _save_date(ai_data.get("period_to")),
            filing_date              = _save_date(ai_data.get("filing_date")),
            due_date                 = _save_date(ai_data.get("due_date")),
            zatca_reference          = _s("zatca_reference"),
            standard_rated_sales     = _safe_decimal(ai_data.get("standard_rated_sales")),
            zero_rated_sales         = _safe_decimal(ai_data.get("zero_rated_sales")),
            exempt_sales             = _safe_decimal(ai_data.get("exempt_sales")),
            total_sales              = _safe_decimal(ai_data.get("total_sales")),
            output_vat               = _safe_decimal(ai_data.get("output_vat")),
            standard_rated_purchases = _safe_decimal(ai_data.get("standard_rated_purchases")),
            input_vat                = _safe_decimal(ai_data.get("input_vat")),
            net_vat_payable          = _safe_decimal(ai_data.get("net_vat_payable")),
            vat_paid                 = _safe_decimal(ai_data.get("vat_paid")),
            calculated_output_vat    = _safe_decimal(ai_data.get("calculated_output_vat")),
            calculated_net           = _safe_decimal(ai_data.get("calculated_net")),
            output_discrepancy       = _safe_decimal(ai_data.get("output_discrepancy")),
            is_late_filing           = bool(ai_data.get("is_late_filing", False)),
            late_days                = int(ai_data.get("late_days") or 0),
        )

    if doc_type == "fixed_asset":
        return FixedAsset.objects.create(
            **common,
            register_date                    = _save_date(ai_data.get("register_date")),
            company_name                     = _s("company_name"),
            department                       = _s("department"),
            fiscal_year                      = _s("fiscal_year"),
            total_cost                       = _safe_decimal(ai_data.get("total_cost")),
            total_accumulated_depreciation   = _safe_decimal(ai_data.get("total_accumulated_depreciation")),
            total_book_value                 = _safe_decimal(ai_data.get("total_book_value")),
            asset_count                      = int(ai_data.get("asset_count") or 0),
            assets                           = ai_data.get("assets") or [],
            negative_book_value_count        = int(ai_data.get("negative_book_value_count") or 0),
            over_depreciated_count           = int(ai_data.get("over_depreciated_count") or 0),
            missing_asset_id_count           = int(ai_data.get("missing_asset_id_count") or 0),
            duplicate_asset_id_count         = int(ai_data.get("duplicate_asset_id_count") or 0),
        )

    if doc_type == "sales_receipt":
        return SalesReceipt.objects.create(
            **common,
            receipt_number      = _s("receipt_number"),
            receipt_date        = _save_date(ai_data.get("receipt_date")),
            receipt_type        = _s("receipt_type", "simplified"),
            seller_name         = _s("seller_name"),
            seller_vat_number   = _s("seller_vat_number"),
            customer_name       = _s("customer_name"),
            customer_vat_number = _s("customer_vat_number"),
            currency            = _s("currency", "SAR"),
            subtotal            = _safe_decimal(ai_data.get("subtotal")),
            vat_rate            = _safe_decimal(ai_data.get("vat_rate", 15)),
            vat_amount          = _safe_decimal(ai_data.get("vat_amount")),
            total_amount        = _safe_decimal(ai_data.get("total_amount")),
            line_items          = ai_data.get("line_items") or [],
            has_qr_code         = bool(ai_data.get("has_qr_code")),
            qr_code_valid       = bool(ai_data.get("qr_code_valid")),
            zatca_uuid          = _s("zatca_uuid"),
            file_hash           = _s("file_hash"),
        )

    raise ValueError(f"Unknown document type: {doc_type}")


# ══════════════════════════════════════════════════════════════════════════════
# Upload View
# ══════════════════════════════════════════════════════════════════════════════

class TypedDocumentUploadView(APIView):
    """
    Universal upload endpoint for all 7 financial document types.
    Detects type from `document_type` field, routes to correct pipeline.
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Documents"],
        summary="رفع وتحليل الوثائق المالية (أوامر شراء / كشوف بنكية / رواتب / مصروفات / ضريبة / أصول / إيصالات)",
        request={"type": "object", "properties": {
            "files": {"type": "array", "items": {"type": "string", "format": "binary"}},
            "document_type": {"type": "string", "enum": VALID_TYPES},
        }},
    )
    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "المستخدم لا ينتمي لمؤسسة."}, status=400)

        doc_type = request.data.get("document_type", "")
        if doc_type not in VALID_TYPES:
            return Response({"error": f"نوع الوثيقة غير صحيح. الأنواع المتاحة: {VALID_TYPES}"}, status=400)

        # Forward invoices to invoice upload endpoint
        if doc_type == "invoice":
            return Response({"error": "للفواتير استخدم: POST /api/v1/invoices/upload/"}, status=400)

        uploaded_files = request.FILES.getlist("files") or (
            [request.FILES["file"]] if "file" in request.FILES else []
        )
        if not uploaded_files:
            return Response({"error": "لم يتم رفع أي ملفات."}, status=400)

        results, errors = [], []

        for f in uploaded_files:
            ext = os.path.splitext(f.name)[1].lower()
            try:
                if ext == ".zip":
                    zr, ze = _process_zip_typed(f, doc_type, org, request.user, request)
                    results.extend(zr); errors.extend(ze)
                elif ext in ALLOWED_EXT:
                    r = _process_typed_document(f, f.name, doc_type, org, request.user, request)
                    results.append(r)
                else:
                    errors.append({"filename": f.name, "error": f"نوع الملف غير مدعوم: {ext}"})
            except Exception as e:
                logger.exception(f"Upload failed for {f.name}: {e}")
                errors.append({
                    "filename": f.name, 
                    "error": _("Processing error: %(detail)s") % {"detail": str(e)[:200]},
                })

        log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, doc_type, "",
                   {"files": len(results), "errors": len(errors)})

        return Response({
            "document_type":    doc_type,
            "document_type_ar":    DOCUMENT_TYPE_LABELS_AR.get(doc_type),
            "document_type_label": str(DOCUMENT_TYPE_LABELS.get(doc_type, doc_type)),
            "total":    len(results) + len(errors),
            "processed": len(results),
            "failed":   len(errors),
            "results":  results,
            "errors":   errors,
        }, status=status.HTTP_201_CREATED)


def _process_zip_typed(zip_file, doc_type, org, user, request):
    results, errors = [], []
    try:
        # Validate ZIP before extraction (bomb detection)
        zip_file.seek(0)
        try:
            validate_zip_bomb(zip_file)
        except ZipValidationError as e:
            errors.append({"filename": zip_file.name, "error": f"فشل التحقق من ZIP: {str(e)}"})
            return results, errors
        
        zip_file.seek(0)
        with zipfile.ZipFile(io.BytesIO(zip_file.read()), "r") as zf:
            for member in zf.infolist():
                if member.is_dir(): continue
                name = os.path.basename(member.filename)
                ext  = os.path.splitext(name)[1].lower()
                if ext not in {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif"}: continue
                try:
                    data = zf.read(member)
                    fl   = io.BytesIO(data); fl.name = name
                    r = _process_typed_document(fl, name, doc_type, org, user, request)
                    results.append(r)
                except Exception as e:
                    errors.append({"filename": name, "error": str(e)})
    except zipfile.BadZipFile:
        errors.append({"filename": zip_file.name, "error": "ملف ZIP غير صالح"})
    except ZipValidationError as e:
        errors.append({"filename": zip_file.name, "error": str(e)})
    return results, errors


# ══════════════════════════════════════════════════════════════════════════════
# Stats View
# ══════════════════════════════════════════════════════════════════════════════

class DocumentStatsView(APIView):
    """Cross-type document statistics for the organisation."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Documents"], summary="إحصائيات الوثائق المالية حسب النوع")
    def get(self, request):
        org = request.user.organization

        def _stats(Model, amount_field=None):
            qs = Model.objects.filter(organization=org)
            agg = {"total": qs.count(), "flagged": qs.filter(audit_status="flagged").count(),
                   "validated": qs.filter(audit_status="validated").count(),
                   "approved": qs.filter(audit_status="approved").count()}
            if amount_field:
                agg["total_amount"] = float(qs.aggregate(s=Sum(amount_field))["s"] or 0)
            return agg

        return Response({
            "purchase_orders":  _stats(PurchaseOrder,  "total_amount"),
            "bank_statements":  _stats(BankStatement),
            "payroll_sheets":   _stats(PayrollSheet,   "total_net_salary"),
            "expense_reports":  _stats(ExpenseReport,  "total_claimed"),
            "vat_returns":      _stats(VATReturn,      "net_vat_payable"),
            "fixed_assets":     _stats(FixedAsset,     "total_cost"),
            "sales_receipts":   _stats(SalesReceipt,   "total_amount"),
        })


# ══════════════════════════════════════════════════════════════════════════════
# Generic List/Detail base classes
# ══════════════════════════════════════════════════════════════════════════════

class _TypedListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    model = None
    list_serializer_class = None
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['audit_status', 'risk_level', 'created_at']
    search_fields = ['original_filename', 'vendor_name', 'ocr_text']
    ordering_fields = ['created_at', 'risk_level', 'audit_status']
    ordering = ['-created_at']

    def get_serializer_class(self):
        return self.list_serializer_class

    def get_queryset(self):
        qs = self.model.objects.filter(organization=self.request.user.organization)
        p = self.request.query_params
        if v := p.get("status"):     qs = qs.filter(audit_status=v)
        if v := p.get("risk_level"): qs = qs.filter(risk_level=v)
        return qs.order_by("-created_at")


class _TypedDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    model = None
    detail_serializer_class = None

    def get_serializer_class(self):
        return self.detail_serializer_class

    def get_queryset(self):
        return self.model.objects.filter(organization=self.request.user.organization)


# ══════════════════════════════════════════════════════════════════════════════
# Per-type views
# ══════════════════════════════════════════════════════════════════════════════

class PurchaseOrderListView(_TypedListView):
    model = PurchaseOrder
    list_serializer_class = PurchaseOrderListSerializer

    @extend_schema(tags=["Purchase Orders"], summary="قائمة أوامر الشراء")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class PurchaseOrderDetailView(_TypedDetailView):
    model = PurchaseOrder
    detail_serializer_class = PurchaseOrderSerializer

    @extend_schema(tags=["Purchase Orders"], summary="تفاصيل أمر الشراء")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class PurchaseOrderApproveView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Purchase Orders"], summary="اعتماد أو رفض أمر الشراء",
        request={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["approve", "reject"]},
            "reason": {"type": "string"}}})
    def post(self, request, pk):
        try:
            po = PurchaseOrder.objects.get(pk=pk, organization=request.user.organization)
        except PurchaseOrder.DoesNotExist:
            return Response({"error": "أمر الشراء غير موجود."}, status=404)

        action = request.data.get("action")
        if action == "approve":
            po.audit_status = "approved"
            po.approval_status = PurchaseOrder.ApprovalStatus.APPROVED
            po.approved_by = request.user
            po.reviewed_by = request.user
            po.reviewed_at = timezone.now()
        elif action == "reject":
            if not request.data.get("reason"):
                return Response({"error": "سبب الرفض مطلوب."}, status=400)
            po.audit_status = "rejected"
            po.approval_status = PurchaseOrder.ApprovalStatus.REJECTED
        else:
            return Response({"error": "action يجب أن يكون approve أو reject"}, status=400)

        po.save()
        return Response({"id": str(po.id), "status": po.audit_status})


class BankStatementListView(_TypedListView):
    model = BankStatement
    list_serializer_class = BankStatementListSerializer

    @extend_schema(tags=["Bank Statements"], summary="قائمة كشوف الحساب البنكي")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class BankStatementDetailView(_TypedDetailView):
    model = BankStatement
    detail_serializer_class = BankStatementSerializer

    @extend_schema(tags=["Bank Statements"], summary="تفاصيل كشف الحساب البنكي")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class PayrollListView(_TypedListView):
    model = PayrollSheet
    list_serializer_class = PayrollSheetListSerializer

    @extend_schema(tags=["Payroll"], summary="قائمة كشوف الرواتب")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class PayrollDetailView(_TypedDetailView):
    model = PayrollSheet
    detail_serializer_class = PayrollSheetSerializer

    @extend_schema(tags=["Payroll"], summary="تفاصيل كشف الرواتب")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class ExpenseReportListView(_TypedListView):
    model = ExpenseReport
    list_serializer_class = ExpenseReportListSerializer

    @extend_schema(tags=["Expense Reports"], summary="قائمة تقارير المصروفات")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class ExpenseReportDetailView(_TypedDetailView):
    model = ExpenseReport
    detail_serializer_class = ExpenseReportSerializer

    @extend_schema(tags=["Expense Reports"], summary="تفاصيل تقرير المصروفات")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class VATReturnListView(_TypedListView):
    model = VATReturn
    list_serializer_class = VATReturnListSerializer

    @extend_schema(tags=["VAT Returns"], summary="قائمة الإقرارات الضريبية")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class VATReturnDetailView(_TypedDetailView):
    model = VATReturn
    detail_serializer_class = VATReturnSerializer

    @extend_schema(tags=["VAT Returns"], summary="تفاصيل الإقرار الضريبي")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class FixedAssetListView(_TypedListView):
    model = FixedAsset
    list_serializer_class = FixedAssetListSerializer

    @extend_schema(tags=["Fixed Assets"], summary="قائمة سجلات الأصول الثابتة")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class FixedAssetDetailView(_TypedDetailView):
    model = FixedAsset
    detail_serializer_class = FixedAssetSerializer

    @extend_schema(tags=["Fixed Assets"], summary="تفاصيل سجل الأصول الثابتة")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class SalesReceiptListView(_TypedListView):
    model = SalesReceipt
    list_serializer_class = SalesReceiptListSerializer

    @extend_schema(tags=["Sales Receipts"], summary="قائمة إيصالات البيع")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)


class SalesReceiptDetailView(_TypedDetailView):
    model = SalesReceipt
    detail_serializer_class = SalesReceiptSerializer

    @extend_schema(tags=["Sales Receipts"], summary="تفاصيل إيصال البيع")
    def get(self, request, *args, **kwargs): return super().get(request, *args, **kwargs)
