"""
AI Document Extraction Service — Universal GCC Financial Auditor
=================================================================
Single GPT-4o prompt framework for all 7 document types.

7-Step audit pipeline per document:
  1. Identify document type
  2. Extract structured data
  3. Financial validation
  4. Anomaly detection
  5. GCC compliance check
  6. Field confidence scores
  7. Structured JSON output
"""

import base64
import json
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("finai")


def _strip_json_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1].strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned


# ── Shared GPT caller ─────────────────────────────────────────────────────────

_STRUCTURED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".json", ".jsonl"}
_IMAGE_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "tiff": "image/tiff", "tif": "image/tiff",
}


def _call_openai(prompt: str, image_path: str, raw_text: str = "") -> dict:
    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured for document extraction.")
        return {}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]

        # Add image only for actual image/PDF files — skip structured data files
        file_ext = Path(image_path).suffix.lower()
        if file_ext not in _STRUCTURED_EXTENSIONS:
            try:
                with open(image_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                ext_key = file_ext.lstrip(".")
                mime = _IMAGE_MIME.get(ext_key, "image/jpeg")
                messages[0]["content"].append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                })
            except Exception:
                pass

        if raw_text:
            messages[0]["content"].append({
                "type": "text",
                "text": f"\n\nExtracted Data:\n{raw_text[:8000]}",
            })

        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            max_tokens=settings.OPENAI_MAX_TOKENS,
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        text = _strip_json_fences(resp.choices[0].message.content)
        data = json.loads(text)
        data["_extraction_method"] = "openai_vision"
        if getattr(resp, "usage", None):
            data["_tokens_used"] = resp.usage.total_tokens
        return data
    except Exception as e:
        logger.warning(f"OpenAI extraction failed: {e}")
        return {}


# ── Elite Universal Audit Prompt ─────────────────────────────────────────────

def _build_audit_prompt(doc_type: str, type_schema: str) -> str:
    return f"""You are an elite AI Financial Auditor specialized in auditing non-invoice financial documents for businesses in GCC countries, especially Saudi Arabia.

Document type hint: {doc_type}

Your role is NOT just to extract text. Your role is to:
1. understand the financial document,
2. identify its type,
3. extract structured financial data,
4. validate financial consistency,
5. detect anomalies or manipulation risks,
6. assess basic compliance readiness,
7. return a professional audit-oriented JSON result.

You must work carefully, conservatively, and accurately.
Do not guess aggressively.
If something is unclear, mark it as uncertain with lower confidence.

========================
A) DOCUMENT UNDERSTANDING
========================
Read the document carefully. Identify the document type from structure, keywords, tables, fields, and business context.
If the type is unclear, choose the closest type and reduce confidence.

========================
B) SMART EXTRACTION
========================
Extract all important fields. Common fields when available:
document_type, document_title, entity_name, counterparty_name, document_number,
reference_number, issue_date, period_start, period_end, currency,
subtotal, tax_amount, total_amount, payment_status, notes.

Type-specific schema to populate inside extracted_data:
{type_schema}

========================
C) FINANCIAL VALIDATION
========================
- Verify subtotal + tax = total when applicable
- Verify line totals sum correctly
- Verify opening balance + credits - debits ≈ closing balance
- Verify payroll totals equal sum of employee rows
- Verify depreciation / net book value consistency
- Verify tax values are mathematically reasonable (Saudi VAT = 15%)
- Check whether dates are logical and sequential
- Check whether currencies are consistent
- Check whether required fields are missing

========================
D) ANOMALY DETECTION
========================
Detect: repeated transactions, duplicate rows, extreme values, missing identifiers,
negative amounts where unexpected, inconsistent totals, abrupt balance jumps,
suspicious round-number concentration, missing employee IDs, missing asset codes,
suspicious tax mismatch, irregular sequence gaps, incomplete document structure.

========================
E) COMPLIANCE-ORIENTED REVIEW
========================
Assess audit readiness:
- Is the document sufficiently complete?
- Is it internally consistent?
- Is it traceable?
- Is it suitable as supporting evidence?
- What key accounting fields are missing?
Saudi-specific: VAT number = 15 digits starting and ending with 3, IBAN = SA + 22 digits.

========================
F) CONFIDENCE SCORING
========================
Return overall_confidence and field_confidence (0.0-1.0).
Reduce confidence when: OCR text is noisy, fields partially missing, table broken,
multiple interpretations possible.

========================
G) RISK RATING
========================
low = mostly complete and consistent.
medium = some issues, usable with review.
high = major inconsistencies, missing fields, or suspicious anomalies.

========================
OUTPUT — RETURN ONLY VALID JSON
========================
No markdown. No commentary outside JSON. No code fences.

{{
  "document_type": "",
  "document_type_confidence": 0.0,
  "overall_confidence": 0.0,
  "language_detected": "ar|en|mixed",
  "extracted_data": {{}},
  "field_confidence": {{}},
  "validation_results": [
    {{"check": "", "status": "passed|warning|failed", "details": ""}}
  ],
  "anomalies": [
    {{"type": "", "severity": "low|medium|high", "details": ""}}
  ],
  "compliance_review": {{
    "audit_readiness": "low|medium|high",
    "traceability": "low|medium|high",
    "completeness": "low|medium|high",
    "key_missing_elements": [],
    "notes": []
  }},
  "recommendations": [],
  "overall_risk_level": "low|medium|high"
}}

Be strict about numbers. Do not invent values. Use null for missing values.
If file is corrupted or unreadable, state that clearly in JSON."""


