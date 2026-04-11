"""
QR Code Scanner — ZATCA Phase 2 Compliance
==========================================
Scans images and PDFs for QR codes and decodes their TLV content.
Uses pyzbar (primary) with PIL preprocessing fallback for low-quality images.
"""
from __future__ import annotations

import base64
import io
import logging
import os
from typing import Optional

logger = logging.getLogger("finai.qr_scanner")


def _decode_zatca_tlv(raw_bytes: bytes) -> dict:
    """Decode ZATCA TLV binary into a structured dict."""
    result = {}
    TAG_NAMES = {
        1: "seller_name",
        2: "vat_number",
        3: "invoice_date",
        4: "total_with_vat",
        5: "vat_amount",
        6: "invoice_hash",
    }
    i = 0
    while i < len(raw_bytes) - 1:
        tag = raw_bytes[i]
        i += 1
        length = raw_bytes[i]
        i += 1
        if length == 0x81 and i < len(raw_bytes):
            length = raw_bytes[i]
            i += 1
        if i + length > len(raw_bytes):
            break
        value = raw_bytes[i: i + length]
        i += length
        key = TAG_NAMES.get(tag, f"tag_{tag}")
        try:
            result[key] = value.decode("utf-8")
        except UnicodeDecodeError:
            result[key] = base64.b64encode(value).decode("ascii")
    return result


def scan_image_for_qr(image_path: str) -> dict:
    """
    Scan an image file for QR codes. Returns decoded ZATCA TLV data.

    Strategy:
      1. pyzbar on original image
      2. PIL contrast enhancement + pyzbar retry
      3. cv2 adaptive threshold + pyzbar (if cv2 available)

    Returns:
        {
            "found": bool,
            "raw_data": str,          # raw QR string
            "tlv_data": dict,         # decoded ZATCA TLV fields
            "vat_number": str,        # extracted TRN if present
            "error": str | None,
        }
    """
    result = {"found": False, "raw_data": "", "tlv_data": {}, "vat_number": "", "error": None}

    if not image_path or not os.path.exists(image_path):
        result["error"] = "Image file not found"
        return result

    try:
        from PIL import Image
        img = Image.open(image_path)
        # Convert to RGB if needed (handles RGBA, palette modes)
        if img.mode not in ("RGB", "L", "1"):
            img = img.convert("RGB")
    except Exception as exc:
        result["error"] = f"Cannot open image: {exc}"
        return result

    # ── Strategy 1: pyzbar on original ───────────────────────────────────────
    decoded = _pyzbar_scan(img)

    # ── Strategy 2: contrast-enhanced retry ──────────────────────────────────
    if not decoded:
        try:
            from PIL import ImageEnhance, ImageFilter
            enhanced = ImageEnhance.Contrast(img).enhance(2.0)
            enhanced = enhanced.filter(ImageFilter.SHARPEN)
            decoded = _pyzbar_scan(enhanced)
        except Exception as exc:
            logger.debug("QR contrast enhancement failed: %s", exc)

    # ── Strategy 3: grayscale + binarize ─────────────────────────────────────
    if not decoded:
        try:
            gray = img.convert("L")
            bw = gray.point(lambda x: 0 if x < 128 else 255, "1")
            decoded = _pyzbar_scan(bw.convert("L"))
        except Exception as exc:
            logger.debug("QR binarize scan failed: %s", exc)

    if not decoded:
        result["error"] = "No QR code detected in image"
        return result

    raw = decoded[0]
    result["found"] = True
    result["raw_data"] = raw

    # Try to decode as ZATCA TLV (base64-encoded binary)
    try:
        tlv_bytes = base64.b64decode(raw)
        tlv = _decode_zatca_tlv(tlv_bytes)
        result["tlv_data"] = tlv
        result["vat_number"] = tlv.get("vat_number", "")
    except Exception:
        # Not a ZATCA TLV QR — treat as plain text
        result["tlv_data"] = {"raw_text": raw}

    return result


def _pyzbar_scan(img) -> list:
    """Run pyzbar decode, return list of decoded QR data strings."""
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        from pyzbar.pyzbar import ZBarSymbol
        codes = pyzbar_decode(img, symbols=[ZBarSymbol.QRCODE])
        return [c.data.decode("utf-8", errors="replace") for c in codes if c.data]
    except ImportError:
        logger.info("pyzbar not installed — QR scanning requires: pip install pyzbar")
        return []
    except Exception as exc:
        logger.debug("pyzbar decode error: %s", exc)
        return []


def scan_pdf_for_qr(pdf_path: str, max_pages: int = 5) -> dict:
    """
    Rasterize PDF pages and scan each for QR codes.
    Stops at first QR code found.

    Returns same structure as scan_image_for_qr.
    """
    result = {"found": False, "raw_data": "", "tlv_data": {}, "vat_number": "", "error": None}

    try:
        import fitz  # PyMuPDF
    except ImportError:
        result["error"] = "PyMuPDF (fitz) not installed — cannot scan PDF for QR"
        return result

    try:
        doc = fitz.open(pdf_path)
        for page_num in range(min(len(doc), max_pages)):
            page = doc[page_num]
            # Render at 2x zoom for better QR resolution
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes("png")

            from PIL import Image
            img = Image.open(io.BytesIO(img_bytes))
            codes = _pyzbar_scan(img)
            if codes:
                raw = codes[0]
                result["found"] = True
                result["raw_data"] = raw
                try:
                    tlv_bytes = base64.b64decode(raw)
                    tlv = _decode_zatca_tlv(tlv_bytes)
                    result["tlv_data"] = tlv
                    result["vat_number"] = tlv.get("vat_number", "")
                except Exception:
                    result["tlv_data"] = {"raw_text": raw}
                return result
        result["error"] = f"No QR code found in first {min(len(doc), max_pages)} pages"
    except Exception as exc:
        logger.warning("PDF QR scan failed for %s: %s", pdf_path, exc)
        result["error"] = str(exc)

    return result


def enrich_invoice_qr(invoice_path: str) -> dict:
    """
    Unified entry point: detect file type, scan for QR, return enriched data.
    Suitable for calling during invoice ingestion pipeline.
    """
    if not invoice_path or not os.path.exists(invoice_path):
        return {"found": False, "error": "File not found"}

    ext = os.path.splitext(invoice_path)[1].lower()
    if ext == ".pdf":
        return scan_pdf_for_qr(invoice_path)
    elif ext in {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}:
        return scan_image_for_qr(invoice_path)
    else:
        return {"found": False, "error": f"Unsupported format for QR scan: {ext}"}
