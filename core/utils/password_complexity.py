"""
Password-complexity validator: enforces digit + special + mixed-case rules.

Plugs into Django's ``AUTH_PASSWORD_VALIDATORS``. The point isn't theoretical
strength — it's to push the password into the "harder than a dictionary brute
force" zone for SOC2 / regulatory checkboxes.
"""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class ComplexityValidator:
    """Require at least one digit, one uppercase, one lowercase, one symbol."""

    def __init__(self, min_classes: int = 4):
        # min_classes = how many of the four character classes must appear.
        # Default 4 = strictest. Drop to 3 for a "two of digit/upper/symbol" policy.
        self.min_classes = min_classes

    def validate(self, password: str, user=None) -> None:
        classes = 0
        if re.search(r"\d", password):
            classes += 1
        if re.search(r"[a-z]", password):
            classes += 1
        if re.search(r"[A-Z]", password):
            classes += 1
        if re.search(r"[^A-Za-z0-9]", password):
            classes += 1
        if classes < self.min_classes:
            raise ValidationError(
                _(
                    "Password must contain at least %(n)d of: digit, lowercase letter, "
                    "uppercase letter, special character."
                ),
                code="password_too_simple",
                params={"n": self.min_classes},
            )

    def get_help_text(self) -> str:
        return _(
            "Use at least %(n)d of: digit, lowercase, uppercase, special character."
        ) % {"n": self.min_classes}
