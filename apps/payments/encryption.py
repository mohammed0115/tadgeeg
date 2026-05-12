"""Symmetric encryption for sensitive credentials at rest.

Fernet (AES-128-CBC + HMAC-SHA256) — secret_key columns are stored as
URL-safe base64 ciphertext. The encryption key is read from
``FIELD_ENCRYPTION_KEY`` (a Fernet key) and rejected at boot if missing
in production. In DEBUG, a key is derived from SECRET_KEY so local devs
don't have to provision a separate value.

Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _get_fernet() -> Fernet:
    raw = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
    if raw:
        key = raw.encode("utf-8") if isinstance(raw, str) else raw
        try:
            return Fernet(key)
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured(
                "FIELD_ENCRYPTION_KEY is not a valid Fernet key. "
                "Generate one with: python -c "
                "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            ) from exc
    # Derived fallback for DEBUG/test only — NEVER acceptable in prod.
    if not settings.DEBUG and not getattr(settings, "TESTING", False):
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY must be set in production deployments."
        )
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class EncryptedTextField(models.TextField):
    """TextField transparently encrypted on save / decrypted on load.

    Stored ciphertext is base64-URL-safe-ASCII, so the column is plain
    TEXT and indexable only as opaque ciphertext (do not try to filter
    on encrypted values).
    """

    description = "Symmetrically encrypted text"

    def from_db_value(self, value, expression, connection):
        return self._decrypt(value)

    def to_python(self, value):
        if value is None or value == "":
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        # Already plaintext (never round-tripped through DB)?
        if not _looks_like_token(value):
            return value
        return self._decrypt(value)

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        # Idempotent: if already a token, store as-is.
        if _looks_like_token(value):
            return value
        token = _get_fernet().encrypt(value.encode("utf-8"))
        return token.decode("utf-8")

    @staticmethod
    def _decrypt(value):
        if value in (None, ""):
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if not _looks_like_token(value):
            # Legacy plaintext rows that pre-date the migration; surface
            # them as-is so a backfill management command can re-encrypt.
            return value
        try:
            return _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            # Wrong key, corruption, or somebody hand-edited the row.
            # Returning the opaque token is safer than crashing the page.
            return ""


def _looks_like_token(value: str) -> bool:
    """Fernet tokens start with ``gAAAA`` (version byte 0x80 + timestamp)."""
    return isinstance(value, str) and value.startswith("gAAAA")
