"""
Invoice Auditing Views
Supports: single file, multiple files, structured data files, ZIP archive upload.
Runs all 30 validation rules + AI analysis on each invoice.
"""

import csv
import io
import json
import logging
import math
import os
import re
import time
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.permissions import IsSeniorAuditorOrAbove, IsOwnOrganization
from core.services.invoice_ai_service import analyze_invoice_risk, extract_invoice_with_ai
from core.services.invoice_validator import RULES, TOTAL_RULES, compute_file_hash, run_all_rules
from core.services.ocr_service import extract_text_tesseract, pdf_to_images
from core.utils.audit import log_action
from apps.authentication.models import AuditLog

from .models import (
    Invoice, InvoiceAuditEvent, InvoiceBatch, InvoiceValidationResult, VendorProfile
)
from .serializers import (
    InvoiceBatchSerializer, InvoiceDetailSerializer,
    InvoiceListSerializer, InvoiceValidationResultSerializer,
    VendorProfileSerializer,
)

logger = logging.getLogger("finai")

IMAGE_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif"}
STRUCTURED_EXT = {".csv", ".xlsx", ".xls", ".json"}
ZIP_EXT = {".zip"}

ALLOWED_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "application/zip",
    "application/x-zip-compressed",
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/json",
    "text/json",
}
ALLOWED_EXT = IMAGE_EXT | STRUCTURED_EXT | ZIP_EXT

_FIELD_ALIAS_GROUPS = {
    "invoice_number": {"invoice_no", "invoice_id", "number", "reference", "ref", "رقم الفاتورة", "رقم_الفاتورة"},
    "invoice_date": {"date", "issued_at", "تاريخ الفاتورة", "تاريخ_الفاتورة", "التاريخ"},
    "due_date": {"due", "due_date_at", "تاريخ الاستحقاق", "تاريخ_الاستحقاق"},
    "vendor_name": {"vendor", "vendor_name_en", "supplier", "supplier_name", "merchant_name", "المورد", "اسم المورد", "اسم_المورد"},
    "vendor_name_ar": {"vendor_ar", "vendor_name_arabic", "اسم المورد بالعربية", "اسم_المورد_بالعربية"},
    "vendor_vat_number": {"vat_number", "vendor_vat", "vendor_tax_number", "supplier_vat", "vat_no", "الرقم الضريبي", "الرقم_الضريبي", "الرقم الضريبي للمورد", "الرقم_الضريبي_للمورد"},
    "vendor_cr_number": {"cr_number", "commercial_registration", "registration_number", "السجل التجاري", "السجل_التجاري", "رقم السجل التجاري", "رقم_السجل_التجاري"},
    "vendor_address": {"address", "vendor_location", "عنوان المورد", "عنوان_المورد"},
    "vendor_phone": {"phone", "vendor_mobile", "هاتف المورد", "هاتف_المورد"},
    "customer_name": {"customer", "client_name", "اسم العميل", "اسم_العميل"},
    "customer_vat_number": {"customer_vat", "customer_tax_number", "الرقم الضريبي للعميل", "الرقم_الضريبي_للعميل"},
    "currency": {"currency_code", "عملة", "العملة"},
    "subtotal": {"sub_total", "amount_before_tax", "before_tax", "net_amount", "subtotal_amount", "المبلغ قبل الضريبة", "المبلغ_قبل_الضريبة", "الإجمالي قبل الضريبة", "الإجمالي_قبل_الضريبة"},
    "vat_rate": {"tax_rate", "vat_percent", "vat_pct", "نسبة الضريبة", "نسبة_الضريبة", "نسبة القيمة المضافة", "نسبة_القيمة_المضافة"},
    "vat_amount": {"tax_amount", "vat_value", "vat", "tax", "قيمة الضريبة", "قيمة_الضريبة", "مبلغ الضريبة", "مبلغ_الضريبة"},
    "discount": {"discount_amount", "الخصم", "قيمة الخصم", "قيمة_الخصم"},
    "total_amount": {"amount", "total", "grand_total", "invoice_total", "المبلغ", "الإجمالي", "المبلغ الإجمالي", "المبلغ_الإجمالي", "الإجمالي_النهائي"},
    "line_items": {"items", "details", "تفاصيل البنود", "تفاصيل_البنود", "البنود"},
    "cost_center": {"costcentre", "cost_centre", "مركز التكلفة", "مركز_التكلفة"},
    "account_code": {"account", "gl_code", "ledger_code", "رمز الحساب", "رمز_الحساب", "الحساب"},
    "budget_code": {"budget", "budget_ref", "رمز الميزانية", "رمز_الميزانية"},
    "department": {"dept", "القسم"},
    "has_qr_code": {"qr", "qr_code", "has_qr", "يوجد qr", "يوجد_qr", "يوجد رمز qr", "يوجد_رمز_qr"},
    "qr_code_valid": {"qr_valid", "valid_qr", "صلاحية_qr", "qr_صالح"},
    "is_clear": {"clear", "document_clear", "واضح", "واضحة"},
    "has_alterations": {"tampered", "altered", "modified", "به تلاعب", "به_تلاعب"},
    "language": {"lang", "اللغة"},
    "ai_summary": {"summary", "notes", "ملاحظات", "ملخص"},
}

_LINE_ITEM_ALIAS_GROUPS = {
    "description": {"description", "details", "item", "item_description", "line_description", "narration"},
    "quantity": {"qty", "quantity", "count"},
    "unit_price": {"unit_price", "unitprice", "price", "unit_cost", "rate"},
    "total": {"line_total", "linetotal", "total", "amount", "value"},
    "vat_rate": {"vat_rate", "vatrate", "tax_rate", "taxrate"},
}


def _normalize_alias_key(value):
    return re.sub(r"[^0-9a-zA-Z\u0600-\u06FF]+", "", str(value or "").strip().lower())


STRUCTURED_FIELD_ALIASES = {}
for canonical, aliases in _FIELD_ALIAS_GROUPS.items():
    STRUCTURED_FIELD_ALIASES[_normalize_alias_key(canonical)] = canonical
    for alias in aliases:
        STRUCTURED_FIELD_ALIASES[_normalize_alias_key(alias)] = canonical

