"""OCR Service — extract text from PDF/image using Tesseract."""

import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class OCRService:
    """Extract text from PDF/image using Tesseract. Replaceable with Google Vision."""

    def extract_from_file(self, file_path: str, language_hint: str = "auto") -> str:
        """Route to _from_pdf or _from_image based on extension."""
        if not file_path or not os.path.exists(file_path):
            logger.warning("OCRService: file not found: %s", file_path)
            return ""

        ext = os.path.splitext(file_path)[1].lstrip(".").lower()
        try:
            if ext == "pdf":
                return self._from_pdf(file_path, language_hint)
            else:
                return self._from_image(file_path, language_hint)
        except Exception as exc:
            logger.exception("OCR extraction failed for %s: %s", file_path, exc)
            return ""

    def _from_pdf(self, file_path: str, lang: str) -> str:
        """Convert PDF pages to images and OCR each page."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.error("PyMuPDF (fitz) is not installed. Cannot OCR PDF.")
            return ""

        tesseract_lang = self._tesseract_lang(lang)
        texts = []

        try:
            doc = fitz.open(file_path)
            with tempfile.TemporaryDirectory() as tmpdir:
                for page_num, page in enumerate(doc):
                    mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better OCR
                    pix = page.get_pixmap(matrix=mat)
                    img_path = os.path.join(tmpdir, f"page_{page_num}.png")
                    pix.save(img_path)
                    page_text = self._ocr_image_file(img_path, tesseract_lang)
                    if page_text.strip():
                        texts.append(f"--- صفحة {page_num + 1} ---\n{page_text}")

                # Also try direct text extraction (for searchable PDFs)
                for page_num, page in enumerate(doc):
                    direct_text = page.get_text("text").strip()
                    if direct_text and len(direct_text) > 50:
                        # Prefer direct text if sufficient
                        if page_num < len(texts):
                            texts[page_num] = f"--- صفحة {page_num + 1} ---\n{direct_text}"
                        else:
                            texts.append(f"--- صفحة {page_num + 1} ---\n{direct_text}")

            doc.close()
        except Exception as exc:
            logger.exception("PDF OCR failed for %s: %s", file_path, exc)
            return ""

        return "\n\n".join(texts)

    def _from_image(self, file_path: str, lang: str) -> str:
        """Run Tesseract on image."""
        tesseract_lang = self._tesseract_lang(lang)
        return self._ocr_image_file(file_path, tesseract_lang)

    def _ocr_image_file(self, img_path: str, tesseract_lang: str) -> str:
        """Run Tesseract OCR on a single image file."""
        try:
            import pytesseract
            from PIL import Image, ImageFilter, ImageEnhance

            img = Image.open(img_path)

            # Preprocessing for better accuracy
            img = img.convert("L")  # Grayscale
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            img = img.filter(ImageFilter.SHARPEN)

            config = "--oem 3 --psm 6"
            text = pytesseract.image_to_string(img, lang=tesseract_lang, config=config)
            return text.strip()
        except ImportError:
            logger.error("pytesseract or Pillow not installed.")
            return ""
        except Exception as exc:
            logger.exception("Tesseract OCR failed for %s: %s", img_path, exc)
            return ""

    def _tesseract_lang(self, hint: str) -> str:
        """Map language hint to Tesseract lang string."""
        mapping = {
            "ar": "ara",
            "en": "eng",
            "auto": "ara+eng",
            "ara": "ara",
            "eng": "eng",
            "ar-en": "ara+eng",
        }
        return mapping.get(hint.lower() if hint else "auto", "ara+eng")
