"""
File Validation Service — Phase 0

Two-stage validation:
  Stage 1: MIME/content-based type validation
           python-magic (libmagic) → mimetypes stdlib fallback
  Stage 2: ZIP-specific security checks
           - Zip-slip (path traversal)
           - Compression bomb (ratio ≥ MAX_ZIP_RATIO)
           - File count limit
           - Nested archive restriction

Usage:
    from core.services.file_validator import FileValidator, FileValidationError

    try:
        meta = FileValidator.validate(uploaded_file)
    except FileValidationError as exc:
        return Response({"error": str(exc)}, status=400)

The returned meta dict contains:
    {
        "detected_mime": "application/pdf",
        "extension":     ".pdf",
        "file_size":     102400,
    }
"""

from __future__ import annotations

import logging
import mimetypes
import os
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from typing import Optional

from django.conf import settings

logger = logging.getLogger("finai")

# ── Constants ─────────────────────────────────────────────────────────────────

# Maximum uncompressed-to-compressed ratio — above this we treat as a zip bomb
MAX_ZIP_RATIO = int(getattr(settings, "ZIP_MAX_COMPRESSION_RATIO", 100))

# Hard cap on the number of files allowed inside a single archive
MAX_ZIP_FILES = int(getattr(settings, "ZIP_MAX_FILE_COUNT", 500))

# Maximum nesting depth for archives (we refuse to extract archives-within-archives)
MAX_ZIP_NESTING = int(getattr(settings, "ZIP_MAX_NESTING_DEPTH", 1))

# Content-type → allowed MIME set mapping.
# Each extension maps to the set of MIME types we consider valid for it.
EXTENSION_MIME_MAP: dict[str, set[str]] = {
    ".pdf":   {"application/pdf"},
    ".png":   {"image/png"},
    ".jpg":   {"image/jpeg"},
    ".jpeg":  {"image/jpeg"},
    ".tiff":  {"image/tiff"},
    ".tif":   {"image/tiff"},
    ".bmp":   {"image/bmp", "image/x-bmp"},
    ".webp":  {"image/webp"},
    ".zip":   {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
    ".xlsx":  {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",       # xlsx is a zip internally
        "application/octet-stream",
    },
    ".xls":   {
        "application/vnd.ms-excel",
        "application/octet-stream",
    },
    ".xlsm":  {
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/octet-stream",
    },
    ".csv":   {"text/csv", "text/plain", "application/csv", "application/octet-stream"},
    ".tsv":   {"text/tab-separated-values", "text/plain", "application/octet-stream"},
    ".json":  {"application/json", "text/json", "text/plain"},
    ".jsonl": {"application/json", "text/json", "text/plain", "application/octet-stream"},
}

# MIME types that represent archive files we refuse to extract recursively
ARCHIVE_MIMES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/gzip",
    "application/x-tar",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
}


# ── Exception ─────────────────────────────────────────────────────────────────

class FileValidationError(ValueError):
    """Raised when an uploaded file fails MIME or security checks."""


# ── Service ───────────────────────────────────────────────────────────────────