# ── Type-specific schemas ─────────────────────────────────────────────────────

_SCHEMAS = {
    "purchase_order": """{
  "po_number": "", "po_date": "YYYY-MM-DD or null",
  "delivery_date": "YYYY-MM-DD or null",
  "vendor_name": "", "vendor_vat_number": "", "vendor_cr_number": "",
  "requester_name": "", "department": "", "cost_center": "", "account_code": "",
  "currency": "SAR", "subtotal": 0.0, "vat_amount": 0.0, "total_amount": 0.0,
  "line_items": [{"description":"","qty":0,"unit_price":0.0,"total":0.0}],
  "language": "ar|en|mixed"
}""",

    "bank_statement": """{
  "bank_name": "", "account_number": "", "account_name": "", "iban": "",
  "currency": "SAR",
  "statement_period_from": "YYYY-MM-DD or null",
  "statement_period_to": "YYYY-MM-DD or null",
  "opening_balance": 0.0, "closing_balance": 0.0,
  "total_credits": 0.0, "total_debits": 0.0, "transaction_count": 0,
  "transactions": [
    {"date":"YYYY-MM-DD","description":"","debit":0.0,"credit":0.0,"balance":0.0,"ref":""}
  ],
  "language": "ar|en|mixed"
}""",

    "payroll": """{
  "payroll_period_from": "YYYY-MM-DD or null",
  "payroll_period_to": "YYYY-MM-DD or null",
  "payment_date": "YYYY-MM-DD or null",
  "department": "", "company_name": "", "currency": "SAR",
  "employee_count": 0,
  "total_gross_salary": 0.0, "total_allowances": 0.0,
  "total_deductions": 0.0, "total_gosi": 0.0, "total_net_salary": 0.0,
  "employees": [
    {"id":"","name":"","name_ar":"","gross":0.0,"allowances":0.0,
     "deductions":0.0,"gosi":0.0,"net":0.0,"bank_account":""}
  ],
  "language": "ar|en|mixed"
}""",

    "expense_report": """{
  "report_number": "", "employee_name": "", "employee_id": "",
  "department": "",
  "report_period_from": "YYYY-MM-DD or null",
  "report_period_to": "YYYY-MM-DD or null",
  "submitted_date": "YYYY-MM-DD or null",
  "currency": "SAR", "purpose": "",
  "total_claimed": 0.0, "vat_included": 0.0,
  "expense_lines": [
    {"date":"YYYY-MM-DD","category":"travel|accommodation|meals|office|communication|training|maintenance|other",
     "description":"","amount":0.0,"receipt_attached":true,"receipt_number":""}
  ],
  "language": "ar|en|mixed"
}""",

    "vat_return": """{
  "taxpayer_name": "", "vat_number": "", "cr_number": "",
  "period_from": "YYYY-MM-DD or null",
  "period_to": "YYYY-MM-DD or null",
  "filing_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "zatca_reference": "",
  "standard_rated_sales": 0.0, "zero_rated_sales": 0.0,
  "exempt_sales": 0.0, "total_sales": 0.0,
  "output_vat": 0.0, "standard_rated_purchases": 0.0,
  "input_vat": 0.0, "net_vat_payable": 0.0, "vat_paid": 0.0,
  "language": "ar|en|mixed"
}""",

    "fixed_asset": """{
  "register_date": "YYYY-MM-DD or null",
  "company_name": "", "department": "", "fiscal_year": "",
  "total_cost": 0.0,
  "total_accumulated_depreciation": 0.0,
  "total_book_value": 0.0, "asset_count": 0,
  "assets": [
    {"asset_id":"","name":"","name_ar":"",
     "category":"land|buildings|vehicles|equipment|computers|furniture|other",
     "purchase_date":"YYYY-MM-DD or null","cost":0.0,"useful_life_years":0,
     "method":"straight_line|declining|units|none",
     "annual_depreciation":0.0,"accumulated_depreciation":0.0,
     "book_value":0.0,"is_fully_depreciated":false}
  ],
  "language": "ar|en|mixed"
}""",

    "sales_receipt": """{
  "receipt_number": "",
  "receipt_date": "YYYY-MM-DD or null",
  "receipt_type": "standard|simplified|credit|debit",
  "seller_name": "", "seller_vat_number": "",
  "customer_name": "", "customer_vat_number": "",
  "currency": "SAR", "subtotal": 0.0, "vat_rate": 15.0,
  "vat_amount": 0.0, "total_amount": 0.0,
  "line_items": [{"description":"","qty":0,"unit_price":0.0,"total":0.0}],
  "has_qr_code": false, "qr_code_valid": false, "zatca_uuid": "",
  "language": "ar|en|mixed"
}""",
}


