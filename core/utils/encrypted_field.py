"""
EncryptedCharField — transparent at-rest encryption for sensitive short strings.

Use case: MFA TOTP secrets, API tokens, anything that:
  • is short (≤ few hundred chars after encryption),
  • must round-trip as plain text in Python (e.g. pyotp.TOTP() needs the
    base32-encoded secret, not ciphertext),
  • should NEVER appear in plaintext at rest because a DB-read attack
    (SQL injection, leaked backup, compromised replica) would otherwise
    hand the attacker every user's second factor.

Backward-compat: a field that has held plaintext in the past will
auto-decrypt encrypted rows AND pass through legacy plaintext rows
unchanged on read. The next save re-stores the value encrypted. This
removes the need for a one-shot data backfill — every write becomes
the migration.

Key management:
  • Production: settings.MFA_FERNET_KEY must be set, base64-urlsafe-encoded
    32 random bytes. Generate with
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  • Dev (DEBUG=True): falls back to a key derived from SECRET_KEY so
    local tests don't need extra config. NEVER in production — the
    field constructor raises if DEBUG=False and the key isn't set.

The Fernet key MUST be different from SECRET_KEY and from
ZATCA_FERNET_KEY. Sharing keys means one leak compromises every
domain.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from django.conf import settings
from django.db import models

logger = logging.getLogger("finai.encrypted_field")

# Fernet tokens always start with these bytes (URL-safe base64 of version + ts).
# Used as a heuristic to distinguish encrypted ciphertext from legacy
# plaintext when reading rows that pre-date encryption.
_FERNET_PREFIX = "gAAAAA"


def _get_fernet():
    """Return a Fernet instance for the configured MFA_FERNET_KEY."""
    from cryptography.fernet import Fernet

    key = getattr(settings, "MFA_FERNET_KEY", "") or ""
    if not key:
        is_dev_or_test = (
            getattr(settings, "DEBUG", False)
            or getattr(settings, "TESTING", False)
        )
        if not is_dev_or_test:
            raise RuntimeError(
                "MFA_FERNET_KEY must be configured in production. Generate "
                "via `python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"` and set in env."
            )
        # Dev / test fallback only.
        digest = hashlib.sha256(
            (settings.SECRET_KEY + ":mfa").encode("utf-8")
        ).digest()
        key = base64.urlsafe_b64encode(digest)
    elif isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def _encrypt(value: str) -> str:
    if value == "":
        return ""
    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_if_needed(value: str) -> str:
    """Return the plaintext value. Transparently decrypts ciphertext."""
    if not value:
        return value
    # Heuristic: Fernet tokens are base64 starting with "gAAAAA". Legacy
    # plaintext TOTP secrets are base32 (A-Z, 2-7 only) so they cannot
    # start with lowercase letters — safe to gate on the prefix.
    if not value.startswith(_FERNET_PREFIX):
        return value  # legacy plaintext — pass through
    try:
        return _get_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except Exception as exc:
        logger.error("EncryptedCharField decrypt failed: %s", exc)
        # Decryption failure usually means a key rotation without a re-encrypt
        # migration. Return the raw ciphertext so the caller fails LOUDLY
        # (e.g., MFA verify says "invalid code") rather than silently using
        # garbage.
        return value


class EncryptedCharField(models.CharField):
    """A CharField that stores its value encrypted with Fernet at rest.

    Reads return decoded plaintext. Writes encrypt automatically. Existing
    legacy plaintext rows are passed through unchanged on read (their next
    save promotes them to encrypted form).
    """

    description = "CharField with transparent Fernet encryption at rest"

    def from_db_value(self, value: Optional[str], expression, connection) -> Optional[str]:
        if value is None:
            return value
        return _decrypt_if_needed(value)

    def to_python(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        # `to_python` runs on form-cleaned data + deserialized fixtures + the
        # value the user just assigned to the instance. We always return
        # plaintext here so downstream code can use the secret directly.
        return _decrypt_if_needed(value)

    def get_prep_value(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        # Idempotent: if the caller assigns an already-encrypted value (e.g.
        # via a raw queryset .update()), don't double-encrypt.
        if isinstance(value, str) and value.startswith(_FERNET_PREFIX):
            return value
        return _encrypt(str(value))
