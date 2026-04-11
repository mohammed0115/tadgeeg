"""
OCR Service — Tesseract (default) + OpenAI GPT-4 Vision (enhancement)
"""

import base64
import io
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger("finai")


def _resolve_tesseract_cmd() -> str:
    """Resolve a working Tesseract executable path across dev environments."""
    configured = str(getattr(settings, "TESSERACT_CMD", "") or "").strip()

    candidates = []
    if configured:
        candidates.append(configured)
        resolved_configured = shutil.which(configured)
        if resolved_configured:
            candidates.append(resolved_configured)

    resolved_default = shutil.which("tesseract")
    if resolved_default:
        candidates.append(resolved_default)

    if os.name == "nt":
        candidates.extend([
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            str(Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
        ])

    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate_path.exists():
            return str(candidate_path)

    return configured or "tesseract"


def _parse_confidence(value) -> float:
    try:
        confidence = float(str(value).strip())
    except (TypeError, ValueError):
        return -1.0
    return confidence if confidence > 0 else -1.0


# ─── Tesseract OCR ─────────────────────────────────────────────────────────────

def extract_text_tesseract(image_path: str, languages: str = None) -> dict:
    """
    Extract text using Tesseract OCR.

    Args:
        image_path: Path to the image file.
        languages: Tesseract language string e.g. 'ara+eng'.

    Returns:
        dict with keys: text, confidence, word_data
    """
    try:
        import pytesseract
        from PIL import Image

        pytesseract.pytesseract.tesseract_cmd = _resolve_tesseract_cmd()
        langs = languages or settings.TESSERACT_LANGUAGES

        image = Image.open(image_path)
        image = _preprocess_image(image)

        # Full text
        custom_config = f"--oem 3 --psm 6 -l {langs}"
        text = pytesseract.image_to_string(image, config=custom_config)

        # Confidence data
        data = pytesseract.image_to_data(image, config=custom_config, output_type=pytesseract.Output.DICT)
        valid_confidences = [
            confidence
            for confidence in (_parse_confidence(raw_confidence) for raw_confidence in data["conf"])
            if confidence > 0
        ]
        avg_confidence = sum(valid_confidences) / len(valid_confidences) if valid_confidences else 0.0

        # Collect word-level data
        word_data = []
        n = len(data["text"])
        for i in range(n):
            word = data["text"][i].strip()
            conf = _parse_confidence(data["conf"][i])
            if word and conf > 0:
                word_data.append({
                    "word": word,
                    "confidence": round(conf, 2),
                    "left": data["left"][i],
                    "top": data["top"][i],
                    "width": data["width"][i],
                    "height": data["height"][i],
                })

        return {
            "text": text.strip(),
            "confidence": round(avg_confidence, 2),
            "word_data": word_data,
            "method": "tesseract",
        }

    except ImportError:
        logger.error("pytesseract or Pillow not installed. Install with: pip install pytesseract Pillow")
        raise
    except Exception as e:
        logger.error(f"Tesseract OCR error: {e}")
        raise


def _preprocess_image(image):
    """Apply basic image preprocessing to improve OCR accuracy."""
    try:
        from PIL import ImageFilter, ImageEnhance
        # Convert to RGB if needed
        if image.mode != "RGB":
            image = image.convert("RGB")
        # Sharpen
        image = image.filter(ImageFilter.SHARPEN)
        # Increase contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.5)
        return image
    except Exception:
        return image


def pdf_to_images(pdf_path: str) -> list[str]:
    """
    Convert each page of a PDF to an image file.

    Returns:
        List of temp image file paths.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        image_paths = []
        tmp_dir = Path(settings.MEDIA_ROOT) / "tmp_ocr"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom = ~144 DPI
            pix = page.get_pixmap(matrix=mat)
            img_path = str(tmp_dir / f"page_{page_num + 1}_{int(time.time())}.png")
            pix.save(img_path)
            image_paths.append(img_path)

        doc.close()
        return image_paths

    except ImportError:
        logger.warning("PyMuPDF not installed. Trying Pillow fallback for PDF.")
        # Fallback: convert via Pillow (only works for image-based PDFs)
        from PIL import Image
        tmp_dir = Path(settings.MEDIA_ROOT) / "tmp_ocr"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            img = Image.open(pdf_path)
            paths = []
            for i, frame in enumerate(_get_frames(img)):
                path = str(tmp_dir / f"page_{i + 1}_{int(time.time())}.png")
                frame.save(path)
                paths.append(path)
            return paths
        except Exception as e:
            logger.error(f"PDF to image conversion failed: {e}")
            return [pdf_path]


def _get_frames(image):
    try:
        i = 0
        while True:
            image.seek(i)
            yield image.copy()
            i += 1
    except EOFError:
        pass


# ─── OpenAI Vision OCR ────────────────────────────────────────────────────────

OCR_TEXT_PROMPT = """You are a high-accuracy OCR engine for financial documents in Arabic and English.
Read ALL text from this image exactly as it appears — preserve numbers, dates, VAT numbers, amounts, and labels.
Output ONLY a JSON object with this structure:
{
  "text": "<full verbatim text, use \\n for line breaks>",
  "confidence": <0-100, your OCR confidence>,
  "language": "ar|en|mixed",
  "is_handwritten": false
}
Do not interpret or summarize — extract every character you can see."""


def extract_text_openai(image_path: str) -> dict:
    """
    Use GPT-4o Vision as an OCR engine to extract raw text from an image.

    Returns:
        dict with keys: text, confidence, language, is_handwritten, method
    """
    if not settings.OPENAI_API_KEY:
        return {"text": "", "confidence": 0.0, "language": "unknown",
                "is_handwritten": False, "method": "openai_ocr_skipped"}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        ext = Path(image_path).suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".tiff": "image/tiff", ".tif": "image/tiff"}
        mime_type = mime_map.get(ext, "image/png")

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": OCR_TEXT_PROMPT},
                {"role": "user", "content": [{
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_data}", "detail": "high"}
                }]},
            ],
            max_tokens=4000,
            response_format={"type": "json_object"},
            temperature=0,
        )

        data = json.loads(response.choices[0].message.content)
        return {
            "text":           data.get("text", ""),
            "confidence":     float(data.get("confidence", 90)),
            "language":       data.get("language", "unknown"),
            "is_handwritten": bool(data.get("is_handwritten", False)),
            "method":         "openai_ocr",
            "tokens_used":    response.usage.total_tokens,
        }

    except Exception as e:
        logger.error(f"OpenAI OCR failed for {image_path}: {e}")
        return {"text": "", "confidence": 0.0, "language": "unknown",
                "is_handwritten": False, "method": "openai_ocr_failed", "error": str(e)}


# ─── OpenAI Vision Enhancement ────────────────────────────────────────────────

def enhance_with_openai(image_path: str, document_type: str, raw_text: str = "") -> dict:
    """
    Use OpenAI GPT-4 Vision to extract structured financial data from an image.

    Args:
        image_path: Path to the image/document file.
        document_type: e.g. 'invoice', 'receipt', 'bank_statement'.
        raw_text: Optional pre-extracted Tesseract text to provide as context.

    Returns:
        dict with structured financial fields.
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI API key not set. Skipping AI enhancement.")
        return {}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        # Encode image to base64
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Determine image mime type
        ext = Path(image_path).suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                    ".tiff": "image/tiff", ".tif": "image/tiff"}
        mime_type = mime_map.get(ext, "image/png")

        system_prompt = _build_extraction_prompt(document_type)
        user_content = []

        if raw_text:
            user_content.append({
                "type": "text",
                "text": f"Pre-extracted text (for context):\n{raw_text[:3000]}\n\nNow analyze the image:"
            })

        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{image_data}",
                "detail": "high"
            }
        })

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=settings.OPENAI_MAX_TOKENS,
            response_format={"type": "json_object"},
            temperature=0,
        )

        content = response.choices[0].message.content
        structured_data = json.loads(content)
        structured_data["_ai_model"] = settings.OPENAI_MODEL
        structured_data["_tokens_used"] = response.usage.total_tokens

        return structured_data

    except Exception as e:
        logger.error(f"OpenAI vision extraction error: {e}")
        return {"_error": str(e)}