# ── Audit result helpers ───────────────────────────────────────────────────────

def _audit_summary(audit: dict) -> str:
    """Build a concise Arabic summary from the elite audit result."""
    risk      = audit.get("overall_risk_level", "low")
    anomalies = audit.get("anomalies", [])
    cr        = audit.get("compliance_review") or {}
    failed_v  = [v for v in audit.get("validation_results", [])
                 if v.get("status") in ("failed", "warning")]
    conf      = audit.get("overall_confidence", 1.0)

    parts = []
    if risk in ("high", "critical"):
        parts.append(f"مستوى الخطر: {risk}.")
    if anomalies:
        high_a = [a for a in anomalies if a.get("severity") == "high"]
        parts.append(f"رُصد {len(anomalies)} شذوذ" +
                     (f" ({len(high_a)} عالية الخطورة)" if high_a else "") + ".")
    if failed_v:
        parts.append(f"{len(failed_v)} تحقق فشل أو يحتاج مراجعة.")
    if cr.get("key_missing_elements"):
        parts.append(f"حقول ناقصة: {', '.join(cr['key_missing_elements'][:3])}.")
    if conf < 0.6:
        parts.append("دقة الاستخراج منخفضة — يُنصح بالمراجعة اليدوية.")
    return " ".join(parts) or "تم استخراج البيانات بنجاح."


def _merge_audit_into_result(base: dict, audit: dict) -> dict:
    """Merge elite audit fields into the type-specific result dict."""
    ed = audit.get("extracted_data") or {}
    # Fill gaps: only overwrite empty/None base fields
    for k, v in ed.items():
        if k not in base or not base[k]:
            base[k] = v

    base["_validation_results"] = audit.get("validation_results", [])
    base["_anomalies"]          = audit.get("anomalies", [])
    base["_compliance_review"]  = audit.get("compliance_review", {})
    base["_recommendations"]    = audit.get("recommendations", [])
    base["_field_confidence"]   = audit.get("field_confidence", {})
    base["_overall_confidence"] = audit.get("overall_confidence", 1.0)
    base["_overall_risk_level"] = audit.get("overall_risk_level", "low")
    base["_language_detected"]  = audit.get("language_detected", "")
    base["ai_summary"]          = _audit_summary(audit)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# Per-type extractors
# ══════════════════════════════════════════════════════════════════════════════

