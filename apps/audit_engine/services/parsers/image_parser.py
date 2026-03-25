from apps.audit_engine.services.parsers.base import BaseParser, ParseResult


class ImageParser(BaseParser):
    """
    OCR-based parser for image files.
    Requires pytesseract and Pillow. Falls back gracefully if not installed.
    """

    @property
    def supported_extensions(self):
        return [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(file_path)
            # Convert to RGB if needed (handles RGBA, palette-mode images)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            text = pytesseract.image_to_string(img)
            width, height = img.size

            return ParseResult(
                text=text.strip(),
                page_count=1,
                metadata={
                    "ocr_available": True,
                    "width": width,
                    "height": height,
                    "mode": img.mode,
                    "format": img.format or "unknown",
                },
                success=True,
            )
        except ImportError:
            return ParseResult(
                text="[Image OCR not available — install pytesseract and Pillow]",
                page_count=1,
                metadata={"ocr_available": False},
                success=True,  # Soft failure — file was received but OCR is unavailable
            )
        except Exception as exc:
            return ParseResult(success=False, error=str(exc))