def _build_extraction_prompt(document_type: str) -> str:
    base = """You are an expert financial document analyzer for GCC (Gulf Cooperation Council) countries.
Extract ALL financial data from the document with maximum accuracy.
Support Arabic (RTL) and English (LTR) text equally.
Return a valid JSON object only — no markdown, no explanation.
"""
    type_prompts = {
        "invoice": base + """
For an invoice, extract:
{
  "document_type": "invoice",
  "language": "ar|en|mixed",
  "is_handwritten": false,
  "vendor": {"name": "", "name_ar": "", "vat_number": "", "cr_number": "", "address": "", "phone": ""},
  "customer": {"name": "", "name_ar": "", "vat_number": "", "address": ""},
  "invoice_number": "",
  "invoice_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "currency": "SAR",
  "line_items": [{"description": "", "quantity": 0, "unit_price": 0, "total": 0, "vat_rate": 15}],
  "subtotal": 0,
  "vat_amount": 0,
  "discount": 0,
  "total_amount": 0,
  "payment_terms": "",
  "qr_code_detected": false,
  "zatca_qr_string": "",
  "vendor_trn": "",
  "zatca_compliant": false,
  "notes": ""
}

IMPORTANT: If you see a QR code anywhere on the invoice image, set qr_code_detected to true and extract the base64 TLV string into zatca_qr_string. Also extract the 15-digit Saudi TRN into vendor_trn.""",
        "receipt": base + """
For a receipt, extract:
{
  "document_type": "receipt",
  "language": "ar|en|mixed",
  "vendor": {"name": "", "address": ""},
  "receipt_number": "",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "currency": "SAR",
  "items": [{"description": "", "amount": 0}],
  "subtotal": 0,
  "vat_amount": 0,
  "total_amount": 0,
  "payment_method": "cash|card|transfer"
}""",
        "bank_statement": base + """
For a bank statement, extract:
{
  "document_type": "bank_statement",
  "language": "ar|en|mixed",
  "bank_name": "",
  "account_number": "",
  "account_holder": "",
  "currency": "SAR",
  "statement_period": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
  "opening_balance": 0,
  "closing_balance": 0,
  "total_credits": 0,
  "total_debits": 0,
  "transactions": [
    {"date": "YYYY-MM-DD", "description": "", "debit": 0, "credit": 0, "balance": 0, "reference": ""}
  ]
}""",
    }
    return type_prompts.get(document_type, base + """
Extract all visible financial data and return as JSON with relevant keys.
Always include: document_type, language, date, amounts, parties involved, reference numbers.
""")


