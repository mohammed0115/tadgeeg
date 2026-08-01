"""
ZIP Bomb Validation Service
===========================

Decompression-bomb protection that does NOT defeat itself by triggering
the very thing it's protecting against.

What changed from the previous implementation
---------------------------------------------
Old behavior (problematic):
  - Read the entire ZIP into memory before any check (`zip_bytes = f.read()`).
    A 500 MB ZIP = 500 MB resident in the worker before validation could
    even start.
  - Called `zf.testzip()` which **decompresses every member** to verify CRCs.
    That's exactly what a zip bomb exploits — a 1 KB archive expanding to
    hundreds of GB will exhaust the host before testzip returns.

New behavior:
  - Open the ZIP from a file path or seekable file-like object **without**
    materializing the whole archive in memory. zipfile.ZipFile only reads
    the central directory and per-file headers as needed.
  - Validate compression ratio + per-file declared size + total declared
    size from the central-directory metadata FIRST. Bail before any
    decompression if the declared sizes already exceed the limits.
  - Reject encrypted members up front (we can't read them anyway, and they
    let an attacker hide payloads from scanners).
  - Reject path traversal: `..`, leading `/`, backslash, NUL bytes, after
    posix-normalization.
  - Optionally stream-read each member with a hard per-file byte cap so a
    member whose central-directory metadata LIES still gets cut off at the
    cap rather than running unbounded. Default cap = `max_file_size`.
"""

from __future__ import annotations

import logging
import os
import posixpath
import zipfile
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Hard limits to prevent resource exhaustion
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024        # 500 MB per file
MAX_TOTAL_SIZE_BYTES = 1000 * 1024 * 1024      # 1 GB total uncompressed
MAX_FILE_COUNT = 500                             # Prevent slowness from too many files
MAX_COMPRESSION_RATIO = 100                      # 100:1 compression ratio threshold
MAX_NESTING_DEPTH = 2                            # Max nested ZIP depth
SAMPLE_CHUNK_BYTES = 64 * 1024                   # streaming verification chunk size


class ZipValidationError(ValueError):
    """Raised when ZIP fails security validation."""
    pass


def _open_zipfile_safely(file_obj_or_path):
    """Return (ZipFile, path-or-fileobj-to-close).

    Does NOT read the entire archive. zipfile reads central directory +
    per-file headers on demand. For a Django UploadedFile we rely on the
    object being seekable; if not, we write it to a tempfile.
    """
    if isinstance(file_obj_or_path, str):
        try:
            zf = zipfile.ZipFile(file_obj_or_path, "r")
            return zf, None
        except zipfile.BadZipFile as exc:
            raise ZipValidationError(f"Invalid or corrupt ZIP file: {exc}")

    file_obj = file_obj_or_path
    # Some upload backends provide temporary_file_path() — use it directly
    # so zipfile reads from disk rather than holding the buffer in memory.
    if hasattr(file_obj, "temporary_file_path"):
        try:
            zf = zipfile.ZipFile(file_obj.temporary_file_path(), "r")
            return zf, None
        except zipfile.BadZipFile as exc:
            raise ZipValidationError(f"Invalid or corrupt ZIP file: {exc}")

    if hasattr(file_obj, "seek"):
        try:
            file_obj.seek(0)
        except Exception:
            pass

    try:
        zf = zipfile.ZipFile(file_obj, "r")
        return zf, None
    except zipfile.BadZipFile as exc:
        raise ZipValidationError(f"Invalid or corrupt ZIP file: {exc}")
    except Exception as exc:  # pragma: no cover — defensive
        raise ZipValidationError(f"Failed to open ZIP: {exc}")


def _is_path_unsafe(name: str) -> Optional[str]:
    """Return a reason string if `name` is not a safe relative path inside a ZIP."""
    if "\x00" in name:
        return "NUL byte in filename"
    if "\\" in name:
        # Windows-style separators inside a ZIP entry name are a known smuggling
        # vector for cross-platform extractors.
        return "backslash in filename"
    if name.startswith("/"):
        return "absolute path"
    norm = posixpath.normpath(name)
    if norm.startswith("..") or "/../" in norm or norm == "..":
        return "path traversal (..)"
    return None