LINE_ITEM_FIELD_ALIASES = {}
for canonical, aliases in _LINE_ITEM_ALIAS_GROUPS.items():
    LINE_ITEM_FIELD_ALIASES[_normalize_alias_key(canonical)] = canonical
    for alias in aliases:
        LINE_ITEM_FIELD_ALIASES[_normalize_alias_key(alias)] = canonical


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")


def _save_audit_event(invoice, user, event_type, description="", before=None, after=None, request=None):
    InvoiceAuditEvent.objects.create(
        invoice=invoice,
        user=user,
        event_type=event_type,
        description=description,
        before_data=before or {},
        after_data=after or {},
        ip_address=_get_client_ip(request) if request else None,
    )


def _is_blank_value(value):
    if value is None:
        return True
    if isinstance(value, Decimal) and value.is_nan():
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "none", "null", "nat"}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _first_non_empty(*values):
    for value in values:
        if _is_blank_value(value):
            continue
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
            continue
        return value
    return ""


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError, ArithmeticError):
        return default


def _safe_decimal(value, default="0"):
    if _is_blank_value(value):
        return Decimal(default)

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return Decimal(default)
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return Decimal(default)
    try:
        return Decimal(match.group(0))
    except Exception:
        return Decimal(default)


def _safe_date(value):
    if _is_blank_value(value):
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if isinstance(value, Decimal):
        value = float(value)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            numeric_value = float(value)
            if 0 < numeric_value < 60000:
                return (datetime(1899, 12, 30) + timedelta(days=numeric_value)).date()
        except Exception:
            return None

    text = str(value).strip()
    if not text:
        return None

    iso_text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_text).date()
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%m/%d/%Y",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _safe_bool(value, default=False):
    if _is_blank_value(value):
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, Decimal):
        return value != 0

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and math.isnan(value):
            return default
        return value != 0

    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _safe_line_items(value):
    if _is_blank_value(value):
        return []

    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return items
        return [value]

    text = str(value).strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [{"description": text}]
    return _safe_line_items(parsed)


def _resolve_saved_file_path(invoice, file_data: bytes, ext: str) -> str:
    try:
        file_path = invoice.file.path
        if file_path and os.path.exists(file_path):
            return file_path
    except Exception:
        pass

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
        tmp_file.write(file_data)
        return tmp_file.name


def _detect_text_encoding(raw_bytes: bytes) -> str:
    try:
        import chardet

        detected = chardet.detect(raw_bytes[:8192])
        encoding = detected.get("encoding")
        if encoding:
            return encoding
    except ImportError:
        pass

    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1256", "iso-8859-1", "latin-1"):
        try:
            raw_bytes.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


def _load_structured_records(file_path: str, ext: str) -> tuple[str, list[dict], dict]:
    if ext == ".csv":
        with open(file_path, "rb") as source_file:
            raw_bytes = source_file.read()

        encoding = _detect_text_encoding(raw_bytes)
        raw_text = raw_bytes.decode(encoding, errors="replace")
        sample = raw_text[:4096]

        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","

        reader = csv.DictReader(io.StringIO(raw_text), delimiter=delimiter)
        records = [
            row for row in reader
            if any(not _is_blank_value(value) for value in (row or {}).values())
        ]
        return raw_text, records, {
            "encoding": encoding,
            "delimiter": delimiter,
            "row_count": len(records),
            "column_count": len(reader.fieldnames or []),
        }

    if ext == ".json":
        with open(file_path, "rb") as source_file:
            raw_bytes = source_file.read()

        json_data = None
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1256", "latin-1"):
            try:
                json_data = json.loads(raw_bytes.decode(encoding))
                break
            except Exception as exc:
                last_error = exc

        if json_data is None:
            raise ValueError(f"Failed to parse JSON invoice file: {last_error}")

        if isinstance(json_data, dict):
            records = json_data.get("records") if isinstance(json_data.get("records"), list) else [json_data]
        elif isinstance(json_data, list):
            records = [item for item in json_data if isinstance(item, dict)]
        else:
            raise ValueError("JSON invoice file must contain an object or a list of objects.")

        return json.dumps(json_data, ensure_ascii=False, indent=2, default=str), records, {
            "record_count": len(records),
            "format": type(json_data).__name__,
        }

    if ext in {".xlsx", ".xls"}:
        try:
            import pandas as pd
        except ImportError as exc:
            raise ValueError("pandas is required to parse Excel invoice uploads.") from exc

        sheets = pd.read_excel(file_path, sheet_name=None, dtype=str, keep_default_na=False)
        records = []
        raw_text_parts = []
        sheet_names = []
        for sheet_name, dataframe in sheets.items():
            if dataframe.empty:
                continue
            sheet_names.append(sheet_name)
            raw_text_parts.append(f"=== Sheet: {sheet_name} ===")
            raw_text_parts.append(dataframe.to_string(index=False))
            for row in dataframe.to_dict("records"):
                if any(not _is_blank_value(value) for value in row.values()):
                    row["_sheet"] = sheet_name
                    records.append(row)

        return "\n\n".join(raw_text_parts), records, {
            "sheet_names": sheet_names,
            "sheet_count": len(sheet_names),
            "record_count": len(records),
        }

    raise ValueError(f"Unsupported structured invoice file type: {ext}")


def _normalize_structured_record(record: dict) -> dict:
    normalized = {}
    for key, value in (record or {}).items():
        canonical = STRUCTURED_FIELD_ALIASES.get(_normalize_alias_key(key))
        if not canonical or _is_blank_value(value):
            continue
        normalized[canonical] = _first_non_empty(normalized.get(canonical), value)
    return normalized


def _extract_line_item_from_record(record: dict) -> dict:
    line_item = {}
    for key, value in (record or {}).items():
        canonical = LINE_ITEM_FIELD_ALIASES.get(_normalize_alias_key(key))
        if not canonical or _is_blank_value(value):
            continue
        line_item[canonical] = value

    if not line_item:
        return {}

    quantity = _safe_decimal(line_item.get("quantity"))
    unit_price = _safe_decimal(line_item.get("unit_price"))
    total = _safe_decimal(line_item.get("total"))
    vat_rate = _safe_decimal(line_item.get("vat_rate"), default="15")

    normalized_line_item = {
        "description": str(_first_non_empty(line_item.get("description"), "") or ""),
        "quantity": float(quantity),
        "unit_price": float(unit_price),
        "total": float(total),
        "vat_rate": float(vat_rate),
    }
    has_explicit_line_item_fields = any(
        [
            normalized_line_item["description"],
            normalized_line_item["quantity"],
            normalized_line_item["unit_price"],
        ]
    )
    if has_explicit_line_item_fields and any(
        [
            normalized_line_item["total"],
            normalized_line_item["quantity"],
            normalized_line_item["unit_price"],
            normalized_line_item["description"],
        ]
    ):
        return normalized_line_item
    return {}


