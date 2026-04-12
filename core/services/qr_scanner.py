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
from typing import Any, Optional

logger = logging.getLogger("finai.qr_scanner")

_PYZBAR_UNAVAILABLE_LOGGED = False


def _empty_result(error: Optional[str] = None) -> dict[str, Any]:
    """Create a normalized QR scan result payload."""
    return {
        "found": False,
        "raw_data": "",
        "tlv_data": {},
        "vat_number": "",
        "error": error,
    }


def _decode_zatca_tlv(raw_bytes: bytes) -> dict[str, str]:
    """
    Decode ZATCA TLV (Tag-Length-Value) binary into a structured dict.

    Tags: 1=seller_name, 2=vat_number, 3=invoice_date,
    4=total_with_vat, 5=vat_amount, 6=invoice_hash
    """
    tag_names = {
        1: "seller_name",
        2: "vat_number",
        3: "invoice_date",
        4: "total_with_vat",
        5: "vat_amount",
        6: "invoice_hash",
    }
    result: dict[str, str] = {}
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
        value = raw_bytes[i:i + length]
        i += length
        key = tag_names.get(tag, f"tag_{tag}")
        try:
            result[key] = value.decode("utf-8")
        except UnicodeDecodeError:
            result[key] = base64.b64encode(value).decode("ascii")
    return result


def _decode_raw_payload(raw: str) -> dict[str, Any]:
    """Decode a raw QR payload into TLV fields when it matches ZATCA format."""
    result = {
        "found": True,
        "raw_data": raw,
        "tlv_data": {},
        "vat_number": "",
        "error": None,
    }
    try:
        tlv_bytes = base64.b64decode(raw)
        tlv = _decode_zatca_tlv(tlv_bytes)
        result["tlv_data"] = tlv
        result["vat_number"] = tlv.get("vat_number", "")
    except Exception:
        result["tlv_data"] = {"raw_text": raw}
    return result


def _pyzbar_scan(img: Any) -> list[str]:
    """Run pyzbar QR decoder. Returns list of decoded string data."""
    global _PYZBAR_UNAVAILABLE_LOGGED
    try:
        from pyzbar.pyzbar import ZBarSymbol, decode as pyzbar_decode

        codes = pyzbar_decode(img, symbols=[ZBarSymbol.QRCODE])
        return [code.data.decode("utf-8", errors="replace") for code in codes if code.data]
    except ImportError:
        if not _PYZBAR_UNAVAILABLE_LOGGED:
            logger.warning("pyzbar not installed — QR scanning disabled. Run: pip install pyzbar")
            _PYZBAR_UNAVAILABLE_LOGGED = True
        return []
    except OSError as exc:
        if not _PYZBAR_UNAVAILABLE_LOGGED:
            logger.warning("pyzbar/zbar unavailable — QR scanning disabled: %s", exc)
            _PYZBAR_UNAVAILABLE_LOGGED = True
        return []
    except Exception as exc:
        logger.debug("pyzbar decode error: %s", exc)
        return []


def _scan_pil_image(img: Any) -> dict[str, Any]:
    """Internal: scan a PIL Image object directly (used by PDF scanner)."""
    decoded = _pyzbar_scan(img)

    if not decoded:
        try:
            from PIL import ImageEnhance, ImageFilter

            enhanced = ImageEnhance.Contrast(img).enhance(2.0)
            enhanced = enhanced.filter(ImageFilter.SHARPEN)
            decoded = _pyzbar_scan(enhanced)
        except Exception as exc:
            logger.debug("QR contrast scan failed: %s", exc)

    if not decoded:
        try:
            gray = img.convert("L")
            bw = gray.point(lambda value: 0 if value < 128 else 255, "1")
            decoded = _pyzbar_scan(bw.convert("L"))
        except Exception as exc:
            logger.debug("QR binarize scan failed: %s", exc)

    if not decoded:
        return _empty_result("No QR code detected")

    return _decode_raw_payload(decoded[0])


def scan_image_for_qr(image_path: str) -> dict[str, Any]:
    """
    Scan an image file for ZATCA QR codes using 3 strategies.

    Strategy 1: pyzbar on original image
    Strategy 2: PIL contrast enhancement + sharpen + pyzbar
    Strategy 3: Grayscale binarize + pyzbar

    Returns:
        {
            "found": bool,
            "raw_data": str,
            "tlv_data": dict,
            "vat_number": str,
            "error": str | None,
        }
    """
    if not image_path or not os.path.exists(image_path):
        return _empty_result("Image file not found")

    try:
        from PIL import Image

        with Image.open(image_path) as opened_img:
            if opened_img.mode not in ("RGB", "L", "1"):
                img = opened_img.convert("RGB")
            else:
                img = opened_img.copy()
    except Exception as exc:
        return _empty_result(f"Cannot open image: {exc}")

    return _scan_pil_image(img)


def scan_pdf_for_qr(pdf_path: str, max_pages: int = 5) -> dict[str, Any]:
    """
    Rasterize PDF pages at 2x zoom and scan each for QR codes.
    Stops at first QR code found.
    """
    result = _empty_result()

    try:
        import fitz  # PyMuPDF
    except ImportError:
        result["error"] = "PyMuPDF not installed. Run: pip install pymupdf"
        return result

    try:
        doc = fitz.open(pdf_path)
        scanned_pages = min(len(doc), max_pages)
        try:
            from PIL import Image

            for page_num in range(scanned_pages):
                page = doc[page_num]
                mat = fitz.Matrix(2, 2)
                pix = page.get_pixmap(matrix=mat, alpha=False)

                with Image.open(io.BytesIO(pix.tobytes("png"))) as opened_img:
                    if opened_img.mode not in ("RGB", "L", "1"):
                        img = opened_img.convert("RGB")
                    else:
                        img = opened_img.copy()

                page_result = _scan_pil_image(img)
                if page_result.get("found"):
                    return page_result
        finally:
            doc.close()

        result["error"] = f"No QR code found in first {scanned_pages} pages"
    except Exception as exc:
        logger.warning("PDF QR scan failed for %s: %s", pdf_path, exc)
        result["error"] = str(exc)

    return result


def enrich_invoice_qr(invoice_path: str) -> dict[str, Any]:
    """
    Unified entry point: detect file type, scan for QR, return enriched data.
    Call this during invoice ingestion pipeline.
    """
    if not invoice_path or not os.path.exists(invoice_path):
        return _empty_result("File not found")

    ext = os.path.splitext(invoice_path)[1].lower()
    if ext == ".pdf":
        return scan_pdf_for_qr(invoice_path)
    if ext in {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}:
        return scan_image_for_qr(invoice_path)
    return _empty_result(f"Unsupported format for QR scan: {ext}")
