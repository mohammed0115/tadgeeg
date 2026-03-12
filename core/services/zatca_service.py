"""
ZATCA QR Code Service
======================
Implements ZATCA Phase 2 TLV (Tag-Length-Value) encoding/decoding
for Saudi Arabia e-invoicing compliance.

TLV Tags:
  1 = Seller Name
  2 = Seller VAT Number (15 digits)
  3 = Invoice Timestamp (ISO 8601)
  4 = Invoice Total (with VAT)
  5 = VAT Amount
  6 = Hash (SHA-256 of canonical invoice XML)
  7 = ECDSA Signature (optional for simplified)
  8 = ECDSA Public Key (optional)
  9 = Stamp (optional)
"""

import base64
import hashlib
import struct
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

logger = logging.getLogger("finai")


# ── TLV Encoder ───────────────────────────────────────────────────────────────

def _tlv_encode(tag: int, value: bytes) -> bytes:
    """Encode a single TLV field."""
    length = len(value)
    if length <= 0xFF:
        return bytes([tag, length]) + value
    else:
        # Extended length
        return bytes([tag, 0x81, length]) + value


def _tlv_decode(data: bytes) -> dict:
    """Decode TLV-encoded bytes into a dict of tag → value."""
    result = {}
    i = 0
    while i < len(data):
        if i + 2 > len(data):
            break
        tag = data[i]
        i += 1
        length = data[i]
        i += 1
        if length == 0x81:
            if i >= len(data):
                break
            length = data[i]
            i += 1
        if i + length > len(data):
            break
        result[tag] = data[i:i + length]
        i += length
    return result


# ── QR Code Generation ────────────────────────────────────────────────────────

def generate_zatca_qr(
    seller_name: str,
    vat_number: str,
    invoice_date: str,          # ISO 8601 e.g. "2024-01-15T14:30:00Z"
    total_with_vat: Decimal,
    vat_amount: Decimal,
) -> str:
    """
    Generate a ZATCA-compliant QR code string (base64-encoded TLV).

    Returns:
        Base64 string suitable for embedding in QR code image.
    """
    try:
        tlv = b""
        tlv += _tlv_encode(1, seller_name.encode("utf-8"))
        tlv += _tlv_encode(2, vat_number.encode("utf-8"))
        tlv += _tlv_encode(3, invoice_date.encode("utf-8"))
        tlv += _tlv_encode(4, str(total_with_vat.quantize(Decimal("0.01"))).encode("utf-8"))
        tlv += _tlv_encode(5, str(vat_amount.quantize(Decimal("0.01"))).encode("utf-8"))

        # Tag 6: hash of the TLV data so far (simplified implementation)
        hash_val = hashlib.sha256(tlv).digest()
        tlv += _tlv_encode(6, base64.b64encode(hash_val))

        return base64.b64encode(tlv).decode("utf-8")

    except Exception as e:
        logger.error(f"ZATCA QR generation failed: {e}")
        return ""


# ── QR Code Validation ────────────────────────────────────────────────────────

