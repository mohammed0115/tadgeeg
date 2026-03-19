"""
OCR & AI Service Exception Classes
=================================
Structured error handling with classification for retry logic.
"""


class BaseFiNAIException(Exception):
    """Base exception for all Tadgeeg AI services."""

    def __init__(self, message: str, code: str = "unknown_error", details: dict = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


# ─── OCR & Document Processing Errors ─────────────────────────────────────────


class OCRException(BaseFiNAIException):
    """Base exception for OCR operations"""

    pass


class TemporaryOCRError(OCRException):
    """Errors that might resolve on retry (network, timeout, resource issues)"""

    pass


class PermanentOCRError(OCRException):
    """Errors that won't resolve by retrying (format, validation, configuration)"""

    pass


class TesseractException(OCRException):
    """Tesseract-specific errors"""

    pass


class TesseractNotFoundError(PermanentOCRError):
    """Tesseract executable not found or not configured"""

    def __init__(self):
        super().__init__(
            "Tesseract OCR not installed. Install with: apt-get install tesseract-ocr",
            code="tesseract_not_found",
        )


class ImageProcessingError(PermanentOCRError):
    """Image preprocessing or conversion failure"""

    def __init__(self, message: str, source_format: str = None):
        super().__init__(
            message,
            code="image_processing_error",
            details={"source_format": source_format},
        )


class PDFConversionError(PermanentOCRError):
    """PDF to image conversion failed"""

    def __init__(self, reason: str = "Unknown"):
        super().__init__(
            f"PDF conversion failed: {reason}",
            code="pdf_conversion_error",
            details={"reason": reason},
        )


class FileFormatNotSupportedError(PermanentOCRError):
    """Uploaded file format is not supported"""

    def __init__(self, file_extension: str, supported: list):
        super().__init__(
            f"File format {file_extension} not supported. Supported: {', '.join(supported)}",
            code="file_format_not_supported",
            details={"file_extension": file_extension, "supported_formats": supported},
        )


class FileSizeExceededError(PermanentOCRError):
    """Uploaded file exceeds size limit"""

    def __init__(self, file_size_mb: float, limit_mb: float):
        super().__init__(
            f"File size {file_size_mb:.1f}MB exceeds limit {limit_mb:.1f}MB",
            code="file_size_exceeded",
            details={"file_size_mb": file_size_mb, "limit_mb": limit_mb},
        )


# ─── GPT/AI API Errors ──────────────────────────────────────────────────────────


class AIException(BaseFiNAIException):
    """Base exception for AI/LLM operations"""

    pass


class TemporaryAIError(AIException):
    """Temporary AI/API errors (rate limit, timeout, unavailable)"""

    pass


class PermanentAIError(AIException):
    """Permanent AI/API errors (invalid key, bad request format)"""

    pass


class GPTAPIError(TemporaryAIError):
    """Generic GPT API error"""

    pass


class GPTTimeoutError(TemporaryAIError):
    """GPT API request timed out"""

    def __init__(self, timeout_seconds: int = 30):
        super().__init__(
            f"GPT API request timed out after {timeout_seconds}s",
            code="gpt_timeout",
            details={"timeout_seconds": timeout_seconds},
        )


class GPTRateLimitError(TemporaryAIError):
    """GPT API rate limit exceeded"""

    def __init__(self, retry_after: int = None):
        super().__init__(
            f"GPT API rate limit exceeded",
            code="gpt_rate_limit",
            details={"retry_after_seconds": retry_after},
        )


class GPTAuthenticationError(PermanentAIError):
    """GPT API authentication failed (invalid key)"""

    def __init__(self):
        super().__init__(
            "GPT API authentication failed. Check OPENAI_API_KEY.",
            code="gpt_auth_error",
        )


class GPTInvalidResponseError(TemporaryAIError):
    """GPT returned invalid/unparseable response"""

    def __init__(self, reason: str = "Invalid JSON"):
        super().__init__(
            f"GPT API invalid response: {reason}",
            code="gpt_invalid_response",
            details={"reason": reason},
        )


class AIServiceUnavailableError(TemporaryAIError):
    """AI service temporarily unavailable"""

    def __init__(self, service_name: str = "OpenAI"):
        super().__init__(
            f"{service_name} service temporarily unavailable",
            code="ai_service_unavailable",
            details={"service": service_name},
        )


# ─── Data Validation Errors ────────────────────────────────────────────────────


class ValidationException(BaseFiNAIException):
    """Base exception for validation errors"""

    pass


class DataValidationError(ValidationException):
    """Extracted data failed validation"""

    def __init__(self, message: str, failed_fields: list = None):
        super().__init__(
            message,
            code="data_validation_error",
            details={"failed_fields": failed_fields or []},
        )


class InvoiceValidationError(ValidationException):
    """Invoice data validation failed"""

    def __init__(self, message: str, violations: list = None):
        super().__init__(
            message,
            code="invoice_validation_error",
            details={"violations": violations or []},
        )


# ─── Document Processing Errors ────────────────────────────────────────────────


class DocumentProcessingException(BaseFiNAIException):
    """Base exception for document processing pipeline"""

    pass


class AllOCRMethodsFailedError(DocumentProcessingException):
    """All OCR methods (GPT-4o, Tesseract) failed"""

    def __init__(self, gpt_error: str = None, tesseract_error: str = None):
        super().__init__(
            "All OCR methods failed. No extraction possible.",
            code="all_ocr_methods_failed",
            details={
                "gpt_error": gpt_error,
                "tesseract_error": tesseract_error,
            },
        )


class DocumentProcessingTimeoutError(TemporaryOCRError):
    """Document processing exceeded timeout"""

    def __init__(self, timeout_seconds: int, stage: str = "processing"):
        super().__init__(
            f"Document {stage} exceeded {timeout_seconds}s timeout",
            code="document_processing_timeout",
            details={"timeout_seconds": timeout_seconds, "stage": stage},
        )


# ─── Celery Task Errors ────────────────────────────────────────────────────────


class TaskExecutionError(BaseFiNAIException):
    """Celery task execution error"""

    pass


class TaskRetryableError(BaseFiNAIException):
    """Error indicating task should be retried"""

    def __init__(self, message: str, retry_delay_seconds: int = 60):
        super().__init__(
            message,
            code="task_retryable",
            details={"retry_delay_seconds": retry_delay_seconds},
        )


class TaskMaxRetriesExceededError(TaskExecutionError):
    """Task exceeded max retries"""

    def __init__(self, task_name: str, max_retries: int):
        super().__init__(
            f"Task {task_name} exceeded max retries ({max_retries})",
            code="task_max_retries_exceeded",
            details={"task_name": task_name, "max_retries": max_retries},
        )


# ─── External Service Errors ───────────────────────────────────────────────────


class ExternalServiceError(BaseFiNAIException):
    """Error communicating with external service"""

    pass


class RedisConnectionError(TemporaryAIError):
    """Redis/Celery broker connection failed"""

    def __init__(self, reason: str = "Connection refused"):
        super().__init__(
            f"Redis connection failed: {reason}",
            code="redis_connection_error",
            details={"reason": reason},
        )


# ─── Utility Functions ──────────────────────────────────────────────────────────


def is_retriable_error(exc: Exception) -> bool:
    """Check if an exception should trigger task retry"""
    return isinstance(
        exc,
        (
            TemporaryOCRError,
            TemporaryAIError,
            RedisConnectionError,
            DocumentProcessingTimeoutError,
            GPTTimeoutError,
            GPTRateLimitError,
        ),
    )


def classify_error(exc: Exception) -> str:
    """Classify error as 'temporary', 'permanent', or 'unknown'"""
    if isinstance(exc, TemporaryOCRError) or isinstance(exc, TemporaryAIError):
        return "temporary"
    elif isinstance(exc, PermanentOCRError) or isinstance(exc, PermanentAIError):
        return "permanent"
    else:
        return "unknown"


def error_to_dict(exc: Exception) -> dict:
    """Convert exception to serializable dict"""
    if isinstance(exc, BaseFiNAIException):
        return {
            "error_type": exc.__class__.__name__,
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        }
    else:
        return {
            "error_type": exc.__class__.__name__,
            "code": "unknown_error",
            "message": str(exc),
            "details": {},
        }