# ─── Hybrid Pipeline ──────────────────────────────────────────────────────────

def process_document_hybrid(file_path: str, document_type: str, use_openai: bool = True) -> dict:
    """
    Full document processing pipeline:
    1. Tesseract OCR (fast, free)
    2. OpenAI Vision (structured extraction, only if use_openai=True)

    Returns combined result dict.
    """
    start_time = time.time()
    result = {
        "raw_text": "",
        "structured_data": {},
        "confidence": 0.0,
        "language": "unknown",
        "is_handwritten": False,
        "method": "tesseract",
        "page_results": [],
        "processing_ms": 0,
    }

    try:
        path_lower = file_path.lower()

        # Convert PDF to images if needed
        if path_lower.endswith(".pdf"):
            image_paths = pdf_to_images(file_path)
        else:
            image_paths = [file_path]

        all_text_parts = []
        total_confidence = 0.0

        for i, img_path in enumerate(image_paths):
            tess_result = extract_text_tesseract(img_path)
            page_text = tess_result.get("text", "")
            page_conf = tess_result.get("confidence", 0.0)

            all_text_parts.append(page_text)
            total_confidence += page_conf

            result["page_results"].append({
                "page": i + 1,
                "text": page_text,
                "confidence": page_conf,
                "image_path": img_path,
            })

        result["raw_text"] = "\n\n--- Page Break ---\n\n".join(all_text_parts)
        result["confidence"] = total_confidence / len(image_paths) if image_paths else 0.0

        # Detect language from text
        result["language"] = _detect_language(result["raw_text"])

        # OpenAI enhancement on first image
        if use_openai and settings.OPENAI_API_KEY and image_paths:
            ai_data = enhance_with_openai(image_paths[0], document_type, result["raw_text"])
            result["structured_data"] = ai_data
            result["method"] = "hybrid"
            if "is_handwritten" in ai_data:
                result["is_handwritten"] = ai_data["is_handwritten"]
        else:
            # Fallback: basic parsing from raw text
            result["structured_data"] = _basic_parse(result["raw_text"], document_type)

    except Exception as e:
        logger.error(f"Document processing error: {e}")
        result["error"] = str(e)

    result["processing_ms"] = int((time.time() - start_time) * 1000)
    return result


