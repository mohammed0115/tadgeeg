"""
AI Invoice Analysis Service
Uses OpenAI GPT-4o + Tesseract OCR to extract and analyze invoice data.
"""

import base64
import json
import logging
from pathlib import Path
from django.conf import settings

from core.ai.openai_client import OpenAI

logger = logging.getLogger("finai")


INVOICE_EXTRACTION_PROMPT = """You are an expert financial document analyst specializing in GCC (Gulf Cooperation Council) invoices.
Extract ALL data from this invoice image with maximum accuracy.
Support Arabic (RTL) and English (LTR) text equally.

Return ONLY a valid JSON object with this exact structure:
{
  "invoice_number": "",
  "invoice_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "vendor_name": "",
  "vendor_name_ar": "",
  "vendor_vat_number": "",
  "vendor_cr_number": "",
  "vendor_address": "",
  "vendor_phone": "",
  "customer_name": "",
  "customer_vat_number": "",
  "currency": "SAR",
  "subtotal": 0.0,
  "vat_rate": 15.0,
  "vat_amount": 0.0,
  "discount": 0.0,
  "total_amount": 0.0,
  "line_items": [
    {"description": "", "quantity": 0, "unit_price": 0.0, "total": 0.0, "vat_rate": 15.0}
  ],
  "has_qr_code": false,
  "qr_code_valid": false,
  "is_handwritten": false,
  "is_clear": true,
  "has_alterations": false,
  "language": "ar|en|mixed",
  "payment_terms": "",
  "notes": "",
  "ai_fraud_suspected": false,
  "ai_fraud_indicators": [],
  "ai_confidence": 0-100,
  "ai_summary": "Brief summary in the same language as the invoice"
}

Critical extraction rules:
- Saudi VAT numbers are 15 digits starting and ending with 3
- ZATCA QR code is a small square barcode usually in the top-right corner
- If any field is not found, use null for dates and 0 for numbers, empty string for text
- Set ai_fraud_suspected=true if you notice inconsistencies, mismatched fonts, or suspicious patterns
- List specific fraud indicators in ai_fraud_indicators array
"""

INVOICE_RISK_PROMPT = """You are a senior financial auditor for GCC organizations.
Analyze this invoice data and provide a risk assessment.
Return ONLY JSON:
{
  "overall_risk_score": 0-100,
  "risk_level": "low|medium|high|critical",
  "risk_factors": [
    {"factor": "string", "severity": "low|medium|high|critical", "description": "string"}
  ],
  "fraud_indicators": ["string"],
  "compliance_issues": ["string"],
  "recommendations": ["string"],
  "ai_summary": "Professional summary of findings in 2-3 sentences",
  "requires_manual_review": true|false,
  "requires_escalation": true|false
}"""


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".pdf"}
_TEXT_EXTS  = {".xlsx", ".xls", ".json", ".csv"}


def extract_invoice_with_ai(image_path: str, raw_text: str = "") -> dict:
    """
    Extract structured invoice data using OpenAI GPT-4o.

    - Image/PDF files  → GPT-4o Vision (base64 image_url)
    - Excel/JSON files → GPT-4o text-only (raw_text already extracted)

    Args:
        image_path: Path to the stored file.
        raw_text: Pre-extracted text (Tesseract for images, pandas/json for xlsx/json).

    Returns:
        dict with extracted invoice fields.
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI not configured — using text-only extraction.")
        return _fallback_extraction(raw_text)

    # Per-org daily budget guard. Falls back to deterministic regex extraction
    # if the org has hit its cap, instead of throwing — uploads still succeed
    # but stop spending money.
    from core.services import ai_budget
    try:
        ai_budget.guard_current(projected_tokens=4000)
    except ai_budget.BudgetExceeded:
        logger.warning("[ai-budget] using fallback extraction (budget exceeded)")
        return _fallback_extraction(raw_text)

    ext = Path(image_path).suffix.lower()
    use_vision = ext in _IMAGE_EXTS

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        if use_vision:
            # ── Vision path (PDF rendered to image, JPG, PNG, TIFF) ──────────
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".png": "image/png", ".tiff": "image/tiff", ".tif": "image/tiff"}
            mime_type = mime_map.get(ext, "image/png")

            user_content = []
            if raw_text:
                user_content.append({
                    "type": "text",
                    "text": f"Pre-extracted text (Tesseract):\n{raw_text[:2000]}\n\nNow analyze the image:"
                })
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_data}", "detail": "high"}
            })

            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": INVOICE_EXTRACTION_PROMPT},
                    {"role": "user",   "content": user_content},
                ],
                max_tokens=2000,
                response_format={"type": "json_object"},
                temperature=0,
            )
            method = "openai_vision"

        else:
            # ── Text-only path (xlsx, xls, json, csv) ────────────────────────
            if not raw_text:
                logger.warning(f"No raw_text for text-only extraction of {image_path}")
                return _fallback_extraction(raw_text)

            text_prompt = (
                f"The following is the full text content extracted from a financial document "
                f"({ext} file). Extract all invoice fields as specified.\n\n"
                f"Document content:\n{raw_text[:6000]}"
            )

            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": INVOICE_EXTRACTION_PROMPT},
                    {"role": "user",   "content": text_prompt},
                ],
                max_tokens=2000,
                response_format={"type": "json_object"},
                temperature=0,
            )
            method = "openai_text"

        data = json.loads(response.choices[0].message.content)
        data["_extraction_method"] = method
        data["_tokens_used"] = response.usage.total_tokens
        # The unified gateway already records and charges actual token usage.
        return data

    except Exception as e:
        logger.error(f"OpenAI invoice extraction failed: {e}")
        return {**_fallback_extraction(raw_text), "_extraction_error": str(e)}


def analyze_invoice_risk(invoice_data: dict, vendor_history: dict = None) -> dict:
    """
    Run AI risk analysis on extracted invoice data.

    Args:
        invoice_data: Extracted invoice fields.
        vendor_history: Dict with vendor statistics (avg_amount, invoice_count, etc.)

    Returns:
        dict with risk assessment.
    """
    if not settings.OPENAI_API_KEY:
        return {"overall_risk_score": 0, "risk_level": "unknown", "error": "OpenAI not configured"}

    from core.services import ai_budget
    try:
        ai_budget.guard_current(projected_tokens=2000)
    except ai_budget.BudgetExceeded:
        return {"overall_risk_score": 0, "risk_level": "unknown", "error": "AI budget exceeded"}

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        context = ""
        if vendor_history:
            context = f"""
