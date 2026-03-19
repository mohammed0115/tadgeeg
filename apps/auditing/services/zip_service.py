"""ZIP Extraction Service — safely extract and process files from ZIP archives."""

import logging
import os
import tempfile
import zipfile

logger = logging.getLogger(__name__)


class ZipExtractionService:
    """Safely extract and process files from ZIP archives."""

    ALLOWED_INNER = {".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".xls", ".csv", ".json"}
    MAX_INNER_FILES = 20
    MAX_INNER_SIZE = 100 * 1024 * 1024  # 100 MB total

    def extract_and_parse(self, file_path: str) -> dict:
        """
        Extract ZIP and parse its contents.

        Returns:
            {
                "combined_text": str,
                "file_results": [{"name": str, "text": str, "error": str}],
                "failed_files": [str],
            }
        """
        result = {
            "combined_text": "",
            "file_results": [],
            "failed_files": [],
        }

        if not os.path.exists(file_path):
            result["failed_files"].append(file_path)
            return result

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                # Security: check for zip bombs and path traversal
                members = self._safe_members(zf)
                if not members:
                    logger.warning("ZIP has no valid/safe members: %s", file_path)
                    return result

                with tempfile.TemporaryDirectory() as tmpdir:
                    combined_parts = []
                    total_size = 0

                    for info in members[: self.MAX_INNER_FILES]:
                        ext = os.path.splitext(info.filename)[1].lower()
                        if ext not in self.ALLOWED_INNER:
                            continue

                        total_size += info.file_size
                        if total_size > self.MAX_INNER_SIZE:
                            logger.warning(
                                "ZIP extraction halted: total size exceeds %d MB",
                                self.MAX_INNER_SIZE // (1024 * 1024),
                            )
                            break

                        file_result = {"name": info.filename, "text": "", "error": ""}
                        try:
                            extracted_path = zf.extract(info, path=tmpdir)
                            text = self._parse_inner(extracted_path, ext)
                            file_result["text"] = text
                            if text.strip():
                                combined_parts.append(
                                    f"=== ملف: {info.filename} ===\n{text}"
                                )
                        except Exception as exc:
                            file_result["error"] = str(exc)
                            result["failed_files"].append(info.filename)
                            logger.warning(
                                "Failed to process ZIP member %s: %s", info.filename, exc
                            )

                        result["file_results"].append(file_result)

                    result["combined_text"] = "\n\n".join(combined_parts)

        except zipfile.BadZipFile as exc:
            logger.error("Bad ZIP file %s: %s", file_path, exc)
            result["failed_files"].append(file_path)
        except Exception as exc:
            logger.exception("ZIP extraction failed for %s: %s", file_path, exc)
            result["failed_files"].append(file_path)

        return result

    def _safe_members(self, zf: zipfile.ZipFile) -> list:
        """Return only members with safe paths (no path traversal)."""
        safe = []
        for info in zf.infolist():
            # Skip directories
            if info.filename.endswith("/"):
                continue
            # Skip path traversal attempts
            if ".." in info.filename or info.filename.startswith("/"):
                logger.warning("ZIP path traversal attempt blocked: %s", info.filename)
                continue
            safe.append(info)
        return safe

    def _parse_inner(self, file_path: str, ext: str) -> str:
        """Parse a single extracted file and return its text."""
        # Import here to avoid circular imports
        from apps.auditing.services.ocr_service import OCRService
        from apps.auditing.services.parser_service import ParserService

        ocr = OCRService()
        parser = ParserService()

        if ext == ".pdf":
            return ocr.extract_from_file(file_path, "auto")
        elif ext in {".jpg", ".jpeg", ".png"}:
            return ocr.extract_from_file(file_path, "auto")
        elif ext in {".xlsx", ".xls"}:
            return parser.parse_excel(file_path)
        elif ext == ".csv":
            return parser.parse_csv(file_path)
        elif ext == ".json":
            return parser.parse_json(file_path)
        return ""