def extract_purchase_order(image_path: str, raw_text: str = "") -> dict:
    prompt = _build_audit_prompt("purchase_order", _SCHEMAS["purchase_order"])
    audit  = _call_openai(prompt, image_path, raw_text)
    ed     = audit.get("extracted_data") or audit  # fallback if flat response

    base = {
        "po_number":         str(ed.get("po_number") or ""),
        "po_date":           ed.get("po_date"),
        "delivery_date":     ed.get("delivery_date"),
        "vendor_name":       str(ed.get("vendor_name") or ""),
        "vendor_vat_number": str(ed.get("vendor_vat_number") or ""),
        "vendor_cr_number":  str(ed.get("vendor_cr_number") or ""),
        "requester_name":    str(ed.get("requester_name") or ""),
        "department":        str(ed.get("department") or ""),
        "cost_center":       str(ed.get("cost_center") or ""),
        "account_code":      str(ed.get("account_code") or ""),
        "currency":          str(ed.get("currency") or "SAR"),
        "subtotal":          float(ed.get("subtotal") or 0),
        "vat_amount":        float(ed.get("vat_amount") or 0),
        "total_amount":      float(ed.get("total_amount") or 0),
        "line_items":        ed.get("line_items") or [],
        "language":          str(ed.get("language") or "unknown"),
    }
    return _merge_audit_into_result(base, audit)


def extract_bank_statement(image_path: str, raw_text: str = "") -> dict:
    prompt = _build_audit_prompt("bank_statement", _SCHEMAS["bank_statement"])
    audit  = _call_openai(prompt, image_path, raw_text)
    ed     = audit.get("extracted_data") or audit

    transactions  = ed.get("transactions") or []
    total_credits = sum(float(t.get("credit") or 0) for t in transactions)
    total_debits  = sum(float(t.get("debit")  or 0) for t in transactions)
    opening       = float(ed.get("opening_balance") or 0)
    closing       = float(ed.get("closing_balance") or 0)
    calc_closing  = round(opening + total_credits - total_debits, 2)

    base = {
        "bank_name":             str(ed.get("bank_name") or ""),
        "account_number":        str(ed.get("account_number") or ""),
        "account_name":          str(ed.get("account_name") or ""),
        "iban":                  str(ed.get("iban") or ""),
        "currency":              str(ed.get("currency") or "SAR"),
        "statement_period_from": ed.get("statement_period_from"),
        "statement_period_to":   ed.get("statement_period_to"),
        "opening_balance":       opening,
        "closing_balance":       closing,
        "total_credits":         total_credits or float(ed.get("total_credits") or 0),
        "total_debits":          total_debits  or float(ed.get("total_debits")  or 0),
        "calculated_closing":    calc_closing,
        "balance_matches":       abs(calc_closing - closing) <= 1.0,
        "transaction_count":     len(transactions) or int(ed.get("transaction_count") or 0),
        "transactions":          transactions,
        "language":              str(ed.get("language") or "unknown"),
    }
    return _merge_audit_into_result(base, audit)


def extract_payroll(image_path: str, raw_text: str = "") -> dict:
    prompt    = _build_audit_prompt("payroll", _SCHEMAS["payroll"])
    audit     = _call_openai(prompt, image_path, raw_text)
    ed        = audit.get("extracted_data") or audit
    employees = ed.get("employees") or []

    ids      = [e.get("id", "") for e in employees if e.get("id")]
    dup_ids  = list({i for i in ids if ids.count(i) > 1})

    calc_errors = []
    for e in employees:
        gross = float(e.get("gross") or 0)
        ded   = float(e.get("deductions") or 0)
        gosi  = float(e.get("gosi") or 0)
        net   = float(e.get("net") or 0)
        expected = gross + float(e.get("allowances") or 0) - ded - gosi
        if abs(net - expected) > 5 and net > 0:
            calc_errors.append(e.get("id") or e.get("name") or "?")

    base = {
        "payroll_period_from":  ed.get("payroll_period_from"),
        "payroll_period_to":    ed.get("payroll_period_to"),
        "payment_date":         ed.get("payment_date"),
        "department":           str(ed.get("department") or ""),
        "company_name":         str(ed.get("company_name") or ""),
        "currency":             str(ed.get("currency") or "SAR"),
        "employee_count":       int(ed.get("employee_count") or len(employees)),
        "total_gross_salary":   float(ed.get("total_gross_salary") or 0),
        "total_allowances":     float(ed.get("total_allowances") or 0),
        "total_deductions":     float(ed.get("total_deductions") or 0),
        "total_gosi":           float(ed.get("total_gosi") or 0),
        "total_net_salary":     float(ed.get("total_net_salary") or 0),
        "employees":            employees,
        "duplicate_employee_ids": dup_ids,
        "calculation_errors":   calc_errors,
        "language":             str(ed.get("language") or "unknown"),
    }
    return _merge_audit_into_result(base, audit)