def _detect_language(text: str) -> str:
    """Simple heuristic language detection."""
    if not text:
        return "unknown"
    arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    latin_chars = sum(1 for c in text if c.isalpha() and c.isascii())
    total = arabic_chars + latin_chars
    if total == 0:
        return "unknown"
    ar_ratio = arabic_chars / total
    if ar_ratio > 0.7:
        return "ar"
    elif ar_ratio < 0.3:
        return "en"
    return "mixed"


def _basic_parse(text: str, document_type: str) -> dict:
    """Lightweight regex-based parsing fallback when OpenAI is unavailable."""
    import re
    result = {"document_type": document_type, "raw_extracted": True}

    # Amount patterns
    amounts = re.findall(r"(?:SAR|ريال|USD|\$|AED|€)?\s*[\d,]+\.?\d{0,2}", text)
    if amounts:
        result["detected_amounts"] = amounts[:10]

    # Date patterns
    dates = re.findall(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text)
    if dates:
        result["detected_dates"] = dates[:5]

    # Invoice/receipt number
    inv_match = re.search(r"(?:Invoice|فاتورة|INV|رقم)[^\d]*(\d+)", text, re.IGNORECASE)
    if inv_match:
        result["reference_number"] = inv_match.group(1)

    # TRN / VAT number (Saudi ZATCA format: 15 digits starting and ending with 3)
    # Pattern 1: strict format 3XXXXXXXXXXXXX3
    vat_match = re.search(r"\b3\d{13}3\b", text)
    if vat_match:
        result["vat_number"] = vat_match.group(0)
    else:
        # Pattern 2: labeled TRN — handles "TRN:", "VAT No:", "الرقم الضريبي:", etc.
        labeled = re.search(
            r"(?:TRN|VAT\s*(?:No|Number|Reg(?:istration)?)?|"
            r"Tax\s*Registration\s*(?:No|Number)?|"
            r"الرقم\s*الضريبي|رقم\s*التسجيل\s*الضريبي)"
            r"[:\s#\-]*([0-9]{10,15})",
            text, re.IGNORECASE
        )
        if labeled:
            candidate = labeled.group(1).strip()
            # Accept 10-digit (ZATCA simplified) or 15-digit
            if len(candidate) in (10, 15):
                result["vat_number"] = candidate
        else:
            # Pattern 3: any standalone 15-digit number (last resort)
            fallback = re.search(r"(?<![\d])([0-9]{15})(?![\d])", text)
            if fallback:
                result["vat_number"] = fallback.group(1)

    return result
