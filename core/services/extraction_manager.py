"""Ordered extraction manager with explicit fallback strategies."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Iterable

from core.services.ai.openai_extractor import extract_with_text, extract_with_vision
from core.services.ocr_service import extract_text_openai, extract_text_tesseract, pdf_to_images
from core.services.parsers.base_parser import ParseResult
from core.services.parsers.csv_parser import CSVParser
from core.services.parsers.excel_parser import ExcelParser
from core.services.parsers.json_parser import JSONParser
from core.services.parsers.pdf_parser import PDFParser, TEXT_LAYER_MIN_CHARS

logger = logging.getLogger("finai")


def _cleanup_files(paths: Iterable[str]) -> None:
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            continue


class ExtractionStrategy(ABC):
    """Common interface for deterministic extraction strategies."""

    name = "base"

    @abstractmethod
    def supports(self, *, mime_type: str, file_path: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract(self, *, file_path: str, mime_type: str, use_ai: bool = True) -> ParseResult:
        raise NotImplementedError


class StructuredStrategy(ExtractionStrategy):
    name = "structured"
    _mime_parsers = {
        "application/json": JSONParser,
        "application/x-jsonlines": JSONParser,
        "text/csv": CSVParser,
        "text/tab-separated-values": CSVParser,
        "text/plain": CSVParser,
        "application/vnd.ms-excel": ExcelParser,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ExcelParser,
    }

    def supports(self, *, mime_type: str, file_path: str) -> bool:
        return mime_type in self._mime_parsers

    def extract(self, *, file_path: str, mime_type: str, use_ai: bool = True) -> ParseResult:
        parser_class = self._mime_parsers[mime_type]
        result = parser_class().parse(file_path, use_ai=use_ai)
        if result.success and not result.extraction_method:
            result.extraction_method = f"{self.name}_{mime_type}"
        return result


class TextLayerStrategy(ExtractionStrategy):
    name = "text_layer"

    def supports(self, *, mime_type: str, file_path: str) -> bool:
        return mime_type == "application/pdf"

    def extract(self, *, file_path: str, mime_type: str, use_ai: bool = True) -> ParseResult:
        parser = PDFParser()
        result = ParseResult(extraction_method="pdf_text_layer")
        page_texts = parser._extract_text_layer(file_path, result)
        total_chars = sum(len(text or "") for text in page_texts)
        min_chars = TEXT_LAYER_MIN_CHARS * max(len(page_texts), 1)

        if total_chars < min_chars:
            result.fatal_error = "PDF text layer is too sparse for structured extraction."
            return result

        result.page_texts = page_texts
        result.raw_text = "\n\n".join(text for text in page_texts if text).strip()
        result.metadata["page_count"] = len(page_texts)
        result.metadata["total_chars"] = total_chars
        result.metadata["source"] = "text_layer"

        if use_ai and result.raw_text:
            structured = extract_with_text(result.raw_text, document_type="invoice")
            if structured:
                result.structured = structured
                result.metadata["ai_enhanced"] = True

        result.success = bool(result.raw_text or result.structured)
        if not result.success:
            result.fatal_error = "Text layer extraction produced no usable content."
        return result


class VisionAIStrategy(ExtractionStrategy):
    name = "vision_ai"
    _supported = {"application/pdf", "image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp"}

    def supports(self, *, mime_type: str, file_path: str) -> bool:
        return mime_type in self._supported

    def extract(self, *, file_path: str, mime_type: str, use_ai: bool = True) -> ParseResult:
        result = ParseResult(extraction_method="openai_vision")
        if not use_ai:
            result.fatal_error = "Vision AI is disabled for this request."
            return result

        temp_images: list[str] = []
        candidate_images = [file_path]
        if mime_type == "application/pdf":
            temp_images = pdf_to_images(file_path)
            candidate_images = temp_images[:3] or [file_path]

        raw_text_parts: list[str] = []
        structured = {}
        confidence_values: list[float] = []
        languages: list[str] = []

        try:
            for image_path in candidate_images:
                ocr_result = extract_text_openai(image_path)
                if ocr_result.get("text"):
                    raw_text_parts.append(ocr_result["text"].strip())
                if ocr_result.get("confidence"):
                    confidence_values.append(float(ocr_result["confidence"]))
                if ocr_result.get("language"):
                    languages.append(ocr_result["language"])
                if not structured:
                    structured = extract_with_vision(image_path, document_type="invoice") or {}
        except Exception as exc:
            result.add_error(f"Vision AI extraction failed: {exc}")
        finally:
            _cleanup_files(path for path in temp_images if path != file_path)

        result.raw_text = "\n\n".join(part for part in raw_text_parts if part).strip()
        result.structured = structured
        if confidence_values:
            result.metadata["ocr_confidence"] = round(sum(confidence_values) / len(confidence_values), 2)
        if languages:
            result.metadata["language"] = next((value for value in languages if value not in {"unknown", ""}), languages[0])
        result.metadata["page_count"] = len(candidate_images)
        result.success = bool(result.raw_text or result.structured)
        if not result.success:
            result.fatal_error = "Vision AI produced no usable OCR or structured output."
        return result


class OCRFallbackStrategy(ExtractionStrategy):
    name = "ocr_fallback"
    _supported = {"application/pdf", "image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp"}

    def supports(self, *, mime_type: str, file_path: str) -> bool:
        return mime_type in self._supported

    def extract(self, *, file_path: str, mime_type: str, use_ai: bool = True) -> ParseResult:
        result = ParseResult(extraction_method="ocr_fallback")
        temp_images: list[str] = []
        candidate_images = [file_path]
        if mime_type == "application/pdf":
            temp_images = pdf_to_images(file_path)
            candidate_images = temp_images or [file_path]

        raw_text_parts: list[str] = []
        confidence_values: list[float] = []
        try:
            for image_path in candidate_images:
                ocr_result = extract_text_tesseract(image_path)
                if ocr_result.get("text"):
                    raw_text_parts.append(ocr_result["text"].strip())
                if ocr_result.get("confidence") is not None:
                    confidence_values.append(float(ocr_result.get("confidence") or 0.0))
        except Exception as exc:
            result.add_error(f"Tesseract fallback failed: {exc}")
        finally:
            _cleanup_files(path for path in temp_images if path != file_path)

        result.raw_text = "\n\n".join(part for part in raw_text_parts if part).strip()
        if confidence_values:
            result.metadata["ocr_confidence"] = round(sum(confidence_values) / len(confidence_values), 2)
        result.metadata["page_count"] = len(candidate_images)
        result.success = bool(result.raw_text)
        if not result.success:
            result.fatal_error = "OCR fallback produced no readable text."
        return result


class ExtractionManager:
    """Try ordered strategies and keep machine-readable trace for observability."""

    def __init__(self, strategies: list[ExtractionStrategy] | None = None):
        self.strategies = strategies or [
            StructuredStrategy(),
            TextLayerStrategy(),
            VisionAIStrategy(),
            OCRFallbackStrategy(),
        ]

    def extract(self, *, file_path: str, mime_type: str, use_ai: bool = True) -> ParseResult:
        attempted: list[dict] = []
        collected_errors: list[str] = []

        for strategy in self.strategies:
            if not strategy.supports(mime_type=mime_type, file_path=file_path):
                continue

            try:
                result = strategy.extract(file_path=file_path, mime_type=mime_type, use_ai=use_ai)
            except Exception as exc:
                logger.exception("[ExtractionManager] %s raised for %s", strategy.name, file_path)
                attempted.append(
                    {
                        "strategy": strategy.name,
                        "success": False,
                        "method": "exception",
                        "fatal_error": str(exc),
                        "errors": [str(exc)],
                    }
                )
                collected_errors.append(f"{strategy.name}: {exc}")
                continue

            trace_entry = {
                "strategy": strategy.name,
                "success": bool(result.success),
                "method": result.extraction_method,
                "fatal_error": result.fatal_error,
                "errors": list(result.errors),
            }
            attempted.append(trace_entry)
            collected_errors.extend(result.errors)

            if result.success:
                result.metadata.setdefault("attempted_strategies", [entry["strategy"] for entry in attempted])
                result.metadata["strategy_trace"] = attempted
                result.metadata["winning_strategy"] = strategy.name
                logger.info(
                    "[ExtractionManager] %s succeeded for %s via %s",
                    strategy.name,
                    os.path.basename(file_path),
                    result.extraction_method,
                )
                return result

            logger.warning(
                "[ExtractionManager] %s failed for %s: %s",
                strategy.name,
                os.path.basename(file_path),
                result.fatal_error or result.errors,
            )

        final_result = ParseResult(
            success=False,
            extraction_method="extraction_failed",
            errors=collected_errors,
            fatal_error="All configured extraction strategies failed.",
        )
        final_result.metadata["attempted_strategies"] = [entry["strategy"] for entry in attempted]
        final_result.metadata["strategy_trace"] = attempted
        return final_result