Vendor historical context:
- Previous invoices: {vendor_history.get('invoice_count', 0)}
- Average invoice amount: {vendor_history.get('avg_amount', 0):.2f} {invoice_data.get('currency', 'SAR')}
- Max invoice amount: {vendor_history.get('max_amount', 0):.2f}
- Is new vendor: {vendor_history.get('is_new', True)}
- Previous flags: {vendor_history.get('flagged_count', 0)}
"""

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": INVOICE_RISK_PROMPT},
                {"role": "user", "content": f"{context}\nInvoice data:\n{json.dumps(invoice_data, ensure_ascii=False, default=str)}"},
            ],
            max_tokens=1500,
            response_format={"type": "json_object"},
            temperature=0,
        )

        data = json.loads(response.choices[0].message.content)
        data["_tokens_used"] = response.usage.total_tokens
        # The unified gateway already records and charges actual token usage.
        return data

    except Exception as e:
        logger.error(f"AI risk analysis failed: {e}")
        return {"overall_risk_score": 0, "risk_level": "unknown", "error": str(e)}


def _fallback_extraction(raw_text: str) -> dict:
    """Regex-based extraction when OpenAI is unavailable."""
    import re

    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip(" :-–—\t")

    def _parse_amount(value: str) -> float:
        text = _clean_text(value).replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return 0.0
        try:
            return float(match.group(0))
        except ValueError:
            return 0.0

    def _find_first_match(patterns, text, flags=re.IGNORECASE):
        for pattern in patterns:
            match = re.search(pattern, text, flags)
            if match:
                return _clean_text(match.group(1))
        return ""

    def _extract_labeled_amount(patterns, text) -> float:
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            cleaned = [_parse_amount(value) for value in matches if _parse_amount(value) > 0]
            if cleaned:
                return cleaned[-1]
        return 0.0

    def _looks_like_vendor(line: str) -> bool:
        lowered = line.lower()
        blacklist = [
            "invoice", "date", "tax", "vat", "total", "subtotal", "amount", "balance", "due",
            "فاتورة", "تاريخ", "الضريبة", "المجموع", "الإجمالي", "الاجمالي", "المبلغ", "الاستحقاق",
            "العميل", "customer", "bill to", "ship to", "qty", "quantity", "price", "payment",
        ]
        if any(token in lowered for token in blacklist):
            return False
        if len(line) < 4 or len(line) > 80:
            return False
        if re.fullmatch(r"[\W\d_]+", line):
            return False
        if re.search(r"\d{5,}", line):
            return False
        return bool(re.search(r"[A-Za-z\u0600-\u06FF]", line))

    def _detect_vendor_name(text: str, lines: list[str]) -> str:
        explicit = _find_first_match(
            [
                r"(?:supplier|vendor|merchant|company|seller|from|اسم\s*المورد|اسم\s*البائع|اسم\s*الشركة|المورد|البائع|المنشأة)\s*[:#-]?\s*(.+)",
            ],
            text,
        )
        if explicit and _looks_like_vendor(explicit):
            return explicit

        vat_line_index = next(
            (
                index
                for index, line in enumerate(lines)
                if re.search(r"(?:vat|الرقم\s*الضريبي|رقم\s*الضريبة|ضريبة)", line, re.IGNORECASE)
            ),
            None,
        )
        if vat_line_index is not None:
            for candidate in reversed(lines[max(0, vat_line_index - 2):vat_line_index]):
                if _looks_like_vendor(candidate):
                    return candidate

        for line in lines[:12]:
            if _looks_like_vendor(line):
                return line

        return ""

    def _detect_language(text: str) -> str:
        has_arabic = bool(re.search(r"[\u0600-\u06FF]", text))
        has_latin = bool(re.search(r"[A-Za-z]", text))
        if has_arabic and has_latin:
            return "mixed"
        if has_arabic:
            return "ar"
        if has_latin:
            return "en"
        return "unknown"

    normalized_text = str(raw_text or "")
    lines = [_clean_text(line) for line in re.split(r"[\r\n]+", normalized_text) if _clean_text(line)]

    result = {
        "invoice_number": "", "invoice_date": None, "due_date": None,
        "vendor_name": "", "vendor_name_ar": "", "vendor_vat_number": "",
        "vendor_cr_number": "", "vendor_address": "", "vendor_phone": "",
        "customer_name": "", "customer_vat_number": "",
        "currency": "SAR", "subtotal": 0.0, "vat_rate": 15.0,
        "vat_amount": 0.0, "discount": 0.0, "total_amount": 0.0,
        "line_items": [], "has_qr_code": False, "qr_code_valid": False,
        "is_handwritten": False, "is_clear": True, "has_alterations": False,
        "language": _detect_language(normalized_text), "payment_terms": "", "notes": "",
        "ai_fraud_suspected": False, "ai_fraud_indicators": [],
        "ai_confidence": 52,
        "ai_summary": "تم استخراج البيانات عبر OCR المحلي مع تطبيق قواعد تحقق تلقائية. يُنصح بمراجعة الحقول الحساسة قبل الاعتماد النهائي.",
        "_extraction_method": "tesseract_fallback",
    }

    if not normalized_text:
        return result

    invoice_number = _find_first_match(
        [
            r"(?im)^\s*(?:invoice\s*(?:no\.?|number|#)|inv\s*#|رقم\s*الفاتورة|فاتورة\s*رقم|رقم\s*المرجع)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})\b",
        ],
        normalized_text,
    )
    if invoice_number:
        result["invoice_number"] = invoice_number

    invoice_date = _find_first_match(
        [
            r"(?:invoice\s*date|issue\s*date|date|تاريخ\s*الفاتورة|تاريخ\s*الإصدار|التاريخ)\s*[:#-]?\s*(\d{1,4}[/-]\d{1,2}[/-]\d{1,4})",
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        ],
        normalized_text,
    )
    if invoice_date:
        result["invoice_date"] = invoice_date

    due_date = _find_first_match(
        [
            r"(?:due\s*date|payment\s*due|تاريخ\s*الاستحقاق|الاستحقاق)\s*[:#-]?\s*(\d{1,4}[/-]\d{1,2}[/-]\d{1,4})",
        ],
        normalized_text,
    )
    if due_date:
        result["due_date"] = due_date

    vendor_name = _detect_vendor_name(normalized_text, lines)
    if vendor_name:
        result["vendor_name"] = vendor_name
        if re.search(r"[\u0600-\u06FF]", vendor_name):
            result["vendor_name_ar"] = vendor_name

    # Saudi VAT number (15 digits starting with 3)
    m = re.search(r"\b3\d{13}3\b", normalized_text)
    if m:
        result["vendor_vat_number"] = m.group(0)

    subtotal = _extract_labeled_amount(
        [
            r"(?:subtotal|before\s*vat|صافي\s*قبل\s*الضريبة|الإجمالي\s*قبل\s*الضريبة|المجموع\s*قبل\s*الضريبة)\s*[:#-]?\s*([\d,]+\.?\d{0,2})",
        ],
        normalized_text,
    )
    if subtotal > 0:
        result["subtotal"] = subtotal

    vat_amount = _extract_labeled_amount(
        [
            r"(?:vat\s*(?:amount)?|tax\s*amount|ضريبة(?:\s*القيمة\s*المضافة)?|قيمة\s*الضريبة)\s*[:#-]?\s*([\d,]+\.?\d{0,2})",
        ],
        normalized_text,
    )
    if vat_amount > 0:
        result["vat_amount"] = vat_amount

    total_amount = _extract_labeled_amount(
        [
            r"(?:grand\s*total|total\s*amount|invoice\s*total|الإجمالي\s*النهائي|الإجمالي|المجموع\s*الكلي|المبلغ\s*الإجمالي)\s*[:#-]?\s*([\d,]+\.?\d{0,2})",
        ],
        normalized_text,
    )
    if total_amount > 0:
        result["total_amount"] = total_amount

    # Currency
    for cur in ["SAR", "AED", "USD", "EUR", "KWD", "QAR", "ريال", "درهم"]:
        if cur in normalized_text:
            result["currency"] = "SAR" if cur == "ريال" else ("AED" if cur == "درهم" else cur)
            break

    if result["subtotal"] <= 0 and result["total_amount"] > 0 and result["vat_amount"] > 0:
        result["subtotal"] = max(result["total_amount"] - result["vat_amount"], 0.0)

    if result["subtotal"] > 0 and result["vat_amount"] > 0:
        result["vat_rate"] = round((result["vat_amount"] / result["subtotal"]) * 100, 2)

    if result["vendor_name"] and not result["vendor_name_ar"] and re.search(r"[\u0600-\u06FF]", result["vendor_name"]):
        result["vendor_name_ar"] = result["vendor_name"]

    return result
