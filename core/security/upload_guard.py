"""Upload guard — file-extension allow-list enforcement (F-4).

Defence-in-depth on top of MIME-type + size validation. A determined
attacker uploads `evil.html` or `tax-statement.svg` (with embedded JS)
and relies on the OCR/storage pipeline to mishandle it. The whitelist
here is the early-rejection guarantee.

Pattern: every file-upload entry point either calls
``assert_extension_allowed(filename, kind=...)`` directly, or passes
the uploaded file through ``UploadedFileValidator.validate()``.
"""
from __future__ import annotations

import os
from typing import Iterable

from django.conf import settings
from django.utils.translation import gettext as _


# Tight, domain-driven allow-lists. Anything that's not raw evidence
# or a tabular/structured payload is rejected.
_INVOICE_EXTENSIONS = frozenset({
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".webp",
    ".xlsx", ".xls", ".csv", ".json", ".jsonl", ".zip",
})

_BANK_STATEMENT_EXTENSIONS = frozenset({
    ".pdf", ".csv", ".xlsx", ".xls", ".ofx", ".qfx", ".qif", ".mt940",
})

_GENERIC_DOCUMENT_EXTENSIONS = frozenset({
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".webp",
    ".docx", ".doc", ".odt", ".rtf",
    ".xlsx", ".xls", ".csv", ".ods",
    ".pptx", ".ppt",
    ".txt", ".json", ".jsonl", ".xml",
})

_AVATAR_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})


_BUCKETS = {
    "invoice":        _INVOICE_EXTENSIONS,
    "bank_statement": _BANK_STATEMENT_EXTENSIONS,
    "document":       _GENERIC_DOCUMENT_EXTENSIONS,
    "avatar":         _AVATAR_EXTENSIONS,
}


class DisallowedExtensionError(ValueError):
    """Raised when an uploaded filename has an extension outside the
    allow-list for its upload bucket."""

    def __init__(self, filename: str, ext: str, allowed: Iterable[str], kind: str):
        self.filename = filename
        self.extension = ext
        self.kind = kind
        self.allowed = sorted(allowed)
        super().__init__(self.user_message)

    @property
    def user_message(self) -> str:
        return str(_(
            "Uploaded file %(filename)s has an unsupported extension %(ext)s "
            "for %(kind)s uploads. Allowed: %(allowed)s."
        )) % {
            "filename": self.filename,
            "ext":      self.extension or "(none)",
            "kind":     self.kind,
            "allowed":  ", ".join(self.allowed),
        }


def _resolve_allowed(kind: str) -> frozenset:
    """Settings override > built-in bucket."""
    override_name = f"ALLOWED_UPLOAD_EXT_{kind.upper()}"
    if hasattr(settings, override_name):
        return frozenset(s.lower() for s in getattr(settings, override_name))
    return _BUCKETS.get(kind, _GENERIC_DOCUMENT_EXTENSIONS)


def assert_extension_allowed(filename: str, *, kind: str = "document") -> str:
    """Raise ``DisallowedExtensionError`` if ``filename`` doesn't end in
    an allowed extension for ``kind``. Returns the normalised extension
    on success."""
    ext = os.path.splitext(filename or "")[1].lower()
    allowed = _resolve_allowed(kind)
    if ext not in allowed:
        raise DisallowedExtensionError(filename, ext, allowed, kind)
    return ext


def is_extension_allowed(filename: str, *, kind: str = "document") -> bool:
    try:
        assert_extension_allowed(filename, kind=kind)
        return True
    except DisallowedExtensionError:
        return False
