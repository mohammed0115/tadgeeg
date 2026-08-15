"""Runtime contract for image invoice extraction.

The test intentionally uses the installed Tesseract binary and a real PNG.
There is no skip path: a test environment that accepts image uploads must provide OCR.
"""
from __future__ import annotations

import shutil


def test_png_invoice_is_read_by_the_real_ocr_runtime(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    from core.services.document_engine import DocumentEngine
    from core.services.invoice_ai_service import _fallback_extraction

    assert shutil.which("tesseract"), "Tesseract is required for image invoice uploads"

    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
    image = Image.new("RGB", (1800, 1050), "white")
    draw = ImageDraw.Draw(image)
    lines = [
        "TAX INVOICE",
        "Invoice Number: INV-IMAGE-2026-001",
        "Vendor: Image OCR Supplier Ltd",
        "VAT Number: 310123456700003",
        "Invoice Date: 2026-08-15",
        "Currency: SAR",
        "Subtotal: 1000.00",
        "VAT Amount: 150.00",
        "Total Amount: 1150.00",
    ]
    for index, line in enumerate(lines):
        draw.text((80, 60 + index * 95), line, fill="black", font=font)

    path = tmp_path / "image-invoice.png"
    image.save(path)

    ingestion = DocumentEngine(use_ai=False).ingest(str(path))
    extracted = _fallback_extraction(ingestion.raw_text)

    assert ingestion.success is True
    assert ingestion.extraction_method == "ocr_fallback"
    assert extracted["invoice_number"] == "INV-IMAGE-2026-001"
    assert extracted["vendor_name"] == "Image OCR Supplier Ltd"
    assert extracted["subtotal"] == 1000.0
    assert extracted["vat_amount"] == 150.0
    assert extracted["total_amount"] == 1150.0
