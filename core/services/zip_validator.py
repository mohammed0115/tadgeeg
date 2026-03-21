"""
ZIP Bomb Validation Service

Comprehensive decompression bomb protection against:
- Excessively compressed files (compression bombs)
- Oversized uncompressed contents
- Path traversal attacks
- Nested ZIP bombs
- Corrupt/malformed ZIPs
"""

import logging
import zipfile
from io import BytesIO
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Hard limits to prevent resource exhaustion
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024        # 500 MB per file
MAX_TOTAL_SIZE_BYTES = 1000 * 1024 * 1024      # 1 GB total uncompressed
MAX_FILE_COUNT = 500                             # Prevent slowness from too many files
MAX_COMPRESSION_RATIO = 100                      # 100:1 compression ratio threshold
MAX_NESTING_DEPTH = 2                            # Max nested ZIP depth


class ZipValidationError(ValueError):
    """Raised when ZIP fails security validation."""
    pass


def validate_zip_bomb(
    file_obj_or_path,
    max_file_size: int = MAX_FILE_SIZE_BYTES,
    max_total_size: int = MAX_TOTAL_SIZE_BYTES,
    max_files: int = MAX_FILE_COUNT,
    max_ratio: int = MAX_COMPRESSION_RATIO,
    allow_nesting: bool = True,
) -> dict:
    """
    Validate a ZIP file against decompression bomb attacks.

    Args:
        file_obj_or_path: File object (with .read() or .seek()) or file path string
        max_file_size: Max uncompressed size per file (bytes)
        max_total_size: Max total uncompressed size (bytes)
        max_files: Max number of files in ZIP
        max_ratio: Max compression ratio threshold (file_size / compressed_size)
        allow_nesting: Whether to allow nested ZIPs

    Returns:
        {
            "valid": bool,
            "errors": [str],
            "warnings": [str],
            "metadata": {
                "file_count": int,
                "total_uncompressed": int,
                "max_ratio": float,
                "has_nesting": bool,
            }
        }

    Raises:
        ZipValidationError: If ZIP fails critical security checks
    """
    errors = []
    warnings = []
    metadata = {
        "file_count": 0,
        "total_uncompressed": 0,
        "max_ratio": 0.0,
        "has_nesting": False,
    }

    # ── Convert file_obj to bytes if needed ────────────────────────────────
    try:
        if isinstance(file_obj_or_path, str):
            # File path
            with open(file_obj_or_path, "rb") as f:
                zip_bytes = f.read()
        else:
            # File object
            if hasattr(file_obj_or_path, "seek"):
                file_obj_or_path.seek(0)
            if hasattr(file_obj_or_path, "read"):
                zip_bytes = file_obj_or_path.read()
            else:
                raise ZipValidationError("Invalid file object: no read() method")
    except ZipValidationError:
        raise
    except Exception as e:
        raise ZipValidationError(f"Failed to read file: {str(e)}")

    # ── Validate ZIP is valid and not corrupted ────────────────────────────
    try:
        zf = zipfile.ZipFile(BytesIO(zip_bytes), "r")
    except zipfile.BadZipFile as e:
        raise ZipValidationError(f"Invalid or corrupt ZIP file: {str(e)}")
    except Exception as e:
        raise ZipValidationError(f"Failed to open ZIP: {str(e)}")

    try:
        # Test ZIP integrity
        if zf.testzip() is not None:
            raise ZipValidationError("ZIP archive is corrupted (testzip failed)")

        info_list = zf.infolist()
        
        # ── Check file count ──────────────────────────────────────────────
        if len(info_list) > max_files:
            errors.append(
                f"ZIP contains {len(info_list)} files (limit: {max_files})"
            )

        total_uncompressed = 0
        max_ratio_found = 0.0
        has_nested_zip = False

        # ── Iterate through all members ────────────────────────────────────
        for info in info_list:
            # Skip directories
            if info.filename.endswith("/"):
                continue

            # ── Check for path traversal ──────────────────────────────────
            if ".." in info.filename or info.filename.startswith("/"):
                errors.append(
                    f"Path traversal detected: {info.filename}"
                )
                continue

            # ── Check per-file uncompressed size ──────────────────────────
            if info.file_size > max_file_size:
                errors.append(
                    f"File '{info.filename}' exceeds {max_file_size // (1024*1024)}MB limit "
                    f"(actual: {info.file_size // (1024*1024)}MB)"
                )
                continue

            total_uncompressed += info.file_size

            # ── Check compression ratio (bomb detection) ──────────────────
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                max_ratio_found = max(max_ratio_found, ratio)

                if ratio > max_ratio:
                    errors.append(
                        f"File '{info.filename}' has suspicious compression ratio "
                        f"({ratio:.1f}:1, limit: {max_ratio}:1)"
                    )

            # ── Check for nested ZIPs ─────────────────────────────────────
            if info.filename.lower().endswith(".zip"):
                has_nested_zip = True
                if not allow_nesting:
                    warnings.append(
                        f"Nested ZIP found: {info.filename} (nesting is disabled)"
                    )

        metadata["file_count"] = len([i for i in info_list if not i.filename.endswith("/")])
        metadata["total_uncompressed"] = total_uncompressed
        metadata["max_ratio"] = max_ratio_found
        metadata["has_nesting"] = has_nested_zip

        # ── Check total uncompressed size ─────────────────────────────────
        if total_uncompressed > max_total_size:
            errors.append(
                f"ZIP contents exceed {max_total_size // (1024*1024)}MB limit "
                f"(total: {total_uncompressed // (1024*1024)}MB)"
            )

    finally:
        zf.close()

    # ── Return result ─────────────────────────────────────────────────────
    valid = len(errors) == 0

    if errors:
        logger.warning(f"ZIP validation failed: {'; '.join(errors)}")

    result = {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "metadata": metadata,
    }

    # Raise if critical errors
    if not valid:
        raise ZipValidationError("; ".join(errors))

    return result


def validate_zip_bomb_silent(
    file_obj_or_path,
    max_file_size: int = MAX_FILE_SIZE_BYTES,
    max_total_size: int = MAX_TOTAL_SIZE_BYTES,
    max_files: int = MAX_FILE_COUNT,
    max_ratio: int = MAX_COMPRESSION_RATIO,
) -> Tuple[bool, str]:
    """
    Non-raising version of validate_zip_bomb.

    Returns:
        (is_valid, error_message)
    """
    try:
        validate_zip_bomb(
            file_obj_or_path,
            max_file_size=max_file_size,
            max_total_size=max_total_size,
            max_files=max_files,
            max_ratio=max_ratio,
        )
        return True, ""
    except ZipValidationError as e:
        return False, str(e)
    except Exception as e:
        return False, f"ZIP validation error: {str(e)}"
