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


def _col(df, *candidates):
    """Return the first matching column Series by case-insensitive name, or None."""
    cols_lower = {c.lower(): c for c in df.columns}
    for name in candidates:
        real = cols_lower.get(name.lower())
        if real is not None:
            return df[real]
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
                item = {
                    "description": str(row.get("description") or row.get("item") or row.get("الوصف") or ""),
                    "qty":         float(_safe_decimal(row.get("qty") or row.get("quantity") or row.get("الكمية") or 0)),
                    "unit_price":  float(_safe_decimal(row.get("unit_price") or row.get("price") or row.get("سعر_الوحدة") or 0)),
                    "total":       float(_safe_decimal(row.get("total") or row.get("amount") or row.get("المبلغ") or 0)),
                }
                if any(v for v in item.values() if v):
                    line_items.append(item)

            total = _sum_col(df, "total", "amount", "total_amount", "المبلغ", "الإجمالي")
            vat   = _sum_col(df, "vat", "tax", "vat_amount", "ضريبة")
            return {
                "po_number":    _first_nonempty(_col(df, "po_number", "reference", "ref", "رقم_الأمر", "المرجع")),
                "po_date":      _first_nonempty(_col(df, "date", "po_date", "invoice_date", "تاريخ")),
                "vendor_name":  _first_nonempty(_col(df, "vendor", "vendor_name", "supplier", "المورد")),
                "currency":     _first_nonempty(_col(df, "currency", "ccy", "العملة")) or "SAR",
                "total_amount": total,
                "vat_amount":   vat,
                "subtotal":     round(total - vat, 2),
                "line_items":   line_items,
                "ai_summary":   f"تم استيراد {len(df)} سجل من الملف المهيكل",
            }

        if doc_type == "bank_statement":
            transactions = []
            for _, row in df.iterrows():
                debit  = float(_safe_decimal(row.get("debit") or row.get("withdrawals") or row.get("المدين") or 0))
                credit = float(_safe_decimal(row.get("credit") or row.get("deposits") or row.get("الدائن") or 0))
                amt    = float(_safe_decimal(row.get("amount") or row.get("المبلغ") or 0))
                if not debit and not credit and amt:
                    if amt < 0:
                        debit = abs(amt)
                    else:
                        credit = amt
                t = {
                    "date":        str(row.get("date") or row.get("txn_date") or row.get("تاريخ") or ""),
                    "description": str(row.get("description") or row.get("narration") or row.get("البيان") or ""),
                    "debit":       debit,
                    "credit":      credit,
                    "balance":     float(_safe_decimal(row.get("balance") or row.get("الرصيد") or 0)),
                    "ref":         str(row.get("reference") or row.get("ref") or row.get("المرجع") or ""),
                }
                transactions.append(t)
            credits = sum(t["credit"] for t in transactions)
            debits  = sum(t["debit"]  for t in transactions)
            return {
                "transaction_count": len(transactions),
                "total_credits":     round(credits, 2),
                "total_debits":      round(debits, 2),
                "transactions":      transactions,
                "currency":          _first_nonempty(_col(df, "currency", "العملة")) or "SAR",
                "ai_summary":        f"تم استيراد {len(transactions)} معاملة من الملف المهيكل",
            }

        if doc_type == "payroll":
            employees = []
            for _, row in df.iterrows():
                e = {
                    "name":        str(row.get("name") or row.get("employee_name") or row.get("الاسم") or ""),
                    "id":          str(row.get("id") or row.get("employee_id") or row.get("رقم_الموظف") or ""),
                    "gross":       float(_safe_decimal(row.get("gross") or row.get("gross_salary") or row.get("الراتب_الأساسي") or 0)),
                    "net":         float(_safe_decimal(row.get("net") or row.get("net_salary") or row.get("صافي_الراتب") or 0)),
                    "allowances":  float(_safe_decimal(row.get("allowances") or row.get("البدلات") or 0)),
                    "deductions":  float(_safe_decimal(row.get("deductions") or row.get("الخصومات") or 0)),
                    "gosi":        float(_safe_decimal(row.get("gosi") or 0)),
                    "bank_account": str(row.get("bank_account") or row.get("حساب_بنكي") or ""),
                }
                if e["name"] or e["gross"]:
                    employees.append(e)
            return {
                "employee_count":     len(employees),
                "total_gross_salary": _sum_col(df, "gross", "gross_salary", "الراتب_الأساسي"),
                "total_net_salary":   _sum_col(df, "net", "net_salary", "صافي_الراتب"),
                "total_allowances":   _sum_col(df, "allowances", "البدلات"),
                "total_deductions":   _sum_col(df, "deductions", "الخصومات"),
                "total_gosi":         _sum_col(df, "gosi"),
                "employees":          employees,
                "currency":           "SAR",
                "ai_summary":         f"تم استيراد {len(employees)} موظف من الملف المهيكل",
            }

        if doc_type == "expense_report":
            lines = []
            for _, row in df.iterrows():
                l = {
                    "date":             str(row.get("date") or row.get("expense_date") or row.get("تاريخ") or ""),
                    "description":      str(row.get("description") or row.get("purpose") or row.get("الوصف") or ""),
                    "amount":           float(_safe_decimal(row.get("amount") or row.get("المبلغ") or 0)),
                    "category":         str(row.get("category") or row.get("type") or row.get("الفئة") or "other"),
                    "receipt_attached": True,
                    "receipt_number":   str(row.get("receipt_number") or row.get("رقم_الإيصال") or ""),
                }
                if l["description"] or l["amount"]:
                    lines.append(l)
            return {
                "total_claimed": _sum_col(df, "amount", "المبلغ"),
                "expense_lines": lines,
                "currency":      _first_nonempty(_col(df, "currency", "العملة")) or "SAR",
                "ai_summary":    f"تم استيراد {len(lines)} مصروف من الملف المهيكل",
            }

        # Generic fallback: return first row as flat dict
        first = df.iloc[0].to_dict() if len(df) > 0 else {}
        return {"ai_summary": f"تم استيراد {len(df)} سجل", **{k: v for k, v in first.items() if v}}

    except Exception as e:
        logger.warning(f"[pandas extract] {e}")
        return {}


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
        "document_type_ar": DOCUMENT_TYPE_LABELS_AR.get(doc_type, doc_type),
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

    if doc_type == "purchase_order":
        return PurchaseOrder.objects.create(
            **common,
            po_number         = ai_data.get("po_number", ""),
            po_date           = _save_date(ai_data.get("po_date")),
            delivery_date     = _save_date(ai_data.get("delivery_date")),
            vendor_name       = ai_data.get("vendor_name", ""),
            vendor_vat_number = ai_data.get("vendor_vat_number", ""),
            vendor_cr_number  = ai_data.get("vendor_cr_number", ""),
            requester_name    = ai_data.get("requester_name", ""),
            department        = ai_data.get("department", ""),
            cost_center       = ai_data.get("cost_center", ""),
            account_code      = ai_data.get("account_code", ""),
            currency          = ai_data.get("currency", "SAR"),
            subtotal          = _safe_decimal(ai_data.get("subtotal")),
            vat_amount        = _safe_decimal(ai_data.get("vat_amount")),
            total_amount      = _safe_decimal(ai_data.get("total_amount")),
            line_items        = ai_data.get("line_items", []),
        )

    if doc_type == "bank_statement":
        return BankStatement.objects.create(
            **common,
            bank_name              = ai_data.get("bank_name", ""),
            account_number         = ai_data.get("account_number", ""),
            account_name           = ai_data.get("account_name", ""),
            iban                   = ai_data.get("iban", ""),
            currency               = ai_data.get("currency", "SAR"),
            statement_period_from  = _save_date(ai_data.get("statement_period_from")),
            statement_period_to    = _save_date(ai_data.get("statement_period_to")),
            opening_balance        = _safe_decimal(ai_data.get("opening_balance")),
            closing_balance        = _safe_decimal(ai_data.get("closing_balance")),
            total_credits          = _safe_decimal(ai_data.get("total_credits")),
            total_debits           = _safe_decimal(ai_data.get("total_debits")),
            calculated_closing     = _safe_decimal(ai_data.get("calculated_closing")),
            balance_matches        = bool(ai_data.get("balance_matches", True)),
            transaction_count      = int(ai_data.get("transaction_count") or 0),
            transactions           = ai_data.get("transactions", []),
        )

    if doc_type == "payroll":
        return PayrollSheet.objects.create(
            **common,
            payroll_period_from   = _save_date(ai_data.get("payroll_period_from")),
            payroll_period_to     = _save_date(ai_data.get("payroll_period_to")),
            payment_date          = _save_date(ai_data.get("payment_date")),
            department            = ai_data.get("department", ""),
            company_name          = ai_data.get("company_name", ""),
            currency              = ai_data.get("currency", "SAR"),
            employee_count        = int(ai_data.get("employee_count") or 0),
            total_gross_salary    = _safe_decimal(ai_data.get("total_gross_salary")),
            total_allowances      = _safe_decimal(ai_data.get("total_allowances")),
            total_deductions      = _safe_decimal(ai_data.get("total_deductions")),
            total_gosi            = _safe_decimal(ai_data.get("total_gosi")),
            total_net_salary      = _safe_decimal(ai_data.get("total_net_salary")),
            employees             = ai_data.get("employees", []),
            duplicate_employee_ids= ai_data.get("duplicate_employee_ids", []),
            calculation_errors    = ai_data.get("calculation_errors", []),
        )

    if doc_type == "expense_report":
        return ExpenseReport.objects.create(
            **common,
            report_number        = ai_data.get("report_number", ""),
            employee_name        = ai_data.get("employee_name", ""),
            employee_id          = ai_data.get("employee_id", ""),
            department           = ai_data.get("department", ""),
            report_period_from   = _save_date(ai_data.get("report_period_from")),
            report_period_to     = _save_date(ai_data.get("report_period_to")),
            submitted_date       = _save_date(ai_data.get("submitted_date")),
            currency             = ai_data.get("currency", "SAR"),
            purpose              = ai_data.get("purpose", ""),
            total_claimed        = _safe_decimal(ai_data.get("total_claimed")),
            vat_included         = _safe_decimal(ai_data.get("vat_included")),
            expense_lines        = ai_data.get("expense_lines", []),
            missing_receipts_count = int(ai_data.get("missing_receipts_count") or 0),
        )

    if doc_type == "vat_return":
        return VATReturn.objects.create(
            **common,
            taxpayer_name            = ai_data.get("taxpayer_name", ""),
            vat_number               = ai_data.get("vat_number", ""),
            cr_number                = ai_data.get("cr_number", ""),
            period_from              = _save_date(ai_data.get("period_from")),
            period_to                = _save_date(ai_data.get("period_to")),
            filing_date              = _save_date(ai_data.get("filing_date")),
            due_date                 = _save_date(ai_data.get("due_date")),
            zatca_reference          = ai_data.get("zatca_reference", ""),
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
            company_name                     = ai_data.get("company_name", ""),
            department                       = ai_data.get("department", ""),
            fiscal_year                      = ai_data.get("fiscal_year", ""),
            total_cost                       = _safe_decimal(ai_data.get("total_cost")),
            total_accumulated_depreciation   = _safe_decimal(ai_data.get("total_accumulated_depreciation")),
            total_book_value                 = _safe_decimal(ai_data.get("total_book_value")),
            asset_count                      = int(ai_data.get("asset_count") or 0),
            assets                           = ai_data.get("assets", []),
            negative_book_value_count        = int(ai_data.get("negative_book_value_count") or 0),
            over_depreciated_count           = int(ai_data.get("over_depreciated_count") or 0),
            missing_asset_id_count           = int(ai_data.get("missing_asset_id_count") or 0),
            duplicate_asset_id_count         = int(ai_data.get("duplicate_asset_id_count") or 0),
        )

    if doc_type == "sales_receipt":
        return SalesReceipt.objects.create(
            **common,
            receipt_number      = ai_data.get("receipt_number", ""),
            receipt_date        = _save_date(ai_data.get("receipt_date")),
            receipt_type        = ai_data.get("receipt_type", "simplified"),
            seller_name         = ai_data.get("seller_name", ""),
            seller_vat_number   = ai_data.get("seller_vat_number", ""),
            customer_name       = ai_data.get("customer_name", ""),
            customer_vat_number = ai_data.get("customer_vat_number", ""),
            currency            = ai_data.get("currency", "SAR"),
            subtotal            = _safe_decimal(ai_data.get("subtotal")),
            vat_rate            = _safe_decimal(ai_data.get("vat_rate", 15)),
            vat_amount          = _safe_decimal(ai_data.get("vat_amount")),
            total_amount        = _safe_decimal(ai_data.get("total_amount")),
            line_items          = ai_data.get("line_items", []),
            has_qr_code         = bool(ai_data.get("has_qr_code")),
            qr_code_valid       = bool(ai_data.get("qr_code_valid")),
            zatca_uuid          = ai_data.get("zatca_uuid", ""),
            file_hash           = ai_data.get("file_hash", ""),
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
                    "error": f"خطأ في المعالجة: {str(e)[:200]}"
                })

        log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, doc_type, "",
                   {"files": len(results), "errors": len(errors)})

        return Response({
            "document_type":    doc_type,
            "document_type_ar": DOCUMENT_TYPE_LABELS_AR.get(doc_type),
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