def extract_expense_report(image_path: str, raw_text: str = "") -> dict:
    prompt = _build_audit_prompt("expense_report", _SCHEMAS["expense_report"])
    audit  = _call_openai(prompt, image_path, raw_text)
    ed     = audit.get("extracted_data") or audit
    lines  = ed.get("expense_lines") or []

    missing_receipts = sum(1 for l in lines if not l.get("receipt_attached", True))
    calc_total       = sum(float(l.get("amount") or 0) for l in lines)

    base = {
        "report_number":       str(ed.get("report_number") or ""),
        "employee_name":       str(ed.get("employee_name") or ""),
        "employee_id":         str(ed.get("employee_id") or ""),
        "department":          str(ed.get("department") or ""),
        "report_period_from":  ed.get("report_period_from"),
        "report_period_to":    ed.get("report_period_to"),
        "submitted_date":      ed.get("submitted_date"),
        "currency":            str(ed.get("currency") or "SAR"),
        "purpose":             str(ed.get("purpose") or ""),
        "total_claimed":       float(ed.get("total_claimed") or calc_total),
        "vat_included":        float(ed.get("vat_included") or 0),
        "expense_lines":       lines,
        "missing_receipts_count": missing_receipts,
        "language":            str(ed.get("language") or "unknown"),
    }
    return _merge_audit_into_result(base, audit)


def extract_vat_return(image_path: str, raw_text: str = "") -> dict:
    prompt     = _build_audit_prompt("vat_return", _SCHEMAS["vat_return"])
    audit      = _call_openai(prompt, image_path, raw_text)
    ed         = audit.get("extracted_data") or audit

    output_vat   = float(ed.get("output_vat") or 0)
    input_vat    = float(ed.get("input_vat")  or 0)
    net_declared = float(ed.get("net_vat_payable") or 0)
    std_sales    = float(ed.get("standard_rated_sales") or 0)
    calc_output  = round(std_sales * 0.15, 2)
    calc_net     = round(output_vat - input_vat, 2)

    is_late, late_days = False, 0
    due_str, file_str  = ed.get("due_date"), ed.get("filing_date")
    if due_str and file_str:
        try:
            from datetime import datetime
            due_d  = datetime.strptime(due_str,  "%Y-%m-%d").date()
            file_d = datetime.strptime(file_str, "%Y-%m-%d").date()
            if file_d > due_d:
                is_late   = True
                late_days = (file_d - due_d).days
        except Exception:
            pass

    base = {
        "taxpayer_name":            str(ed.get("taxpayer_name") or ""),
        "vat_number":               str(ed.get("vat_number") or ""),
        "cr_number":                str(ed.get("cr_number") or ""),
        "period_from":              ed.get("period_from"),
        "period_to":                ed.get("period_to"),
        "filing_date":              ed.get("filing_date"),
        "due_date":                 ed.get("due_date"),
        "zatca_reference":          str(ed.get("zatca_reference") or ""),
        "standard_rated_sales":     std_sales,
        "zero_rated_sales":         float(ed.get("zero_rated_sales") or 0),
        "exempt_sales":             float(ed.get("exempt_sales") or 0),
        "total_sales":              float(ed.get("total_sales") or 0),
        "output_vat":               output_vat,
        "standard_rated_purchases": float(ed.get("standard_rated_purchases") or 0),
        "input_vat":                input_vat,
        "net_vat_payable":          net_declared,
        "vat_paid":                 float(ed.get("vat_paid") or 0),
        "calculated_output_vat":    calc_output,
        "calculated_input_vat":     input_vat,
        "calculated_net":           calc_net,
        "output_discrepancy":       round(output_vat - calc_output, 2),
        "input_discrepancy":        0.0,
        "is_late_filing":           is_late,
        "late_days":                late_days,
        "language":                 str(ed.get("language") or "unknown"),
    }
    return _merge_audit_into_result(base, audit)


