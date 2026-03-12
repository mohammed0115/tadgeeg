"""
AI Document Extraction Service
================================
GPT-4o prompts + extraction logic for all 7 financial document types.
Each extractor returns structured JSON matching the typed model fields.
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

def _call_openai(prompt: str, image_path: str, raw_text: str = "") -> dict:
    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured for document extraction.")
        return {}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]

        # Add image if available
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = Path(image_path).suffix.lower().lstrip(".")
            mime = {"pdf": "image/jpeg", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "tiff": "image/tiff"}.get(ext, "image/jpeg")
            messages[0]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}
            })
        except Exception:
            pass

        if raw_text:
            messages[0]["content"].append({"type": "text", "text": f"\n\nOCR Text:\n{raw_text[:3000]}"})

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


# ══════════════════════════════════════════════════════════════════════════════
# 1. Purchase Order
# ══════════════════════════════════════════════════════════════════════════════

PO_PROMPT = """You are an expert in GCC financial documents. Extract ALL data from this Purchase Order.
Return ONLY valid JSON:
{
  "po_number": "",
  "po_date": "YYYY-MM-DD or null",
  "delivery_date": "YYYY-MM-DD or null",
  "vendor_name": "",
  "vendor_vat_number": "",
  "vendor_cr_number": "",
  "requester_name": "",
  "department": "",
  "cost_center": "",
  "account_code": "",
  "currency": "SAR",
  "subtotal": 0.0,
  "vat_amount": 0.0,
  "total_amount": 0.0,
  "line_items": [{"description":"","qty":0,"unit_price":0.0,"total":0.0}],
  "language": "ar|en|mixed",
  "ai_summary": "Brief summary in Arabic or English matching document language"
}
Rules: Saudi VAT numbers are 15 digits. Return null for missing dates, 0 for missing numbers."""

def extract_purchase_order(image_path: str, raw_text: str = "") -> dict:
    data = _call_openai(PO_PROMPT, image_path, raw_text)
    return {
        "po_number":         str(data.get("po_number") or ""),
        "po_date":           data.get("po_date"),
        "delivery_date":     data.get("delivery_date"),
        "vendor_name":       str(data.get("vendor_name") or ""),
        "vendor_vat_number": str(data.get("vendor_vat_number") or ""),
        "vendor_cr_number":  str(data.get("vendor_cr_number") or ""),
        "requester_name":    str(data.get("requester_name") or ""),
        "department":        str(data.get("department") or ""),
        "cost_center":       str(data.get("cost_center") or ""),
        "account_code":      str(data.get("account_code") or ""),
        "currency":          str(data.get("currency") or "SAR"),
        "subtotal":          float(data.get("subtotal") or 0),
        "vat_amount":        float(data.get("vat_amount") or 0),
        "total_amount":      float(data.get("total_amount") or 0),
        "line_items":        data.get("line_items") or [],
        "language":          str(data.get("language") or "unknown"),
        "ai_summary":        str(data.get("ai_summary") or ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. Bank Statement
# ══════════════════════════════════════════════════════════════════════════════

BANK_PROMPT = """You are an expert in GCC bank statements. Extract ALL data from this bank statement.
Return ONLY valid JSON:
{
  "bank_name": "",
  "account_number": "",
  "account_name": "",
  "iban": "",
  "currency": "SAR",
  "statement_period_from": "YYYY-MM-DD or null",
  "statement_period_to": "YYYY-MM-DD or null",
  "opening_balance": 0.0,
  "closing_balance": 0.0,
  "total_credits": 0.0,
  "total_debits": 0.0,
  "transaction_count": 0,
  "transactions": [
    {"date":"YYYY-MM-DD","description":"","debit":0.0,"credit":0.0,"balance":0.0,"ref":""}
  ],
  "language": "ar|en|mixed",
  "ai_summary": "Brief summary"
}
Saudi IBAN format: SA + 22 digits. Extract all visible transactions."""

def extract_bank_statement(image_path: str, raw_text: str = "") -> dict:
    data = _call_openai(BANK_PROMPT, image_path, raw_text)
    transactions = data.get("transactions") or []
    total_credits = sum(float(t.get("credit") or 0) for t in transactions)
    total_debits  = sum(float(t.get("debit")  or 0) for t in transactions)
    opening = float(data.get("opening_balance") or 0)
    closing = float(data.get("closing_balance") or 0)
    calc_closing = round(opening + total_credits - total_debits, 2)
    return {
        "bank_name":              str(data.get("bank_name") or ""),
        "account_number":         str(data.get("account_number") or ""),
        "account_name":           str(data.get("account_name") or ""),
        "iban":                   str(data.get("iban") or ""),
        "currency":               str(data.get("currency") or "SAR"),
        "statement_period_from":  data.get("statement_period_from"),
        "statement_period_to":    data.get("statement_period_to"),
        "opening_balance":        opening,
        "closing_balance":        closing,
        "total_credits":          total_credits or float(data.get("total_credits") or 0),
        "total_debits":           total_debits  or float(data.get("total_debits")  or 0),
        "calculated_closing":     calc_closing,
        "balance_matches":        abs(calc_closing - closing) <= 1.0,
        "transaction_count":      len(transactions) or int(data.get("transaction_count") or 0),
        "transactions":           transactions,
        "language":               str(data.get("language") or "unknown"),
        "ai_summary":             str(data.get("ai_summary") or ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. Payroll Sheet
# ══════════════════════════════════════════════════════════════════════════════

PAYROLL_PROMPT = """You are an expert in Saudi/GCC payroll documents. Extract ALL data from this payroll sheet.
Return ONLY valid JSON:
{
  "payroll_period_from": "YYYY-MM-DD or null",
  "payroll_period_to": "YYYY-MM-DD or null",
  "payment_date": "YYYY-MM-DD or null",
  "department": "",
  "company_name": "",
  "currency": "SAR",
  "employee_count": 0,
  "total_gross_salary": 0.0,
  "total_allowances": 0.0,
  "total_deductions": 0.0,
  "total_gosi": 0.0,
  "total_net_salary": 0.0,
  "employees": [
    {
      "id": "", "name": "", "name_ar": "",
      "gross": 0.0, "allowances": 0.0, "deductions": 0.0,
      "gosi": 0.0, "net": 0.0, "bank_account": ""
    }
  ],
  "language": "ar|en|mixed",
  "ai_summary": "Brief summary"
}
Saudi GOSI rate is typically 11.75% (employer 11.25% + employee 0.5% for Saudis)."""

def extract_payroll(image_path: str, raw_text: str = "") -> dict:
    data = _call_openai(PAYROLL_PROMPT, image_path, raw_text)
    employees = data.get("employees") or []

    # Detect duplicates
    ids = [e.get("id","") for e in employees if e.get("id")]
    dup_ids = list({i for i in ids if ids.count(i) > 1})

    # Detect calculation errors
    calc_errors = []
    for e in employees:
        gross = float(e.get("gross") or 0)
        ded   = float(e.get("deductions") or 0)
        gosi  = float(e.get("gosi") or 0)
        net   = float(e.get("net") or 0)
        expected_net = gross + float(e.get("allowances") or 0) - ded - gosi
        if abs(net - expected_net) > 5 and net > 0:
            calc_errors.append(e.get("id") or e.get("name") or "?")

    return {
        "payroll_period_from":  data.get("payroll_period_from"),
        "payroll_period_to":    data.get("payroll_period_to"),
        "payment_date":         data.get("payment_date"),
        "department":           str(data.get("department") or ""),
        "company_name":         str(data.get("company_name") or ""),
        "currency":             str(data.get("currency") or "SAR"),
        "employee_count":       int(data.get("employee_count") or len(employees)),
        "total_gross_salary":   float(data.get("total_gross_salary") or 0),
        "total_allowances":     float(data.get("total_allowances") or 0),
        "total_deductions":     float(data.get("total_deductions") or 0),
        "total_gosi":           float(data.get("total_gosi") or 0),
        "total_net_salary":     float(data.get("total_net_salary") or 0),
        "employees":            employees,
        "duplicate_employee_ids": dup_ids,
        "calculation_errors":   calc_errors,
        "language":             str(data.get("language") or "unknown"),
        "ai_summary":           str(data.get("ai_summary") or ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. Expense Report
# ══════════════════════════════════════════════════════════════════════════════

EXPENSE_PROMPT = """You are an expert in GCC expense reports. Extract ALL data from this expense report.
Return ONLY valid JSON:
{
  "report_number": "",
  "employee_name": "",
  "employee_id": "",
  "department": "",
  "report_period_from": "YYYY-MM-DD or null",
  "report_period_to": "YYYY-MM-DD or null",
  "submitted_date": "YYYY-MM-DD or null",
  "currency": "SAR",
  "purpose": "",
  "total_claimed": 0.0,
  "vat_included": 0.0,
  "expense_lines": [
    {
      "date": "YYYY-MM-DD",
      "category": "travel|accommodation|meals|office|communication|training|maintenance|other",
      "description": "",
      "amount": 0.0,
      "receipt_attached": true,
      "receipt_number": ""
    }
  ],
  "language": "ar|en|mixed",
  "ai_summary": "Brief summary"
}"""

def extract_expense_report(image_path: str, raw_text: str = "") -> dict:
    data = _call_openai(EXPENSE_PROMPT, image_path, raw_text)
    lines = data.get("expense_lines") or []
    missing_receipts = sum(1 for l in lines if not l.get("receipt_attached", True))
    calc_total = sum(float(l.get("amount") or 0) for l in lines)
    return {
        "report_number":       str(data.get("report_number") or ""),
        "employee_name":       str(data.get("employee_name") or ""),
        "employee_id":         str(data.get("employee_id") or ""),
        "department":          str(data.get("department") or ""),
        "report_period_from":  data.get("report_period_from"),
        "report_period_to":    data.get("report_period_to"),
        "submitted_date":      data.get("submitted_date"),
        "currency":            str(data.get("currency") or "SAR"),
        "purpose":             str(data.get("purpose") or ""),
        "total_claimed":       float(data.get("total_claimed") or calc_total),
        "vat_included":        float(data.get("vat_included") or 0),
        "expense_lines":       lines,
        "missing_receipts_count": missing_receipts,
        "language":            str(data.get("language") or "unknown"),
        "ai_summary":          str(data.get("ai_summary") or ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. VAT Return
# ══════════════════════════════════════════════════════════════════════════════

VAT_RETURN_PROMPT = """You are a ZATCA VAT compliance expert. Extract ALL data from this VAT return (إقرار ضريبة القيمة المضافة).
Return ONLY valid JSON:
{
  "taxpayer_name": "",
  "vat_number": "",
  "cr_number": "",
  "period_from": "YYYY-MM-DD or null",
  "period_to": "YYYY-MM-DD or null",
  "filing_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "zatca_reference": "",
  "standard_rated_sales": 0.0,
  "zero_rated_sales": 0.0,
  "exempt_sales": 0.0,
  "total_sales": 0.0,
  "output_vat": 0.0,
  "standard_rated_purchases": 0.0,
  "input_vat": 0.0,
  "net_vat_payable": 0.0,
  "vat_paid": 0.0,
  "language": "ar|en|mixed",
  "ai_summary": "Brief summary"
}
Saudi VAT number: 15 digits starting and ending with 3."""

def extract_vat_return(image_path: str, raw_text: str = "") -> dict:
    from datetime import date as dt
    data = _call_openai(VAT_RETURN_PROMPT, image_path, raw_text)

    output_vat   = float(data.get("output_vat") or 0)
    input_vat    = float(data.get("input_vat")  or 0)
    net_declared = float(data.get("net_vat_payable") or 0)
    std_sales    = float(data.get("standard_rated_sales") or 0)

    calc_output = round(std_sales * 0.15, 2)
    calc_net    = round(output_vat - input_vat, 2)

    # Late filing check
    due_str  = data.get("due_date")
    file_str = data.get("filing_date")
    is_late  = False
    late_days = 0
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

    return {
        "taxpayer_name":          str(data.get("taxpayer_name") or ""),
        "vat_number":             str(data.get("vat_number") or ""),
        "cr_number":              str(data.get("cr_number") or ""),
        "period_from":            data.get("period_from"),
        "period_to":              data.get("period_to"),
        "filing_date":            data.get("filing_date"),
        "due_date":               data.get("due_date"),
        "zatca_reference":        str(data.get("zatca_reference") or ""),
        "standard_rated_sales":   std_sales,
        "zero_rated_sales":       float(data.get("zero_rated_sales") or 0),
        "exempt_sales":           float(data.get("exempt_sales") or 0),
        "total_sales":            float(data.get("total_sales") or 0),
        "output_vat":             output_vat,
        "standard_rated_purchases": float(data.get("standard_rated_purchases") or 0),
        "input_vat":              input_vat,
        "net_vat_payable":        net_declared,
        "vat_paid":               float(data.get("vat_paid") or 0),
        "calculated_output_vat":  calc_output,
        "calculated_input_vat":   input_vat,
        "calculated_net":         calc_net,
        "output_discrepancy":     round(output_vat - calc_output, 2),
        "input_discrepancy":      0.0,
        "is_late_filing":         is_late,
        "late_days":              late_days,
        "language":               str(data.get("language") or "unknown"),
        "ai_summary":             str(data.get("ai_summary") or ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. Fixed Asset Ledger
# ══════════════════════════════════════════════════════════════════════════════

ASSET_PROMPT = """You are an expert in fixed asset accounting (IFRS/SOCPA). Extract ALL data from this fixed asset register.
Return ONLY valid JSON:
{
  "register_date": "YYYY-MM-DD or null",
  "company_name": "",
  "department": "",
  "fiscal_year": "",
  "total_cost": 0.0,
  "total_accumulated_depreciation": 0.0,
  "total_book_value": 0.0,
  "asset_count": 0,
  "assets": [
    {
      "asset_id": "", "name": "", "name_ar": "",
      "category": "land|buildings|vehicles|equipment|computers|furniture|other",
      "purchase_date": "YYYY-MM-DD or null",
      "cost": 0.0,
      "useful_life_years": 0,
      "method": "straight_line|declining|units|none",
      "annual_depreciation": 0.0,
      "accumulated_depreciation": 0.0,
      "book_value": 0.0,
      "is_fully_depreciated": false
    }
  ],
  "language": "ar|en|mixed",
  "ai_summary": "Brief summary"
}"""

def extract_fixed_assets(image_path: str, raw_text: str = "") -> dict:
    data = _call_openai(ASSET_PROMPT, image_path, raw_text)
    assets = data.get("assets") or []

    # Detect anomalies
    negative_bv    = sum(1 for a in assets if float(a.get("book_value") or 0) < 0)
    over_depr      = sum(1 for a in assets
                         if float(a.get("accumulated_depreciation") or 0) > float(a.get("cost") or 0) + 1)
    missing_ids    = sum(1 for a in assets if not a.get("asset_id"))
    ids            = [a.get("asset_id","") for a in assets if a.get("asset_id")]
    dup_ids        = len(ids) - len(set(ids))

    return {
        "register_date":              data.get("register_date"),
        "company_name":               str(data.get("company_name") or ""),
        "department":                 str(data.get("department") or ""),
        "fiscal_year":                str(data.get("fiscal_year") or ""),
        "total_cost":                 float(data.get("total_cost") or 0),
        "total_accumulated_depreciation": float(data.get("total_accumulated_depreciation") or 0),
        "total_book_value":           float(data.get("total_book_value") or 0),
        "asset_count":                int(data.get("asset_count") or len(assets)),
        "assets":                     assets,
        "negative_book_value_count":  negative_bv,
        "over_depreciated_count":     over_depr,
        "missing_asset_id_count":     missing_ids,
        "duplicate_asset_id_count":   dup_ids,
        "wrong_depreciation_rate":    [],
        "language":                   str(data.get("language") or "unknown"),
        "ai_summary":                 str(data.get("ai_summary") or ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 7. Sales Receipt
# ══════════════════════════════════════════════════════════════════════════════

RECEIPT_PROMPT = """You are a ZATCA Phase 2 compliance expert. Extract ALL data from this sales receipt/tax invoice.
Return ONLY valid JSON:
{
  "receipt_number": "",
  "receipt_date": "YYYY-MM-DD or null",
  "receipt_type": "standard|simplified|credit|debit",
  "seller_name": "",
  "seller_vat_number": "",
  "customer_name": "",
  "customer_vat_number": "",
  "currency": "SAR",
  "subtotal": 0.0,
  "vat_rate": 15.0,
  "vat_amount": 0.0,
  "total_amount": 0.0,
  "line_items": [{"description":"","qty":0,"unit_price":0.0,"total":0.0}],
  "has_qr_code": false,
  "qr_code_valid": false,
  "zatca_uuid": "",
  "language": "ar|en|mixed",
  "ai_summary": "Brief summary"
}
ZATCA QR code is a TLV-encoded base64 string in the bottom of simplified invoices."""

def extract_sales_receipt(image_path: str, raw_text: str = "") -> dict:
    import hashlib, io
    data = _call_openai(RECEIPT_PROMPT, image_path, raw_text)
    try:
        with open(image_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        file_hash = ""

    return {
        "receipt_number":     str(data.get("receipt_number") or ""),
        "receipt_date":       data.get("receipt_date"),
        "receipt_type":       str(data.get("receipt_type") or "simplified"),
        "seller_name":        str(data.get("seller_name") or ""),
        "seller_vat_number":  str(data.get("seller_vat_number") or ""),
        "customer_name":      str(data.get("customer_name") or ""),
        "customer_vat_number":str(data.get("customer_vat_number") or ""),
        "currency":           str(data.get("currency") or "SAR"),
        "subtotal":           float(data.get("subtotal") or 0),
        "vat_rate":           float(data.get("vat_rate") or 15),
        "vat_amount":         float(data.get("vat_amount") or 0),
        "total_amount":       float(data.get("total_amount") or 0),
        "line_items":         data.get("line_items") or [],
        "has_qr_code":        bool(data.get("has_qr_code")),
        "qr_code_valid":      bool(data.get("qr_code_valid")),
        "qr_code_data":       {},
        "zatca_uuid":         str(data.get("zatca_uuid") or ""),
        "file_hash":          file_hash,
        "language":           str(data.get("language") or "unknown"),
        "ai_summary":         str(data.get("ai_summary") or ""),
    }


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
