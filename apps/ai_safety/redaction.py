"""PII redaction for AI logs and persisted evidence.

The platform deals with Saudi financial documents — national ID numbers,
Iqama numbers, IBANs, and credit-card numbers routinely appear in
invoices. We MUST mask them anywhere they'd be logged, stored as
provider response, or echoed to a downstream system.

The implementation is a regex sweep over text and a recursive walk
over JSON-like structures. Patterns:

  • Saudi National ID (Hawiya):  10 digits, starts with 1
  • Iqama:                       10 digits, starts with 2
  • IBAN:                        ISO 13616 (Saudi: SA + 22 chars, but we
                                 accept the general 15-34 alphanumeric)
  • Credit card PAN:             13-19 digits, Luhn-validated to avoid
                                 false positives on invoice numbers
  • Email and Saudi phone number are NOT redacted (they're routinely
    the legitimate contact field on an invoice).
"""
from __future__ import annotations

import re
from typing import Any


MASK = "[REDACTED]"

_SA_HAWIYA  = re.compile(r"(?<!\d)1\d{9}(?!\d)")            # Saudi national ID
_SA_IQAMA   = re.compile(r"(?<!\d)2\d{9}(?!\d)")            # Iqama
_IBAN       = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_PAN        = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _luhn_ok(digits: str) -> bool:
    """Standard Luhn check — used to avoid masking ordinary numbers."""
    s = 0
    flip = False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        flip = not flip
    return s % 10 == 0


def _mask_pan(match: re.Match) -> str:
    digits = re.sub(r"[ -]", "", match.group(0))
    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
        return MASK
    return match.group(0)


def redact(text: Any) -> Any:
    """Redact PII anywhere it appears in *text*.

    Accepts a string, dict, list, or scalar. Returns the same shape with
    string leaves redacted. ``None`` / bool / numeric values pass through
    untouched.
    """
    if isinstance(text, str):
        out = _SA_HAWIYA.sub(MASK, text)
        out = _SA_IQAMA.sub(MASK, out)
        out = _IBAN.sub(MASK, out)
        out = _PAN.sub(_mask_pan, out)
        return out
    if isinstance(text, dict):
        return {k: redact(v) for k, v in text.items()}
    if isinstance(text, list):
        return [redact(v) for v in text]
    if isinstance(text, tuple):
        return tuple(redact(v) for v in text)
    return text


def has_pii(text: Any) -> bool:
    """``True`` if redacting *text* would change it."""
    return redact(text) != text