def _merge_structured_records(records: list[dict]) -> dict:
    normalized_records = []
    for record in records:
        if not isinstance(record, dict):
            continue
        normalized_record = _normalize_structured_record(record)
        if normalized_record or _extract_line_item_from_record(record):
            normalized_records.append((record, normalized_record))

    if not normalized_records:
        raise ValueError("Structured file did not contain any invoice data.")

    unique_headers = {}
    for field_name in ("invoice_number", "vendor_name", "invoice_date"):
        values = set()
        for _, normalized_record in normalized_records:
            value = normalized_record.get(field_name)
            if _is_blank_value(value):
                continue
            if field_name.endswith("_date"):
                parsed = _safe_date(value)
                if parsed:
                    values.add(parsed.isoformat())
            else:
                values.add(str(value).strip())
        unique_headers[field_name] = values

    conflicting_fields = [field_name for field_name, values in unique_headers.items() if len(values) > 1]
    if conflicting_fields:
        raise ValueError(
            "Structured file contains multiple invoice records. Upload one invoice per file or split them into a ZIP archive."
        )

    merged = {}
    line_items = []
    for raw_record, normalized_record in normalized_records:
        for key, value in normalized_record.items():
            if key == "line_items" or _is_blank_value(value):
                continue
            merged[key] = _first_non_empty(merged.get(key), value)

        line_items.extend(_safe_line_items(normalized_record.get("line_items")))

        row_line_item = _extract_line_item_from_record(raw_record)
        if row_line_item:
            line_items.append(row_line_item)

    if len(normalized_records) > 1 and not any(unique_headers.values()):
        raise ValueError(
            "Structured file has multiple rows but no shared invoice identifiers. Upload one invoice per file or use a ZIP archive."
        )

    if line_items:
        merged["line_items"] = line_items
    return merged


def _extract_structured_invoice_data(file_path: str, ext: str) -> tuple[str, float, dict]:
    raw_text, records, metadata = _load_structured_records(file_path, ext)
    if records:
        structured_data = _merge_structured_records(records)
    else:
        structured_data = {}

    if not structured_data:
        raise ValueError("Structured file did not contain any invoice fields.")

    subtotal = _safe_decimal(structured_data.get("subtotal"))
    vat_amount = _safe_decimal(structured_data.get("vat_amount"))
    discount = _safe_decimal(structured_data.get("discount"))
    total_amount = _safe_decimal(structured_data.get("total_amount"))

    if subtotal == 0 and total_amount > 0 and vat_amount > 0:
        subtotal = max(total_amount - vat_amount + discount, Decimal("0"))
    if total_amount == 0 and (subtotal > 0 or vat_amount > 0 or discount > 0):
        total_amount = subtotal + vat_amount - discount
    if vat_amount == 0 and subtotal > 0 and total_amount > 0:
        vat_amount = max(total_amount - subtotal + discount, Decimal("0"))

    vat_rate = _safe_decimal(structured_data.get("vat_rate"), default="15")
    if vat_rate == 0 and subtotal > 0 and vat_amount > 0:
        vat_rate = (vat_amount / subtotal) * Decimal("100")

    invoice_date = _safe_date(structured_data.get("invoice_date"))
    due_date = _safe_date(structured_data.get("due_date"))
    line_items = _safe_line_items(structured_data.get("line_items"))

    invoice_data = {
        "invoice_number": str(_first_non_empty(structured_data.get("invoice_number"), "") or ""),
        "invoice_date": invoice_date.isoformat() if invoice_date else None,
        "due_date": due_date.isoformat() if due_date else None,
        "vendor_name": str(_first_non_empty(structured_data.get("vendor_name"), "") or ""),
        "vendor_name_ar": str(_first_non_empty(structured_data.get("vendor_name_ar"), "") or ""),
        "vendor_vat_number": str(_first_non_empty(structured_data.get("vendor_vat_number"), "") or ""),
        "vendor_cr_number": str(_first_non_empty(structured_data.get("vendor_cr_number"), "") or ""),
        "vendor_address": str(_first_non_empty(structured_data.get("vendor_address"), "") or ""),
        "vendor_phone": str(_first_non_empty(structured_data.get("vendor_phone"), "") or ""),
        "customer_name": str(_first_non_empty(structured_data.get("customer_name"), "") or ""),
        "customer_vat_number": str(_first_non_empty(structured_data.get("customer_vat_number"), "") or ""),
        "currency": str(_first_non_empty(structured_data.get("currency"), "SAR") or "SAR").upper()[:3],
        "subtotal": float(subtotal),
        "vat_rate": float(vat_rate),
        "vat_amount": float(vat_amount),
        "discount": float(discount),
        "total_amount": float(total_amount),
        "line_items": line_items,
        "has_qr_code": _safe_bool(structured_data.get("has_qr_code"), False),
        "qr_code_valid": _safe_bool(structured_data.get("qr_code_valid"), False),
        "is_handwritten": _safe_bool(structured_data.get("is_handwritten"), False),
        "is_clear": _safe_bool(structured_data.get("is_clear"), True),
        "has_alterations": _safe_bool(structured_data.get("has_alterations"), False),
        "language": str(_first_non_empty(structured_data.get("language"), "unknown") or "unknown"),
        "cost_center": str(_first_non_empty(structured_data.get("cost_center"), "") or ""),
        "account_code": str(_first_non_empty(structured_data.get("account_code"), "") or ""),
        "budget_code": str(_first_non_empty(structured_data.get("budget_code"), "") or ""),
        "department": str(_first_non_empty(structured_data.get("department"), "") or ""),
        "ai_summary": str(_first_non_empty(structured_data.get("ai_summary"), "") or ""),
        "_extraction_method": f"structured_{ext.lstrip('.')}",
        "_parser_metadata": metadata,
        "_source_record_count": len(records),
    }
    return raw_text, 100.0, invoice_data


