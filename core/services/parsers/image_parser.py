"""
Image Parser — PNG / JPG / JPEG / TIFF / BMP / WEBP

Pipeline:
  1. Load image with Pillow
  2. Preprocess (grayscale → denoise → contrast → resize if too small)
  3. OCR via Tesseract (ara+eng)
  4. Optional AI enhancement via OpenAI Vision
  5. Return ParseResult with raw_text + structured fields
"""

import logging
import os
import tempfile
from pathlib import Path

from .base_parser import DocumentParser, ParseResult

logger = logging.getLogger("finai")

SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")
SUPPORTED_MIMES = (
    "image/png",
    "image/jpeg",
    "image/tiff",
    "image/bmp",
    "image/webp",
)

# Minimum dimension to apply upscaling before OCR
MIN_DIMENSION = 1200


class ImageParser(DocumentParser):
    """
    Parser for raster image documents.

    Preprocessing improves Tesseract accuracy on low-quality scans.
    OpenAI Vision is attempted as a higher-accuracy extraction layer.
    """

    supported_extensions = SUPPORTED_EXTENSIONS
    supported_mimes = SUPPORTED_MIMES

    def parse(self, file_path: str, use_ai: bool = True, **kwargs) -> ParseResult:
        result = ParseResult(extraction_method="image_ocr")

        # ── 1. Load ──────────────────────────────────────────────────────────
        try:
            from PIL import Image

            image = Image.open(file_path)
            image.verify()          # Detect corrupt headers early
            image = Image.open(file_path)  # Re-open after verify()
            image = image.convert("RGB")
        except Exception as exc:
            result.fatal_error = f"Cannot open image: {exc}"
            logger.error("[ImageParser] %s — %s", file_path, exc)
            return result

        # ── 2. Preprocess ────────────────────────────────────────────────────
        preprocessed_path = self._preprocess(image, file_path)

        # ── 3. OCR (Tesseract primary → OpenAI upgrade if low confidence) ───────
        try:
            from core.services.ocr_service import extract_text_openai, extract_text_tesseract

            ocr_result = extract_text_tesseract(preprocessed_path or file_path)
            raw_text = ocr_result.get("text", "").strip()
            confidence = ocr_result.get("confidence", 0.0)

            # Upgrade to OpenAI OCR when Tesseract confidence is low or empty
            if confidence < 60 or not raw_text:
                logger.info("[ImageParser] Tesseract confidence %.0f%% — upgrading to OpenAI OCR", confidence)
                ai_ocr = extract_text_openai(file_path)
                if ai_ocr.get("text"):
                    raw_text = ai_ocr["text"]
                    confidence = ai_ocr.get("confidence", confidence)
                    result.metadata["source"] = "openai_ocr"
                    result.metadata["is_handwritten"] = ai_ocr.get("is_handwritten", False)
            else:
                result.metadata["source"] = "tesseract"

            result.raw_text = raw_text
            result.metadata["ocr_confidence"] = confidence
        except Exception as exc:
            result.add_error(f"OCR failed: {exc}")

        # ── 4. AI Vision enhancement ─────────────────────────────────────────
        if use_ai:
            try:
                from core.services.ai.openai_extractor import extract_with_vision

                ai_structured = extract_with_vision(file_path)
                if ai_structured:
                    result.structured = ai_structured
                    result.extraction_method = "image_ai_vision"
                    result.metadata["ai_enhanced"] = True
            except Exception as exc:
                result.add_error(f"OpenAI Vision failed: {exc}")

        # ── 5. Finalize ──────────────────────────────────────────────────────
        result.success = bool(result.raw_text or result.structured)
        if not result.success:
            result.fatal_error = "No text or structured data could be extracted."

        # Cleanup temp file
        if preprocessed_path and preprocessed_path != file_path:
            try:
                os.unlink(preprocessed_path)
            except OSError:
                pass

        return result

    # ── Private helpers ──────────────────────────────────────────────────────

    def _preprocess(self, image, original_path: str) -> str:
        """
        Apply image preprocessing to improve OCR accuracy.

        Steps:
          - Convert to grayscale
          - Upscale if smaller than MIN_DIMENSION
          - Sharpen / increase contrast
          - Save to a temporary PNG for Tesseract

        Returns:
          Path to the preprocessed temp file, or original_path on failure.
        """
        try:
            from PIL import Image, ImageEnhance, ImageFilter

            # Grayscale
            gray = image.convert("L")

            # Upscale if too small
            w, h = gray.size
            if min(w, h) < MIN_DIMENSION:
                scale = MIN_DIMENSION / min(w, h)
                new_w, new_h = int(w * scale), int(h * scale)
                gray = gray.resize((new_w, new_h), Image.LANCZOS)

            # Sharpen
            gray = gray.filter(ImageFilter.SHARPEN)

            # Contrast boost
            enhancer = ImageEnhance.Contrast(gray)
            gray = enhancer.enhance(1.5)

            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", delete=False, prefix="finai_img_"
            )
            gray.save(tmp.name, format="PNG", dpi=(300, 300))
            tmp.close()
            return tmp.name

        except Exception as exc:
            logger.warning("[ImageParser] Preprocessing failed: %s", exc)
            return original_path