def validate_zatca_qr(
    qr_string: str,
    expected_vat_number: str = "",
    expected_total: Optional[Decimal] = None,
    expected_vat: Optional[Decimal] = None,
) -> dict:
    """
    Decode and validate a ZATCA QR string.

    Returns:
        {
            "valid": bool,
            "seller_name": str,
            "vat_number": str,
            "invoice_date": str,
            "total_with_vat": str,
            "vat_amount": str,
            "errors": list[str],
            "warnings": list[str],
        }
    """
    result = {
        "valid": False,
        "seller_name": "",
        "vat_number": "",
        "invoice_date": "",
        "total_with_vat": "",
        "vat_amount": "",
        "errors": [],
        "warnings": [],
    }

    if not qr_string:
        result["errors"].append("QR code is empty")
        return result

    # ── Decode base64 ──
    try:
        raw = base64.b64decode(qr_string)
    except Exception:
        result["errors"].append("QR code is not valid base64")
        return result

    # ── Decode TLV ──
    try:
        fields = _tlv_decode(raw)
    except Exception as e:
        result["errors"].append(f"TLV decode error: {e}")
        return result

    if not fields:
        result["errors"].append("QR code contains no readable fields")
        return result

    # ── Extract fields ──
    def _get(tag, default=""):
        val = fields.get(tag, b"")
        try:
            return val.decode("utf-8")
        except Exception:
            return default

    result["seller_name"]    = _get(1)
    result["vat_number"]     = _get(2)
    result["invoice_date"]   = _get(3)
    result["total_with_vat"] = _get(4)
    result["vat_amount"]     = _get(5)

    # ── Validations ──

    # 1. Required fields
    for tag, name in [(1,"اسم البائع"),(2,"الرقم الضريبي"),(3,"التاريخ"),(4,"الإجمالي"),(5,"الضريبة")]:
        if not fields.get(tag):
            result["errors"].append(f"حقل {name} مفقود في QR (Tag {tag})")

    # 2. VAT number format (15 digits, starts and ends with 3)
    vat = result["vat_number"]
    if vat:
        if len(vat) != 15:
            result["errors"].append(f"الرقم الضريبي في QR يجب أن يكون 15 رقم، الموجود: {len(vat)}")
        elif not (vat.startswith("3") and vat.endswith("3")):
            result["warnings"].append("الرقم الضريبي لا يبدأ وينتهي بـ 3")
        if expected_vat_number and vat != expected_vat_number:
            result["errors"].append(f"الرقم الضريبي في QR ({vat}) لا يتطابق مع الفاتورة ({expected_vat_number})")

    # 3. Date format
    date_str = result["invoice_date"]
    if date_str:
        try:
            datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            result["errors"].append(f"تنسيق التاريخ في QR غير صحيح: {date_str}")

    # 4. Amount consistency
    if expected_total and result["total_with_vat"]:
        try:
            qr_total = Decimal(result["total_with_vat"])
            if abs(qr_total - expected_total) > Decimal("1.00"):
                result["errors"].append(
                    f"الإجمالي في QR ({qr_total}) لا يتطابق مع الفاتورة ({expected_total})"
                )
        except Exception:
            result["warnings"].append("تعذر مقارنة مبالغ QR مع الفاتورة")

    if expected_vat and result["vat_amount"]:
        try:
            qr_vat = Decimal(result["vat_amount"])
            if abs(qr_vat - expected_vat) > Decimal("1.00"):
                result["errors"].append(
                    f"الضريبة في QR ({qr_vat}) لا تتطابق مع الفاتورة ({expected_vat})"
                )
        except Exception:
            pass

    # 5. Hash integrity (Tag 6)
    if 6 in fields:
        try:
            # Rebuild TLV without tag 6
            tlv_no_hash = b""
            for t in [1, 2, 3, 4, 5]:
                if t in fields:
                    tlv_no_hash += _tlv_encode(t, fields[t])
            expected_hash = base64.b64encode(hashlib.sha256(tlv_no_hash).digest())
            if fields[6] != expected_hash:
                result["warnings"].append("Hash integrity check failed — QR may have been tampered")
        except Exception:
            pass

    result["valid"] = len(result["errors"]) == 0
    return result


# ── Generate QR Image ─────────────────────────────────────────────────────────

def generate_qr_image_base64(qr_string: str) -> str:
    """
    Convert ZATCA QR string to a PNG image (base64).
    Requires: pip install qrcode pillow

    Returns:
        Base64-encoded PNG or empty string on failure.
    """
    try:
        import qrcode
        import io
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(qr_string)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except ImportError:
        logger.warning("qrcode library not installed. Run: pip install qrcode pillow")
        return ""
    except Exception as e:
        logger.error(f"QR image generation failed: {e}")
        return ""


# ── Convenience: validate invoice object ─────────────────────────────────────

def validate_invoice_qr(invoice) -> dict:
    """Validate QR code on an Invoice model instance."""
    from decimal import Decimal
    qr = invoice.extracted_data.get("qr_code_raw", "") or ""
    if not qr and hasattr(invoice, "qr_code_data"):
        qr = invoice.qr_code_data if isinstance(invoice.qr_code_data, str) else ""

    date_str = ""
    if invoice.invoice_date:
        date_str = invoice.invoice_date.isoformat() + "T00:00:00Z"

    return validate_zatca_qr(
        qr_string=qr,
        expected_vat_number=invoice.vendor_vat_number or "",
        expected_total=invoice.total_amount,
        expected_vat=invoice.vat_amount,
    )
