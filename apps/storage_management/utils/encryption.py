"""
Encryption utilities for secure storage of credentials.
Uses Fernet symmetric encryption with a key derived from Django's SECRET_KEY.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _get_fernet() -> Fernet:
    """Derive a Fernet key from Django's SECRET_KEY using SHA-256."""
    raw = settings.SECRET_KEY
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_value(value: str) -> str:
    """
    Encrypt a plain-text string and return a base64-encoded ciphertext string.
    Returns empty string for empty/None input.
    """
    if not value:
        return ""
    fernet = _get_fernet()
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(value: str) -> str:
    """
    Decrypt a Fernet-encrypted string and return the plain-text value.
    Returns empty string for empty/None input.
    Raises ValueError if decryption fails (wrong key or tampered data).
    """
    if not value:
        return ""
    fernet = _get_fernet()
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        raise ValueError(f"Failed to decrypt value: {exc}") from exc


def mask_value(value: str) -> str:
    """
    Return a masked representation of a secret value.
    Shows only the last 4 characters, replaces the rest with '***...***'.
    Returns empty string for short/empty values.
    """
    if not value or len(value) < 5:
        return "***"
    return f"***...***{value[-4:]}"