def _risk_level_from_score(score):
    numeric_score = max(0.0, min(100.0, _to_float(score)))
    if numeric_score >= 70:
        return "high"
    if numeric_score >= 40:
        return "medium"
    return "low"


def _fallback_risk_score(validation_result):
    validation_score = max(0.0, min(100.0, _to_float(validation_result.get("validation_score"), 0.0)))
    failed_codes = set(validation_result.get("failed_rule_codes") or [])
    fallback_score = round(100.0 - validation_score, 2)

    if any(code.startswith("DUP-") for code in failed_codes):
        fallback_score = max(fallback_score, 78.0)
    elif any(code.startswith("ANO-") for code in failed_codes):
        fallback_score = max(fallback_score, 72.0)
    elif any(code.startswith("VAT-") for code in failed_codes):
        fallback_score = max(fallback_score, 58.0)

    return round(max(0.0, min(100.0, fallback_score)), 2)


def _merge_risk_assessment(invoice, validation_result, risk_result):
    risk_result = risk_result or {}
    fallback_score = _fallback_risk_score(validation_result)
    ai_score = max(0.0, min(100.0, _to_float(risk_result.get("overall_risk_score"), 0.0)))
    final_score = max(ai_score, fallback_score)
    final_level = _risk_level_from_score(final_score)

    invoice.risk_score = round(final_score, 2)
    invoice.risk_level = final_level
    invoice.ai_recommendations = risk_result.get("recommendations", [])
    if not invoice.ai_summary:
        invoice.ai_summary = str(risk_result.get("ai_summary", "") or "")

    invoice.is_duplicate = any(
        code in validation_result.get("failed_rule_codes", []) for code in ["DUP-001", "DUP-002", "DUP-003", "DUP-004"]
    )
    if invoice.status not in [Invoice.Status.APPROVED, Invoice.Status.REJECTED]:
        invoice.status = Invoice.Status.FLAGGED if invoice.risk_score >= 70 else Invoice.Status.VALIDATED

    return {
        "overall_risk_score": invoice.risk_score,
        "risk_level": invoice.risk_level,
        "recommendations": invoice.ai_recommendations,
        "ai_summary": invoice.ai_summary,
    }


