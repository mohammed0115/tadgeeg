"""Prompt registry.

Every prompt the platform sends to a language model is registered here
with a frozen body and a SHA-256 hash. The hash makes it impossible for
a developer to silently A/B prompts — the registry is the contract.

Usage::

    from apps.ai_safety.prompts import register, get

    register(
        name="invoice.classify",
        version=3,
        body=("You are an audit assistant. Classify the invoice ..."),
    )

    tpl = get("invoice.classify")           # latest
    tpl_v2 = get("invoice.classify", 2)     # specific
    rendered = tpl.render(invoice_number="INV-001", vendor="Acme")

When you change a prompt, BUMP THE VERSION. A version may not be
re-defined with a different body — that raises ``PromptDriftError``.
"""
from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass
from typing import Dict, Tuple


class PromptDriftError(RuntimeError):
    """Raised when an existing prompt version is registered with a different body."""


class PromptNotFoundError(LookupError):
    """No prompt found under that ``(name, version)``."""


@dataclass(frozen=True)
class PromptTemplate:
    name:    str
    version: int
    body:    str
    sha256:  str        # 64 hex chars

    def render(self, **kwargs) -> str:
        """Render via ``str.format``. Unknown placeholders → KeyError."""
        try:
            return string.Formatter().vformat(self.body, args=(), kwargs=kwargs)
        except KeyError as exc:
            raise KeyError(
                f"prompt '{self.name}' v{self.version} is missing variable {exc}"
            ) from exc

    def to_dict(self) -> dict:
        return {
            "name":    self.name,
            "version": self.version,
            "sha256":  self.sha256,
        }


_REGISTRY: Dict[Tuple[str, int], PromptTemplate] = {}


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def register(*, name: str, version: int, body: str) -> PromptTemplate:
    """Register a prompt. Re-registering the same (name, version) with a
    matching body is fine and returns the existing row; with a different
    body it raises :class:`PromptDriftError`."""
    if version < 1:
        raise ValueError("version must be ≥ 1")
    digest = _hash(body)
    key = (name, version)
    existing = _REGISTRY.get(key)
    if existing is not None:
        if existing.sha256 != digest:
            raise PromptDriftError(
                f"prompt '{name}' v{version} already registered with a "
                f"different body — bump the version instead of editing"
            )
        return existing
    tpl = PromptTemplate(name=name, version=version, body=body, sha256=digest)
    _REGISTRY[key] = tpl
    return tpl


def get(name: str, version: int | None = None) -> PromptTemplate:
    """Fetch a registered prompt. ``version=None`` returns the highest."""
    if version is None:
        candidates = [v for (n, v) in _REGISTRY if n == name]
        if not candidates:
            raise PromptNotFoundError(name)
        version = max(candidates)
    try:
        return _REGISTRY[(name, version)]
    except KeyError as exc:
        raise PromptNotFoundError(f"{name} v{version}") from exc


def all_prompts() -> list[dict]:
    """For an admin listing — every registered (name, version, sha)."""
    return sorted(
        (t.to_dict() for t in _REGISTRY.values()),
        key=lambda d: (d["name"], d["version"]),
    )


def reset_registry_for_tests():    # pragma: no cover
    _REGISTRY.clear()