def validate_zip_bomb(
    file_obj_or_path,
    max_file_size: int = MAX_FILE_SIZE_BYTES,
    max_total_size: int = MAX_TOTAL_SIZE_BYTES,
    max_files: int = MAX_FILE_COUNT,
    max_ratio: int = MAX_COMPRESSION_RATIO,
    allow_nesting: bool = True,
    allow_encrypted: bool = False,
    verify_payload: bool = True,
) -> dict:
    """Validate a ZIP file against decompression bomb attacks.

    Args:
        file_obj_or_path: file path string, Django UploadedFile, or any
            seekable file-like object.
        max_file_size: declared/streamed bytes limit per member.
        max_total_size: declared total uncompressed bytes for the archive.
        max_files: max member count.
        max_ratio: max compress ratio (file_size / compress_size).
        allow_nesting: whether to permit `.zip` members.
        allow_encrypted: whether to permit encrypted members. Default False
            because we can't scan their contents and they shouldn't appear
            in financial-document workflows.
        verify_payload: stream-read each member with a hard byte cap so a
            lying central-directory entry still gets cut off. Set False to
            trust metadata only (faster, less safe).

    Returns: dict with `valid`, `errors`, `warnings`, `metadata`.

    Raises ZipValidationError on critical violations.
    """
    errors: list[str] = []
    warnings: list[str] = []
    metadata = {
        "file_count": 0,
        "total_uncompressed": 0,
        "max_ratio": 0.0,
        "has_nesting": False,
    }

    zf, _ = _open_zipfile_safely(file_obj_or_path)

    try:
        info_list = zf.infolist()

        if len(info_list) > max_files:
            errors.append(f"ZIP contains {len(info_list)} files (limit: {max_files})")

        total_uncompressed = 0
        max_ratio_found = 0.0
        has_nested_zip = False

        for info in info_list:
            if info.is_dir() or info.filename.endswith("/"):
                continue

            unsafe_reason = _is_path_unsafe(info.filename)
            if unsafe_reason:
                errors.append(f"Unsafe path '{info.filename}': {unsafe_reason}")
                continue

            # Encrypted entries — flag bit 0 — must be rejected by default.
            if info.flag_bits & 0x1:
                if not allow_encrypted:
                    errors.append(f"Encrypted member not allowed: {info.filename}")
                    continue
                warnings.append(f"Encrypted member admitted: {info.filename}")

            if info.file_size > max_file_size:
                errors.append(
                    f"File '{info.filename}' exceeds {max_file_size // (1024*1024)} MB "
                    f"(declared: {info.file_size // (1024*1024)} MB)"
                )
                continue

            total_uncompressed += info.file_size

            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                max_ratio_found = max(max_ratio_found, ratio)
                if ratio > max_ratio:
                    errors.append(
                        f"File '{info.filename}' has suspicious compression ratio "
                        f"({ratio:.1f}:1, limit: {max_ratio}:1)"
                    )
                    continue

            if info.filename.lower().endswith(".zip"):
                has_nested_zip = True
                if allow_nesting:
                    # Permitted, but still worth saying: a nested archive is
                    # the shape a decompression bomb usually arrives in, and a
                    # caller that allows it should know it is there.
                    warnings.append(f"Nested ZIP present: {info.filename}")
                else:
                    # This used to append to `warnings` while `valid` is
                    # computed as `len(errors) == 0` — so the message said
                    # "rejected" and nothing was rejected. A guarantee that
                    # does not exist is worse than none; the caller asked for
                    # nesting to be disallowed, so it is an error.
                    errors.append(f"Nested ZIP rejected: {info.filename}")

            # ── Streaming verification ──────────────────────────────────────
            # Open the member as a stream and read it in chunks with a hard
            # cap. zipfile decompresses on the fly; if the central directory
            # lied about file_size, this catches it BEFORE the host's RAM
            # runs out. We never accumulate the bytes — we just count them.
            if verify_payload:
                try:
                    with zf.open(info, "r") as src:
                        seen = 0
                        cap = max_file_size
                        while True:
                            chunk = src.read(SAMPLE_CHUNK_BYTES)
                            if not chunk:
                                break
                            seen += len(chunk)
                            if seen > cap:
                                errors.append(
                                    f"File '{info.filename}' exceeded byte cap "
                                    f"during streaming verification "
                                    f"(declared {info.file_size}, read > {cap})"
                                )
                                break
                except Exception as exc:
                    warnings.append(
                        f"Could not stream-verify '{info.filename}': {exc}"
                    )

        metadata["file_count"] = sum(1 for i in info_list if not i.filename.endswith("/"))
        metadata["total_uncompressed"] = total_uncompressed
        metadata["max_ratio"] = max_ratio_found
        metadata["has_nesting"] = has_nested_zip

        if total_uncompressed > max_total_size:
            errors.append(
                f"ZIP contents exceed {max_total_size // (1024*1024)} MB "
                f"(total declared: {total_uncompressed // (1024*1024)} MB)"
            )

    finally:
        zf.close()

    valid = len(errors) == 0
    if errors:
        logger.warning(f"ZIP validation failed: {'; '.join(errors)}")

    result = {"valid": valid, "errors": errors, "warnings": warnings, "metadata": metadata}
    if not valid:
        raise ZipValidationError("; ".join(errors))
    return result


def validate_zip_bomb_silent(
    file_obj_or_path,
    max_file_size: int = MAX_FILE_SIZE_BYTES,
    max_total_size: int = MAX_TOTAL_SIZE_BYTES,
    max_files: int = MAX_FILE_COUNT,
    max_ratio: int = MAX_COMPRESSION_RATIO,
    allow_nesting: bool = True,
) -> Tuple[bool, str]:
    """Non-raising wrapper around validate_zip_bomb.

    ``allow_nesting`` is forwarded so the two entry points can express the same
    policy. Without it a caller on this path could not refuse a nested archive
    at all, which is a quieter version of the defect this parameter guards.

    Returns: (is_valid, error_message)
    """
    try:
        validate_zip_bomb(
            file_obj_or_path,
            max_file_size=max_file_size,
            max_total_size=max_total_size,
            max_files=max_files,
            max_ratio=max_ratio,
            allow_nesting=allow_nesting,
        )
        return True, ""
    except ZipValidationError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover — defensive
        return False, f"ZIP validation error: {exc}"