def _process_single_file(file_obj, filename: str, org, user, batch=None, request=None) -> dict:
    """
    Full pipeline for one file:
      1. OCR or structured parsing
      2. AI extraction for visual invoices
      3. Save Invoice record
      4. Run 30 validation rules
      5. AI risk analysis
      6. Update vendor profile

    Returns:
        dict with invoice_id, validation, risk, errors.
    """
    start = time.time()
    ext = os.path.splitext(filename)[1].lower()
    file_data = file_obj.read()
    file_obj.seek(0)

    # Compute hash for duplicate detection
    file_hash = compute_file_hash(io.BytesIO(file_data))

    # Create invoice record (initial)
    invoice = Invoice.objects.create(
        organization=org,
        uploaded_by=user,
        batch=batch,
        file=ContentFile(file_data, name=filename),
        original_filename=filename,
        file_size=len(file_data),
        mime_type=file_obj.content_type if hasattr(file_obj, "content_type") else "",
        extracted_data={"file_hash": file_hash},
    )

    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.UPLOADED,
                      f"Uploaded file: {filename}", request=request)

    # ── Step 1: OCR ──────────────────────────────────────────────────────────
    raw_text = ""
    ocr_confidence = 0.0
    ai_data = {}
    image_paths = []
    saved_file_path = _resolve_saved_file_path(invoice, file_data, ext)

    if ext in STRUCTURED_EXT:
        raw_text, ocr_confidence, ai_data = _extract_structured_invoice_data(saved_file_path, ext)
    else:
        try:
            if ext == ".pdf":
                image_paths = pdf_to_images(saved_file_path)
                img_for_ai = image_paths[0] if image_paths else saved_file_path
            else:
                img_for_ai = saved_file_path
                image_paths = [saved_file_path]

            tess_result = extract_text_tesseract(image_paths[0])
            raw_text = tess_result.get("text", "")
            ocr_confidence = tess_result.get("confidence", 0.0)

        except Exception as e:
            logger.warning(f"Tesseract OCR failed for {filename}: {e}")
            img_for_ai = saved_file_path
            raw_text = ""

    # ── Step 2: AI Extraction (OpenAI) ───────────────────────────────────────
    if ext not in STRUCTURED_EXT:
        try:
            ai_data = extract_invoice_with_ai(img_for_ai, raw_text)
        except Exception as e:
            logger.warning(f"AI extraction failed for {filename}: {e}")
            from core.services.invoice_ai_service import _fallback_extraction

            ai_data = _fallback_extraction(raw_text)

    # ── Step 3: Populate Invoice from extracted data ──────────────────────────
    invoice.invoice_number    = str(_first_non_empty(ai_data.get("invoice_number"), filename) or "")
    invoice.invoice_date      = _safe_date(ai_data.get("invoice_date"))
    invoice.due_date          = _safe_date(ai_data.get("due_date"))
    invoice.vendor_name       = str(_first_non_empty(
        ai_data.get("vendor_name"),
        ai_data.get("vendor_name_ar"),
        ai_data.get("supplier_name"),
        ai_data.get("merchant_name"),
    ) or "")
    invoice.vendor_name_ar    = str(_first_non_empty(ai_data.get("vendor_name_ar"), ai_data.get("vendor_name")) or "")
    invoice.vendor_vat_number = str(ai_data.get("vendor_vat_number", "") or "")
    invoice.vendor_cr_number  = str(ai_data.get("vendor_cr_number", "") or "")
    invoice.vendor_address    = str(ai_data.get("vendor_address", "") or "")
    invoice.vendor_phone      = str(ai_data.get("vendor_phone", "") or "")
    invoice.customer_name     = str(ai_data.get("customer_name", "") or "")
    invoice.customer_vat_number = str(ai_data.get("customer_vat_number", "") or "")
    invoice.currency          = str(ai_data.get("currency", "SAR") or "SAR")
    invoice.subtotal          = _safe_decimal(ai_data.get("subtotal", 0))
    invoice.vat_rate          = _safe_decimal(ai_data.get("vat_rate", 15))
    invoice.vat_amount        = _safe_decimal(ai_data.get("vat_amount", 0))
    invoice.discount          = _safe_decimal(ai_data.get("discount", 0))
    invoice.total_amount      = _safe_decimal(ai_data.get("total_amount", 0))
    invoice.line_items        = _safe_line_items(ai_data.get("line_items", []))
    invoice.has_qr_code       = _safe_bool(ai_data.get("has_qr_code", False), False)
    invoice.qr_code_valid     = _safe_bool(ai_data.get("qr_code_valid", False), False)
    invoice.is_handwritten    = _safe_bool(ai_data.get("is_handwritten", False), False)
    invoice.is_clear          = _safe_bool(ai_data.get("is_clear", True), True)
    invoice.has_alterations   = _safe_bool(ai_data.get("has_alterations", False), False)
    invoice.language          = str(ai_data.get("language", "unknown"))
    invoice.raw_text          = raw_text
    invoice.ocr_confidence    = ocr_confidence
    invoice.ai_summary        = str(ai_data.get("ai_summary", ""))
    invoice.extracted_data    = {**ai_data, "file_hash": file_hash}
    invoice.status            = Invoice.Status.PROCESSING
    invoice.save()

    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.PROCESSED,
                      f"OCR confidence: {ocr_confidence:.0f}% | AI extraction: {ai_data.get('_extraction_method','unknown')}",
                      request=request)

    # ── Step 4: Run all 30 validation rules ───────────────────────────────────
    val_result = run_all_rules(invoice, organization=org, file_hash=file_hash)

    # Save validation result
    vr, _ = InvoiceValidationResult.objects.update_or_create(
        invoice=invoice,
        defaults={
            "has_invoice_number":       "INV-001" in val_result["passed_rule_codes"],
            "has_invoice_date":         "INV-002" in val_result["passed_rule_codes"],
            "has_vendor_name":          "INV-003" in val_result["passed_rule_codes"],
            "has_vendor_vat":           "INV-004" in val_result["passed_rule_codes"],
            "has_total_amount":         "INV-005" in val_result["passed_rule_codes"],
            "has_currency":             "INV-006" in val_result["passed_rule_codes"],
            "total_greater_zero":       "INV-007" in val_result["passed_rule_codes"],
            "no_vat_without_base":      "INV-008" in val_result["passed_rule_codes"],
            "duplicate_invoice_number": "DUP-001" in val_result["failed_rule_codes"],
            "duplicate_vendor_and_number": "DUP-002" in val_result["failed_rule_codes"],
            "duplicate_vendor_amount_date": "DUP-003" in val_result["failed_rule_codes"],
            "duplicate_file_hash":      "DUP-004" in val_result["failed_rule_codes"],
            "duplicate_across_months":  "DUP-005" in val_result["failed_rule_codes"],
            "vat_rate_correct":         "VAT-001" in val_result["passed_rule_codes"],
            "vat_calculation_correct":  "VAT-002" in val_result["passed_rule_codes"],
            "vat_subtotal_correct":     "VAT-003" in val_result["passed_rule_codes"],
            "vat_number_present":       "VAT-004" in val_result["passed_rule_codes"],
            "qr_code_valid":            "VAT-005" in val_result["passed_rule_codes"],
            "amount_unusually_high":    "ANO-001" in val_result["failed_rule_codes"],
            "new_unknown_vendor":       "ANO-002" in val_result["failed_rule_codes"],
            "many_invoices_same_day":   "ANO-003" in val_result["failed_rule_codes"],
            "sudden_price_change":      "ANO-004" in val_result["failed_rule_codes"],
            "many_invoices_year_end":   "ANO-005" in val_result["failed_rule_codes"],
            "vendor_dominates_invoices":"ANO-006" in val_result["failed_rule_codes"],
            "has_cost_center":          "CTL-001" in val_result["passed_rule_codes"],
            "has_account_code":         "CTL-002" in val_result["passed_rule_codes"],
            "has_approver":             "CTL-005" in val_result["passed_rule_codes"],
            "document_is_clear":        "DOC-001" in val_result["passed_rule_codes"],
            "appears_genuine":          "DOC-002" in val_result["passed_rule_codes"],
            "no_alterations":           "DOC-003" in val_result["passed_rule_codes"],
            "has_qr_code":              "DOC-004" in val_result["passed_rule_codes"],
            "rules_passed":             val_result["rules_passed"],
            "rules_failed":             val_result["rules_failed"],
            "validation_score":         val_result["validation_score"],
            "failed_rule_codes":        val_result["failed_rule_codes"],
            "validation_details":       val_result["rule_details"],
        }
    )

    _save_audit_event(invoice, user, InvoiceAuditEvent.EventType.VALIDATED,
                      f"Validation score: {val_result['validation_score']}% | Failed: {val_result['failed_rule_codes']}",
                      request=request)

    # ── Step 5: AI Risk Analysis ──────────────────────────────────────────────
    vendor_hist = _get_vendor_history(org, invoice.vendor_name)
    try:
        risk_result = analyze_invoice_risk(
            {k: v for k, v in ai_data.items() if not k.startswith("_")},
            vendor_hist,
        )
    except Exception as e:
        logger.warning(f"AI risk analysis failed: {e}")
        risk_result = {}

    # Merge risk into invoice
    risk_result = _merge_risk_assessment(invoice, val_result, risk_result)
    invoice.save()

    # ── Step 6: Update vendor profile ────────────────────────────────────────
    _update_vendor_profile(org, invoice)

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(f"Invoice {invoice.id} processed in {elapsed_ms}ms | Score: {val_result['validation_score']}%")

    return {
        "invoice_id": str(invoice.id),
        "filename": filename,
        "success": True,
        "validation_score": val_result["validation_score"],
        "rules_failed": val_result["failed_rule_codes"],
        "risk_level": invoice.risk_level,
        "status": invoice.status,
        "processing_ms": elapsed_ms,
    }


