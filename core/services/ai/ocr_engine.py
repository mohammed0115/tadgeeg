"""
Unified OCR Engine

Wraps the existing core/services/ocr_service.py with:
  - A class-based interface (OCREngine)
  - Language auto-detection before OCR
  - Preprocessing pipeline control
  - Page-level confidence tracking
  - Clean fallback to raw Tesseract if preprocessing fails

This module does NOT replace ocr_service.py — it composes it.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("finai")


class OCREngine:
    """
    Unified OCR interface used by parsers.

    Attributes:
        languages: Tesseract language string (e.g. 'ara+eng').
        preprocess: Whether to apply image preprocessing before OCR.
        use_ai_enhancement: Whether to attempt OpenAI Vision after OCR.
    """

    def __init__(
        self,
        languages: str = None,
        preprocess: bool = True,
        use_ai_enhancement: bool = False,
    ):
        from django.conf import settings

        self.languages = languages or getattr(settings, "TESSERACT_LANGUAGES", "ara+eng")
        self.preprocess = preprocess
        self.use_ai_enhancement = use_ai_enhancement

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_from_image(self, image_path: str) -> dict:
        """
        Run OCR on a single image file.

        Returns:
            {
              text: str,
              confidence: float,
              word_data: list,
              language_detected: str,
              method: str
            }
        """
        processed_path = image_path
        cleanup = False

        if self.preprocess:
            processed_path, cleanup = self._preprocess_image(image_path)

        try:
            result = self._tesseract_ocr(processed_path)
        except Exception as exc:
            logger.error("[OCREngine] Tesseract failed on %s: %s", image_path, exc)
            result = {"text": "", "confidence": 0.0, "word_data": []}
        finally:
            if cleanup and processed_path != image_path:
                try:
                    os.unlink(processed_path)
                except OSError:
                    pass

        # Detect language from output text
        result["language_detected"] = self._detect_language(result.get("text", ""))
        result["method"] = "tesseract"

        # Optional AI enhancement
        if self.use_ai_enhancement and result.get("text"):
            result = self._ai_enhance(image_path, result)

        return result

    def extract_from_pdf(self, pdf_path: str) -> list[dict]:
        """
        Convert PDF pages to images and OCR each page.

        Returns:
            List of per-page result dicts (same schema as extract_from_image).
        """
        page_results: list[dict] = []
        image_paths: list[str] = []

        try:
            from core.services.ocr_service import pdf_to_images
            image_paths = pdf_to_images(pdf_path)
        except Exception as exc:
            logger.error("[OCREngine] PDF→image conversion failed: %s", exc)
            return page_results

        for page_num, img_path in enumerate(image_paths, start=1):
            try:
                page_result = self.extract_from_image(img_path)
                page_result["page_number"] = page_num
                page_results.append(page_result)
            except Exception as exc:
                logger.error("[OCREngine] OCR failed on page %d: %s", page_num, exc)
                page_results.append({
                    "page_number": page_num,
                    "text": "",
                    "confidence": 0.0,
                    "word_data": [],
                    "language_detected": "unknown",
                    "method": "tesseract_failed",
                })
            finally:
                try:
                    os.unlink(img_path)
                except OSError:
                    pass

        return page_results

    def combined_text(self, page_results: list[dict]) -> str:
        """Concatenate page texts with page separators."""
        return "\n\n".join(
            f"[Page {r.get('page_number', i + 1)}]\n{r.get('text', '')}"
            for i, r in enumerate(page_results)
        )

    def average_confidence(self, page_results: list[dict]) -> float:
        """Compute average OCR confidence across pages."""
        if not page_results:
            return 0.0
        confidences = [r.get("confidence", 0.0) for r in page_results]
        return round(sum(confidences) / len(confidences), 2)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _tesseract_ocr(self, image_path: str) -> dict:
        from core.services.ocr_service import extract_text_tesseract
        return extract_text_tesseract(image_path, languages=self.languages)

    def _preprocess_image(self, image_path: str) -> tuple[str, bool]:
        """
        Preprocess image for better OCR accuracy.

        Returns (processed_path, should_cleanup).
        """
        try:
            from PIL import Image, ImageEnhance, ImageFilter

            img = Image.open(image_path).convert("L")  # Grayscale

            # Upscale if small
            w, h = img.size
            if min(w, h) < 1200:
                scale = 1200 / min(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

            img = img.filter(ImageFilter.SHARPEN)
            img = ImageEnhance.Contrast(img).enhance(1.4)

            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="finai_ocr_")
            img.save(tmp.name, format="PNG", dpi=(300, 300))
            tmp.close()
            return tmp.name, True

        except Exception as exc:
            logger.warning("[OCREngine] Preprocessing failed: %s", exc)
            return image_path, False

    def _detect_language(self, text: str) -> str:
        if not text:
            return "unknown"
        arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
        ratio = arabic_chars / max(len(text), 1)
        if ratio > 0.5:
            return "ar"
        elif ratio > 0.1:
            return "mixed"
        return "en"

    def _ai_enhance(self, image_path: str, ocr_result: dict) -> dict:
        """Attempt OpenAI Vision enhancement on top of Tesseract output."""
        try:
            from core.services.ai.openai_extractor import extract_with_vision
            ai_data = extract_with_vision(image_path)
            if ai_data:
                ocr_result["ai_structured"] = ai_data
                ocr_result["method"] = "tesseract+openai"
        except Exception as exc:
            logger.warning("[OCREngine] AI enhancement failed: %s", exc)
        return ocr_result
