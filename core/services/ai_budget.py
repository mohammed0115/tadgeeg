"""
Per-organization AI budget guard.

Tracks daily OpenAI token spend per organization and short-circuits requests
when the configured cap is reached. Without this, a single misbehaving upload
or runaway process can burn through a customer's monthly OpenAI quota in
minutes — turning a feature into a liability.

Implementation notes
--------------------
- Counters live in Django's cache (DB- or Redis-backed depending on config),
  keyed by org_id + UTC date. Counters auto-expire at 32h so we don't have to
  do explicit midnight rollovers.
- Cap is configured via env var OPENAI_DAILY_TOKEN_CAP_PER_ORG (default
  500_000 tokens — roughly $5/day on GPT-4o pricing).
- We charge BEFORE the call (estimated tokens) so a runaway loop is stopped
  before it starts. After the call returns, we reconcile with actual usage.
- Callers should check `is_over_budget()` before invoking OpenAI; on overrun,
  fall back to deterministic regex extraction (already implemented elsewhere).
"""
from __future__ import annotations

import logging
import os
from datetime import date as _date

from django.core.cache import cache

logger = logging.getLogger("finai")

# Default ~$5/day on GPT-4o input pricing. Override via env in production.
_DEFAULT_DAILY_CAP = int(os.environ.get("OPENAI_DAILY_TOKEN_CAP_PER_ORG", "500000"))


def _key(org_id, day=None) -> str:
    day = day or _date.today().isoformat()
    return f"openai:budget:{org_id}:{day}"


def get_daily_cap(org_id) -> int:
    """Return the per-org daily token cap. Hook for per-org overrides later."""
    return _DEFAULT_DAILY_CAP


def get_used(org_id) -> int:
    """How many tokens this org has consumed today."""
    return int(cache.get(_key(org_id), 0))


def is_over_budget(org_id, projected_tokens: int = 0) -> bool:
    """True if charging `projected_tokens` would exceed today's cap."""
    if not org_id:
        return False
    return get_used(org_id) + max(projected_tokens, 0) > get_daily_cap(org_id)


def charge(org_id, tokens: int) -> int:
    """Add ``tokens`` to today's counter. Returns the new total.

    Uses cache.add+incr so multiple workers don't race on init. The 32-hour
    TTL covers the timezone wraparound without manual expiry logic.
    """
    if not org_id or tokens <= 0:
        return get_used(org_id)
    key = _key(org_id)
    cache.add(key, 0, timeout=32 * 3600)
    try:
        return cache.incr(key, tokens)
    except ValueError:
        # Cache backend evicted the key between add() and incr() — re-seed.
        cache.set(key, tokens, timeout=32 * 3600)
        return tokens


class BudgetExceeded(RuntimeError):
    """Raised by guarded extractors when the org cap is reached."""

    def __init__(self, org_id, used: int, cap: int):
        self.org_id = org_id
        self.used = used
        self.cap = cap
        super().__init__(
            f"OpenAI daily budget exceeded for org {org_id}: "
            f"{used:,} / {cap:,} tokens used"
        )


def guard(org_id, projected_tokens: int = 0):
    """Raise BudgetExceeded if the org has hit its cap. Otherwise no-op."""
    if is_over_budget(org_id, projected_tokens):
        used = get_used(org_id)
        cap = get_daily_cap(org_id)
        logger.warning(
            "[ai-budget] org=%s used=%d cap=%d projected=%d — request blocked",
            org_id, used, cap, projected_tokens,
        )
        raise BudgetExceeded(org_id, used, cap)


# Thread-local current-org context — set by upload pipelines so the AI service
# layer can call guard()/charge() without each function having to take org_id.
import threading as _threading
from contextlib import contextmanager

_local = _threading.local()


def get_current_org_id():
    return getattr(_local, "org_id", None)


@contextmanager
def org_context(org_id):
    """Bind ``org_id`` for the duration of a block so the AI extractor can
    look it up via ``get_current_org_id()`` without a signature change."""
    prev = getattr(_local, "org_id", None)
    _local.org_id = org_id
    try:
        yield
    finally:
        _local.org_id = prev


def guard_current(projected_tokens: int = 0):
    """Convenience: guard() against whichever org is currently in context."""
    org_id = get_current_org_id()
    if org_id is not None:
        guard(org_id, projected_tokens)


def charge_current(tokens: int):
    """Convenience: charge tokens to the current-context org."""
    org_id = get_current_org_id()
    if org_id is not None and tokens > 0:
        charge(org_id, tokens)