def _get_vendor_history(org, vendor_name: str) -> dict:
    if not vendor_name:
        return {"is_new": True, "invoice_count": 0}
    try:
        vp = VendorProfile.objects.get(organization=org, vendor_name=vendor_name)
        return {
            "invoice_count": vp.invoice_count,
            "avg_amount": float(vp.avg_invoice_amount),
            "max_amount": float(vp.max_invoice_amount),
            "flagged_count": vp.flagged_count,
            "is_new": vp.is_new,
        }
    except VendorProfile.DoesNotExist:
        return {"is_new": True, "invoice_count": 0}


def _update_vendor_profile(org, invoice: Invoice):
    """Update or create vendor profile after processing an invoice."""
    if not invoice.vendor_name:
        return
    try:
        stats = Invoice.objects.filter(
            organization=org, vendor_name=invoice.vendor_name
        ).aggregate(
            cnt=Count("id"),
            total=Sum("total_amount"),
            avg=Avg("total_amount"),
            max_a=Max("total_amount"),
            flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
            dups=Count("id", filter=Q(is_duplicate=True)),
        )
        vp, _ = VendorProfile.objects.update_or_create(
            organization=org,
            vendor_name=invoice.vendor_name,
            defaults={
                "vendor_vat_number": invoice.vendor_vat_number or "",
                "invoice_count":    stats["cnt"] or 0,
                "total_amount":     stats["total"] or 0,
                "avg_invoice_amount": stats["avg"] or 0,
                "max_invoice_amount": stats["max_a"] or 0,
                "flagged_count":    stats["flagged"] or 0,
                "duplicate_count":  stats["dups"] or 0,
                "is_new":           (stats["cnt"] or 0) <= 1,
                "last_seen":        invoice.invoice_date or date.today(),
            }
        )
        if not vp.first_seen:
            vp.first_seen = invoice.invoice_date or date.today()
            vp.save(update_fields=["first_seen"])
    except Exception as e:
        logger.warning(f"Vendor profile update failed: {e}")


# ─── Views ────────────────────────────────────────────────────────────────────

class InvoiceUploadView(APIView):
    """
    Upload invoices for auditing.

    Supports:
    - Single file (PDF / JPG / PNG / TIFF / CSV / XLS / XLSX / JSON)
    - Multiple files (multipart with multiple 'files' fields)
    - ZIP archive (contains multiple invoice files)
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="Upload one or more invoices (PDF/image/ZIP) — runs all 30 audit rules",
        request={"type": "object", "properties": {
            "files": {"type": "array", "items": {"type": "string", "format": "binary"},
                      "description": "One or more invoice files (PDF, JPG, PNG, TIFF, or ZIP)"},
            "batch_name": {"type": "string"},
        }},
    )
    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "User has no organization."}, status=400)

        uploaded_files = request.FILES.getlist("files")
        if not uploaded_files:
            # Try single file key
            single = request.FILES.get("file")
            if single:
                uploaded_files = [single]
            else:
                return Response({"error": "No files uploaded. Use 'files' or 'file' field."}, status=400)

        batch_name = request.data.get("batch_name", f"Batch {timezone.now().strftime('%Y-%m-%d %H:%M')}")

        # Create batch
        batch = InvoiceBatch.objects.create(
            organization=org,
            uploaded_by=request.user,
            batch_name=batch_name,
            total_files=len(uploaded_files),
        )

        results = []
        errors  = []

        for uploaded_file in uploaded_files:
            filename = uploaded_file.name
            ext = os.path.splitext(filename)[1].lower()

            if ext not in ALLOWED_EXT:
                errors.append({"filename": filename, "error": f"Unsupported file type: {ext}"})
                batch.failed_files += 1
                continue

            # ── ZIP: extract and process each file inside ─────────────────────
            if ext == ".zip":
                zip_results, zip_errors = _process_zip(uploaded_file, org, request.user, batch, request)
                results.extend(zip_results)
                errors.extend(zip_errors)
                batch.total_files += len(zip_results) + len(zip_errors) - 1  # replace 1 zip with n files
            else:
                try:
                    r = _process_single_file(uploaded_file, filename, org, request.user, batch, request)
                    results.append(r)
                    batch.processed_files += 1
                except Exception as e:
                    logger.error(f"Failed processing {filename}: {e}")
                    errors.append({"filename": filename, "error": str(e)})
                    batch.failed_files += 1

        # Finalize batch
        batch.status = (
            InvoiceBatch.BatchStatus.COMPLETED  if not errors else
            InvoiceBatch.BatchStatus.PARTIAL    if results else
            InvoiceBatch.BatchStatus.FAILED
        )
        batch.completed_at = timezone.now()
        batch.processing_log = results + errors
        batch.save()

        log_action(request, AuditLog.Action.DOCUMENT_UPLOAD, "invoice_batch", str(batch.id),
                   {"files": len(results), "errors": len(errors)})

        return Response({
            "batch_id":      str(batch.id),
            "batch_name":    batch_name,
            "total_files":   len(results) + len(errors),
            "processed":     len(results),
            "failed":        len(errors),
            "status":        batch.status,
            "results":       results,
            "errors":        errors,
        }, status=status.HTTP_201_CREATED)


def _process_zip(zip_file, org, user, batch, request) -> tuple[list, list]:
    """Extract and process all invoice files inside a ZIP archive."""
    results, errors = [], []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_file.read()), "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                name = os.path.basename(member.filename)
                ext = os.path.splitext(name)[1].lower()
                if ext not in (ALLOWED_EXT - ZIP_EXT):
                    continue
                try:
                    data = zf.read(member)
                    file_like = io.BytesIO(data)
                    file_like.name = name
                    file_like.content_type = _guess_mime(ext)
                    r = _process_single_file(file_like, name, org, user, batch, request)
                    results.append(r)
                    batch.processed_files += 1
                except Exception as e:
                    logger.error(f"ZIP member {name} failed: {e}")
                    errors.append({"filename": name, "error": str(e)})
                    batch.failed_files += 1
    except zipfile.BadZipFile:
        errors.append({"filename": zip_file.name, "error": "Invalid ZIP file"})
    return results, errors


def _guess_mime(ext: str) -> str:
    return {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "tiff": "image/tiff", "tif": "image/tiff",
            "csv": "text/csv", "json": "application/json", "xls": "application/vnd.ms-excel",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(ext.lstrip("."), "application/octet-stream")


class InvoiceListView(generics.ListAPIView):
    serializer_class = InvoiceListSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="List all invoices for the organization",
        parameters=[
            OpenApiParameter("status",       description="Filter by status"),
            OpenApiParameter("risk_level",   description="Filter by risk level"),
            OpenApiParameter("vendor_name",  description="Filter by vendor name"),
            OpenApiParameter("is_duplicate", type=bool),
            OpenApiParameter("date_from"),
            OpenApiParameter("date_to"),
            OpenApiParameter("min_amount",   type=float),
            OpenApiParameter("max_amount",   type=float),
            OpenApiParameter("search",       description="Search vendor/invoice number/notes"),
            OpenApiParameter("batch_id",     description="Filter by batch ID"),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = Invoice.objects.filter(organization=self.request.user.organization).select_related(
            "uploaded_by", "approved_by", "batch"
        )
        p = self.request.query_params
        if v := p.get("status"):        qs = qs.filter(status=v)
        if v := p.get("risk_level"):    qs = qs.filter(risk_level=v)
        if v := p.get("vendor_name"):   qs = qs.filter(vendor_name__icontains=v)
        if v := p.get("is_duplicate"):  qs = qs.filter(is_duplicate=v.lower() == "true")
        if v := p.get("date_from"):     qs = qs.filter(invoice_date__gte=v)
        if v := p.get("date_to"):       qs = qs.filter(invoice_date__lte=v)
        if v := p.get("min_amount"):    qs = qs.filter(total_amount__gte=v)
        if v := p.get("max_amount"):    qs = qs.filter(total_amount__lte=v)
        if v := p.get("batch_id") or p.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := p.get("search"):
            qs = qs.filter(
                Q(vendor_name__icontains=v) | Q(invoice_number__icontains=v) |
                Q(notes__icontains=v) | Q(vendor_vat_number__icontains=v)
            )
        return qs.order_by("-created_at")


class InvoiceDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = InvoiceDetailSerializer
    permission_classes = [IsAuthenticated, IsOwnOrganization]

    @extend_schema(tags=["Invoices"], summary="Get full invoice details with validation results")
    def get(self, request, *args, **kwargs):
        invoice = self.get_object()
        data = InvoiceDetailSerializer(invoice).data
        try:
            data["validation"] = InvoiceValidationResultSerializer(invoice.validation).data
        except InvoiceValidationResult.DoesNotExist:
            data["validation"] = None
        data["audit_trail"] = list(
            invoice.audit_events.order_by("-timestamp").values(
                "event_type", "description", "timestamp", "user__full_name", "ip_address"
            )[:20]
        )
        return Response(data)

    def perform_update(self, serializer):
        invoice = self.get_object()
        if invoice.status == Invoice.Status.APPROVED:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot edit an approved invoice. (Rule CTL-004)")
        before = InvoiceDetailSerializer(invoice).data
        updated = serializer.save()
        _save_audit_event(updated, self.request.user, InvoiceAuditEvent.EventType.EDITED,
                          "Invoice fields updated", before=before,
                          after=InvoiceDetailSerializer(updated).data,
                          request=self.request)

    def get_queryset(self):
        return Invoice.objects.filter(organization=self.request.user.organization)


class InvoiceApproveView(APIView):
    """Approve or reject an invoice (Rule CTL-005: must have approver)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(
        tags=["Invoices"],
        summary="Approve or reject an invoice",
        request={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["approve", "reject"]},
            "reason": {"type": "string", "description": "Required for rejection"},
        }},
    )
    def post(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk, organization=request.user.organization)
        except Invoice.DoesNotExist:
            return Response({"error": "Invoice not found."}, status=404)

        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": "action must be 'approve' or 'reject'"}, status=400)

        before = {"status": invoice.status}

        if action == "approve":
            invoice.status      = Invoice.Status.APPROVED
            invoice.approved_by = request.user
            invoice.approved_at = timezone.now()
            event_type          = InvoiceAuditEvent.EventType.APPROVED
            msg                 = f"Approved by {request.user.full_name}"
        else:
            reason = request.data.get("reason", "")
            if not reason:
                return Response({"error": "reason is required for rejection."}, status=400)
            invoice.status          = Invoice.Status.REJECTED
            invoice.rejected_reason = reason
            event_type              = InvoiceAuditEvent.EventType.REJECTED
            msg                     = f"Rejected: {reason}"

        invoice.save()
        _save_audit_event(invoice, request.user, event_type, msg,
                          before=before, after={"status": invoice.status}, request=request)

        return Response({"invoice_id": str(invoice.id), "status": invoice.status, "message": msg})


