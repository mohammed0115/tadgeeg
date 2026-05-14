"""EncryptedJSONField — at-rest encryption for JSON columns.

Used for ``BankConnection.credentials`` and any other JSON blob that
contains secrets (API keys, OAuth tokens, mTLS PEM bodies).

Storage shape:
    On disk:   {"_enc": "gAAAAA...<fernet ciphertext of the JSON dump>"}
    In Python: the original dict / list / scalar

The on-disk shape is itself a JSON dict, so a DB inspector sees a real
JSONField row (queryable via the standard ``json`` extension) — but the
useful keys live inside the encrypted blob.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.db import models

from core.utils.encrypted_field import _decrypt_if_needed, _encrypt, _FERNET_PREFIX

logger = logging.getLogger("finai.encrypted_json")


class EncryptedJSONField(models.JSONField):
    """JSON field whose serialized form is Fernet-encrypted at rest."""

    description = "JSONField with transparent Fernet encryption at rest"

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        # JSONField may already have parsed it to a dict on some backends.
        parsed = value if not isinstance(value, str) else self._loads(value)
        return self._maybe_decrypt(parsed)

    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, str):
            try:
                value = self._loads(value)
            except Exception:
                return value
        return self._maybe_decrypt(value)

    def get_prep_value(self, value):
        """Return the encryption-wrapper DICT; the parent JSONField then
        serializes it via ``adapt_json_value``."""
        if value is None:
            return value
        # Already in the encrypted envelope — pass through unchanged.
        if isinstance(value, dict) and isinstance(value.get("_enc"), str) \
                and value["_enc"].startswith(_FERNET_PREFIX):
            return value
        body = self._dumps(value)
        return {"_enc": _encrypt(body)}

    # ── helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _dumps(obj: Any) -> str:
        return json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str)

    @staticmethod
    def _loads(s: str):
        return json.loads(s)

    def _maybe_decrypt(self, parsed):
        if not isinstance(parsed, dict):
            return parsed     # legacy plaintext list / scalar
        ct = parsed.get("_enc")
        if not (isinstance(ct, str) and ct.startswith(_FERNET_PREFIX)):
            return parsed     # legacy plaintext dict
        try:
            return self._loads(_decrypt_if_needed(ct))
        except Exception as exc:
            logger.error("EncryptedJSONField decrypt failed: %s", exc)
            return parsed