class FileValidator:
    """
    Validates uploaded files before they enter the processing pipeline.

    All methods are classmethods — no instance state.
    """

    # ── Public entry point ────────────────────────────────────────────────────

    @classmethod
    def validate(cls, uploaded_file, *, extension: Optional[str] = None) -> dict:
        """
        Full validation pass: MIME check + ZIP security (if applicable).

        Args:
            uploaded_file: Django UploadedFile / InMemoryUploadedFile.
            extension:     Explicit extension override (e.g. ".pdf").
                           Derived from uploaded_file.name if not provided.

        Returns:
            dict with detected_mime, extension, file_size.

        Raises:
            FileValidationError on any validation failure.
        """
        ext = (extension or cls._extension(uploaded_file.name)).lower()
        file_size = uploaded_file.size or 0

        # ── 1. Allowed extension ──────────────────────────────────────────────
        allowed_exts = getattr(settings, "ALLOWED_UPLOAD_EXTENSIONS", list(EXTENSION_MIME_MAP.keys()))
        if ext not in allowed_exts:
            raise FileValidationError(
                f"File type '{ext}' is not permitted. "
                f"Allowed: {', '.join(sorted(allowed_exts))}"
            )

        # ── 2. File size ──────────────────────────────────────────────────────
        if ext == ".zip":
            max_size = getattr(settings, "MAX_ZIP_UPLOAD_SIZE", 200 * 1024 * 1024)
        else:
            max_size = getattr(settings, "MAX_UPLOAD_SIZE", 50 * 1024 * 1024)

        if file_size > max_size:
            raise FileValidationError(
                f"File too large: {file_size // (1024*1024)} MB "
                f"(max {max_size // (1024*1024)} MB for {ext})"
            )

        # ── 3. MIME detection ─────────────────────────────────────────────────
        header = cls._read_header(uploaded_file)
        detected_mime = cls._detect_mime(header, uploaded_file.name)

        allowed_mimes = EXTENSION_MIME_MAP.get(ext)
        if allowed_mimes and detected_mime not in allowed_mimes:
            # Be lenient with octet-stream — some clients send it for everything
            if detected_mime != "application/octet-stream":
                raise FileValidationError(
                    f"MIME mismatch: file with extension '{ext}' reported as "
                    f"'{detected_mime}'. Expected one of: {', '.join(sorted(allowed_mimes))}"
                )

        # ── 4. ZIP security checks ────────────────────────────────────────────
        if ext == ".zip" or detected_mime in {"application/zip", "application/x-zip-compressed"}:
            cls._validate_zip(uploaded_file)

        return {
            "detected_mime": detected_mime,
            "extension":     ext,
            "file_size":     file_size,
        }

    # ── ZIP security ──────────────────────────────────────────────────────────

    @classmethod
    def _validate_zip(cls, uploaded_file) -> None:
        """
        Run all ZIP-specific security checks.

        Checks:
          Z1 — Integrity (valid ZIP structure)
          Z2 — Path traversal / zip-slip
          Z3 — File count limit
          Z4 — Nested archive restriction
          Z5 — Compression bomb (uncompressed/compressed ratio)

        Raises FileValidationError on any violation.
        """
        raw = cls._read_all(uploaded_file)

        # Z1 — valid archive?
        try:
            zf = zipfile.ZipFile(BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise FileValidationError(f"Invalid ZIP file: {exc}") from exc

        members = zf.infolist()

        # Z3 — file count
        if len(members) > MAX_ZIP_FILES:
            raise FileValidationError(
                f"ZIP contains {len(members)} files; maximum allowed is {MAX_ZIP_FILES}."
            )

        total_compressed   = 0
        total_uncompressed = 0

        for info in members:
            name = info.filename

            # Z2 — path traversal (zip-slip)
            # Normalise the path and ensure it doesn't escape the root
            try:
                safe = PurePosixPath(name)
            except Exception:
                raise FileValidationError(f"Invalid filename in archive: {name!r}")

            # Any absolute path or ".." component is forbidden
            if safe.is_absolute() or ".." in safe.parts:
                raise FileValidationError(
                    f"ZIP path traversal detected: entry '{name}' would escape the "
                    "extraction directory."
                )

            # Also reject Windows-style traversal
            if "\\" in name or name.startswith("/"):
                raise FileValidationError(
                    f"Unsafe path in ZIP entry: '{name}'"
                )

            # Z4 — nested archives
            entry_ext = PurePosixPath(name).suffix.lower()
            if entry_ext in {".zip", ".gz", ".tar", ".rar", ".7z", ".bz2"}:
                raise FileValidationError(
                    f"Nested archives are not permitted: '{name}' is an archive "
                    f"inside the uploaded ZIP."
                )

            # Accumulate sizes for Z5 check
            total_compressed   += info.compress_size
            total_uncompressed += info.file_size

        # Z5 — compression bomb
        if total_compressed > 0:
            ratio = total_uncompressed / total_compressed
            if ratio > MAX_ZIP_RATIO:
                raise FileValidationError(
                    f"Potential ZIP bomb: compression ratio {ratio:.0f}x exceeds "
                    f"the maximum allowed {MAX_ZIP_RATIO}x."
                )

        logger.debug(
            "[FileValidator] ZIP OK: %d files, uncompressed=%dKB ratio=%.1fx",
            len(members),
            total_uncompressed // 1024,
            (total_uncompressed / total_compressed) if total_compressed else 0,
        )

    # ── MIME detection ────────────────────────────────────────────────────────

    @staticmethod
    def _detect_mime(header: bytes, filename: str) -> str:
        """
        Detect MIME type from file bytes (content-first, not extension-first).

        Priority:
          1. python-magic (libmagic) — byte-level identification
          2. stdlib mimetypes        — extension-based fallback
          3. "application/octet-stream" — last resort
        """
        # Attempt python-magic
        try:
            import magic as _magic
            mime = _magic.from_buffer(header, mime=True)
            if mime:
                return mime
        except ImportError:
            logger.debug("[FileValidator] python-magic not available; using mimetypes fallback")
        except Exception as exc:
            logger.debug("[FileValidator] magic detection failed: %s", exc)

        # Stdlib fallback
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or "application/octet-stream"

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extension(filename: str) -> str:
        """Extract and return the lowercased file extension including the dot."""
        _, ext = os.path.splitext(filename or "")
        return ext.lower() if ext else ""

    @staticmethod
    def _read_header(uploaded_file, n: int = 8192) -> bytes:
        """Read the first n bytes without consuming the entire stream."""
        uploaded_file.seek(0)
        header = uploaded_file.read(n)
        uploaded_file.seek(0)
        return header

    @staticmethod
    def _read_all(uploaded_file) -> bytes:
        """Read the entire file into memory and reset the cursor."""
        uploaded_file.seek(0)
        data = uploaded_file.read()
        uploaded_file.seek(0)
        return data