class InvoiceRevalidateView(APIView):
    """Re-run all 30 validation rules on an existing invoice."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Re-run all 30 validation rules on an existing invoice")
    def post(self, request, pk):
        try:
            invoice = Invoice.objects.get(pk=pk, organization=request.user.organization)
        except Invoice.DoesNotExist:
            return Response({"error": "Invoice not found."}, status=404)

        file_hash = invoice.extracted_data.get("file_hash", "")
        val_result = run_all_rules(invoice, organization=request.user.organization, file_hash=file_hash)

        InvoiceValidationResult.objects.filter(invoice=invoice).update(
            rules_passed=val_result["rules_passed"],
            rules_failed=val_result["rules_failed"],
            validation_score=val_result["validation_score"],
            failed_rule_codes=val_result["failed_rule_codes"],
            validation_details=val_result["rule_details"],
        )
        risk_result = {}
        try:
            risk_result = analyze_invoice_risk(invoice.extracted_data or {}, _get_vendor_history(request.user.organization, invoice.vendor_name))
        except Exception as exc:
            logger.warning(f"AI risk re-analysis failed: {exc}")

        _merge_risk_assessment(invoice, val_result, risk_result)
        invoice.save(update_fields=["risk_score", "risk_level", "ai_recommendations", "ai_summary", "is_duplicate", "status"])

        _save_audit_event(invoice, request.user, InvoiceAuditEvent.EventType.REPROCESSED,
                          f"Re-validated: score={val_result['validation_score']}%", request=request)

        return Response(val_result)


class InvoiceBatchListView(generics.ListAPIView):
    serializer_class = InvoiceBatchSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="List upload batches")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return InvoiceBatch.objects.filter(organization=self.request.user.organization)


class InvoiceBatchDetailView(APIView):
    """Get batch details with all invoice summaries."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Get batch details with invoice summaries")
    def get(self, request, pk):
        try:
            batch = InvoiceBatch.objects.get(pk=pk, organization=request.user.organization)
        except InvoiceBatch.DoesNotExist:
            return Response({"error": "Batch not found."}, status=404)

        invoices = Invoice.objects.filter(batch=batch).values(
            "id", "original_filename", "vendor_name", "total_amount", "currency",
            "invoice_date", "status", "risk_level", "is_duplicate", "ocr_confidence",
        )
        stats = Invoice.objects.filter(batch=batch).aggregate(
            total_amount=Sum("total_amount"),
            avg_score=Avg("ocr_confidence"),
            flagged=Count("id", filter=Q(status="flagged")),
            approved=Count("id", filter=Q(status="approved")),
            duplicates=Count("id", filter=Q(is_duplicate=True)),
            critical=Count("id", filter=Q(risk_level="critical")),
        )
        return Response({
            "batch": InvoiceBatchSerializer(batch).data,
            "stats": stats,
            "invoices": list(invoices),
        })