def extract_fixed_assets(image_path: str, raw_text: str = "") -> dict:
    prompt = _build_audit_prompt("fixed_asset", _SCHEMAS["fixed_asset"])
    audit  = _call_openai(prompt, image_path, raw_text)
    ed     = audit.get("extracted_data") or audit
    assets = ed.get("assets") or []

    negative_bv = sum(1 for a in assets if float(a.get("book_value") or 0) < 0)
    over_depr   = sum(1 for a in assets
                      if float(a.get("accumulated_depreciation") or 0) > float(a.get("cost") or 0) + 1)
    missing_ids = sum(1 for a in assets if not a.get("asset_id"))
    ids         = [a.get("asset_id", "") for a in assets if a.get("asset_id")]
    dup_ids     = len(ids) - len(set(ids))

    base = {
        "register_date":                  ed.get("register_date"),
        "company_name":                   str(ed.get("company_name") or ""),
        "department":                     str(ed.get("department") or ""),
        "fiscal_year":                    str(ed.get("fiscal_year") or ""),
        "total_cost":                     float(ed.get("total_cost") or 0),
        "total_accumulated_depreciation": float(ed.get("total_accumulated_depreciation") or 0),
        "total_book_value":               float(ed.get("total_book_value") or 0),
        "asset_count":                    int(ed.get("asset_count") or len(assets)),
        "assets":                         assets,
        "negative_book_value_count":      negative_bv,
        "over_depreciated_count":         over_depr,
        "missing_asset_id_count":         missing_ids,
        "duplicate_asset_id_count":       dup_ids,
        "wrong_depreciation_rate":        [],
        "language":                       str(ed.get("language") or "unknown"),
    }
    return _merge_audit_into_result(base, audit)


def extract_sales_receipt(image_path: str, raw_text: str = "") -> dict:
    import hashlib
    prompt = _build_audit_prompt("sales_receipt", _SCHEMAS["sales_receipt"])
    audit  = _call_openai(prompt, image_path, raw_text)
    ed     = audit.get("extracted_data") or audit

    try:
        with open(image_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        file_hash = ""

    base = {
        "receipt_number":      str(ed.get("receipt_number") or ""),
        "receipt_date":        ed.get("receipt_date"),
        "receipt_type":        str(ed.get("receipt_type") or "simplified"),
        "seller_name":         str(ed.get("seller_name") or ""),
        "seller_vat_number":   str(ed.get("seller_vat_number") or ""),
        "customer_name":       str(ed.get("customer_name") or ""),
        "customer_vat_number": str(ed.get("customer_vat_number") or ""),
        "currency":            str(ed.get("currency") or "SAR"),
        "subtotal":            float(ed.get("subtotal") or 0),
        "vat_rate":            float(ed.get("vat_rate") or 15),
        "vat_amount":          float(ed.get("vat_amount") or 0),
        "total_amount":        float(ed.get("total_amount") or 0),
        "line_items":          ed.get("line_items") or [],
        "has_qr_code":         bool(ed.get("has_qr_code")),
        "qr_code_valid":       bool(ed.get("qr_code_valid")),
        "qr_code_data":        {},
        "zatca_uuid":          str(ed.get("zatca_uuid") or ""),
        "file_hash":           file_hash,
        "language":            str(ed.get("language") or "unknown"),
    }
    return _merge_audit_into_result(base, audit)


# ── Router ────────────────────────────────────────────────────────────────────

EXTRACTORS = {
    "purchase_order": extract_purchase_order,
    "bank_statement": extract_bank_statement,
    "payroll":        extract_payroll,
    "expense_report": extract_expense_report,
    "vat_return":     extract_vat_return,
    "fixed_asset":    extract_fixed_assets,
    "sales_receipt":  extract_sales_receipt,
}


def extract_document(doc_type: str, image_path: str, raw_text: str = "") -> dict:
    extractor = EXTRACTORS.get(doc_type)
    if not extractor:
        raise ValueError(f"No extractor for: {doc_type}")
    return extractor(image_path, raw_text)