# ─── Reports ─────────────────────────────────────────────────────────────────

class InvoiceRiskReportView(APIView):
    """Report: High-risk invoices."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="Risk report — flagged and high-risk invoices",
        parameters=[
            OpenApiParameter("date_from"), OpenApiParameter("date_to"),
            OpenApiParameter("risk_level", description="low|medium|high|critical"),
        ],
    )
    def get(self, request):
        org = request.user.organization
        qs = Invoice.objects.filter(organization=org)
        if v := request.query_params.get("date_from"):
            qs = qs.filter(invoice_date__gte=v)
        if v := request.query_params.get("date_to"):
            qs = qs.filter(invoice_date__lte=v)
        if v := request.query_params.get("risk_level"):
            qs = qs.filter(risk_level=v)
        else:
            qs = qs.filter(risk_level__in=["high", "critical"])

        invoices = qs.order_by("-risk_score").values(
            "id", "invoice_number", "vendor_name", "total_amount", "currency",
            "invoice_date", "risk_level", "risk_score", "ai_summary",
            "is_duplicate", "status", "ai_recommendations",
        )
        stats = qs.aggregate(
            count=Count("id"), total=Sum("total_amount"), avg_risk=Avg("risk_score")
        )
        return Response({
            "report_type": "risk_report",
            "generated_at": timezone.now().isoformat(),
            "stats": stats,
            "invoices": list(invoices),
        })


class DuplicateInvoiceReportView(APIView):
    """Report: Duplicate invoices."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Duplicate invoices report")
    def get(self, request):
        org = request.user.organization
        qs = Invoice.objects.filter(organization=org, is_duplicate=True).order_by("-created_at")
        invoices = qs.values(
            "id", "invoice_number", "vendor_name", "total_amount", "currency",
            "invoice_date", "status", "duplicate_of_id", "created_at",
        )
        return Response({
            "report_type": "duplicate_report",
            "generated_at": timezone.now().isoformat(),
            "total_duplicates": qs.count(),
            "invoices": list(invoices),
        })


class VendorRiskReportView(APIView):
    """Report: Vendor risk analysis."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="Vendor risk analysis report")
    def get(self, request):
        org = request.user.organization
        vendors = VendorProfile.objects.filter(organization=org).order_by("-total_amount")
        return Response({
            "report_type": "vendor_risk_report",
            "generated_at": timezone.now().isoformat(),
            "vendors": VendorProfileSerializer(vendors, many=True).data,
        })


class SpendAnalysisReportView(APIView):
    """Report: Spend analysis by vendor and category."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Invoices"],
        summary="Spend analysis report",
        parameters=[
            OpenApiParameter("date_from"), OpenApiParameter("date_to"),
        ],
    )
    def get(self, request):
        org = request.user.organization
        qs = Invoice.objects.filter(organization=org)
        if v := request.query_params.get("date_from"):
            qs = qs.filter(invoice_date__gte=v)
        if v := request.query_params.get("date_to"):
            qs = qs.filter(invoice_date__lte=v)

        # By vendor
        by_vendor = qs.values("vendor_name").annotate(
            total=Sum("total_amount"), count=Count("id"),
            avg=Avg("total_amount"), flagged=Count("id", filter=Q(is_duplicate=True)),
        ).order_by("-total")[:20]

        # By currency
        by_currency = qs.values("currency").annotate(
            total=Sum("total_amount"), count=Count("id"),
        ).order_by("-total")

        # Monthly trend
        from django.db.models.functions import TruncMonth
        monthly = qs.annotate(month=TruncMonth("invoice_date")).values("month").annotate(
            total=Sum("total_amount"), count=Count("id"),
            flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
        ).order_by("month")

        # Overall stats
        stats = qs.aggregate(
            grand_total=Sum("total_amount"),
            total_vat=Sum("vat_amount"),
            total_invoices=Count("id"),
            avg_invoice=Avg("total_amount"),
            flagged_total=Sum("total_amount", filter=Q(risk_level__in=["high","critical"])),
        )

        return Response({
            "report_type": "spend_analysis",
            "generated_at": timezone.now().isoformat(),
            "overall": stats,
            "by_vendor": list(by_vendor),
            "by_currency": list(by_currency),
            "monthly_trend": [
                {**m, "month": str(m["month"])[:7] if m["month"] else None}
                for m in monthly
            ],
        })


class ValidationRulesListView(APIView):
    """List all 30 validation rules with descriptions."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Invoices"], summary="List all 30 invoice audit rules")
    def get(self, request):
        groups = {
            "Group 1 — Invoice Validation": {k: v for k, v in RULES.items() if k.startswith("INV")},
            "Group 2 — Duplicate Detection": {k: v for k, v in RULES.items() if k.startswith("DUP")},
            "Group 3 — VAT Validation": {k: v for k, v in RULES.items() if k.startswith("VAT")},
            "Group 4 — Anomaly Detection": {k: v for k, v in RULES.items() if k.startswith("ANO")},
            "Group 5 — Financial Controls": {k: v for k, v in RULES.items() if k.startswith("CTL")},
            "Group 6 — Document Quality": {k: v for k, v in RULES.items() if k.startswith("DOC")},
        }
        return Response({"total_rules": TOTAL_RULES, "rule_groups": groups})
