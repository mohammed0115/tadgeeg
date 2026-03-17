"""
OpenAI Circuit Breaker — Phase 0

Implements the circuit breaker pattern to prevent cascading failures when
OpenAI API is degraded or unavailable.

States:
  CLOSED     — normal operation; requests flow through
  OPEN       — too many failures; requests are rejected immediately
  HALF_OPEN  — recovery probe; a limited number of test requests are allowed

Configuration (via Django settings):
  CIRCUIT_BREAKER_FAILURE_THRESHOLD  — consecutive failures before opening (default 5)
  CIRCUIT_BREAKER_RECOVERY_TIMEOUT   — seconds before OPEN → HALF_OPEN probe (default 60)
  CIRCUIT_BREAKER_HALF_OPEN_CALLS    — test calls allowed in HALF_OPEN state (default 2)

Usage:
    from core.services.ai.circuit_breaker import openai_circuit_breaker, CircuitBreakerOpen

    try:
        result = openai_circuit_breaker.call(my_openai_function, *args, **kwargs)
    except CircuitBreakerOpen as exc:
        # Circuit is OPEN — use fallback immediately
        result = fallback()

Or as a decorator:
    @openai_circuit_breaker.protect
    def call_openai():
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from django.conf import settings

logger = logging.getLogger("finai")


# ── States ────────────────────────────────────────────────────────────────────

class CircuitState(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


# ── Exception ─────────────────────────────────────────────────────────────────

class CircuitBreakerOpen(Exception):
    """Raised when a call is attempted while the circuit is OPEN."""

    def __init__(self, name: str, retry_after: float):
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is OPEN — retry after {retry_after:.0f}s"
        )


# ── Stats ─────────────────────────────────────────────────────────────────────

@dataclass
class CircuitBreakerStats:
    total_calls:          int   = 0
    total_successes:      int   = 0
    total_failures:       int   = 0
    total_rejected:       int   = 0   # calls rejected while OPEN
    consecutive_failures: int   = 0
    last_failure_time:    float = 0.0
    last_success_time:    float = 0.0
    state_changes:        list  = field(default_factory=list)

    def record_state_change(self, old_state: CircuitState, new_state: CircuitState) -> None:
        self.state_changes.append({
            "from":      old_state.value,
            "to":        new_state.value,
            "timestamp": time.time(),
        })
        # Keep only last 20 transitions
        if len(self.state_changes) > 20:
            self.state_changes = self.state_changes[-20:]

    def to_dict(self) -> dict:
        return {
            "total_calls":           self.total_calls,
            "total_successes":       self.total_successes,
            "total_failures":        self.total_failures,
            "total_rejected":        self.total_rejected,
            "consecutive_failures":  self.consecutive_failures,
            "last_failure_time":     self.last_failure_time,
            "last_success_time":     self.last_success_time,
            "recent_state_changes":  self.state_changes[-5:],
        }


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    All state mutations are protected by a threading.Lock so this is safe
    to use across concurrent Celery workers in the same process.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int  = 5,
        recovery_timeout:  float = 60.0,
        half_open_max_calls: int = 2,
        expected_exceptions: tuple = (Exception,),
    ):
        self.name                 = name
        self.failure_threshold    = failure_threshold
        self.recovery_timeout     = recovery_timeout
        self.half_open_max_calls  = half_open_max_calls
        self.expected_exceptions  = expected_exceptions

        self._state               = CircuitState.CLOSED
        self._half_open_calls     = 0   # calls attempted in HALF_OPEN
        self._half_open_successes = 0   # successes in HALF_OPEN

        self._lock  = threading.Lock()
        self._stats = CircuitBreakerStats()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    def call(self, func: Callable, *args, **kwargs):
        """
        Execute func through the circuit breaker.

        Raises CircuitBreakerOpen if the circuit is OPEN (not yet recovered).
        Propagates any exception raised by func and counts it as a failure.
        """
        with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.OPEN:
                self._stats.total_rejected += 1
                retry_after = max(
                    0.0,
                    self.recovery_timeout - (time.time() - self._stats.last_failure_time),
                )
                raise CircuitBreakerOpen(self.name, retry_after)

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    self._stats.total_rejected += 1
                    raise CircuitBreakerOpen(self.name, 0.0)
                self._half_open_calls += 1

            self._stats.total_calls += 1

        # ── Execute outside the lock to avoid deadlock in reentrant calls ──────
        try:
            result = func(*args, **kwargs)
        except self.expected_exceptions as exc:
            self._on_failure(exc)
            raise

        self._on_success()
        return result

    def protect(self, func: Callable) -> Callable:
        """Decorator form of call()."""
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper

    def reset(self) -> None:
        """Manually force the circuit to CLOSED (use for testing / admin recovery)."""
        with self._lock:
            old = self._state
            self._state               = CircuitState.CLOSED
            self._half_open_calls     = 0
            self._half_open_successes = 0
            self._stats.consecutive_failures = 0
            if old != CircuitState.CLOSED:
                self._stats.record_state_change(old, CircuitState.CLOSED)
            logger.info("[CircuitBreaker:%s] Manually reset to CLOSED", self.name)

    def stats(self) -> dict:
        return {"name": self.name, "state": self._state.value, **self._stats.to_dict()}

    # ── Transitions ───────────────────────────────────────────────────────────

    def _maybe_transition_to_half_open(self) -> None:
        """OPEN → HALF_OPEN when the recovery timeout has elapsed."""
        if (
            self._state == CircuitState.OPEN
            and self._stats.last_failure_time > 0
            and time.time() - self._stats.last_failure_time >= self.recovery_timeout
        ):
            self._transition(CircuitState.HALF_OPEN)
            self._half_open_calls     = 0
            self._half_open_successes = 0

    def _on_success(self) -> None:
        with self._lock:
            self._stats.total_successes      += 1
            self._stats.consecutive_failures  = 0
            self._stats.last_success_time     = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.half_open_max_calls:
                    self._transition(CircuitState.CLOSED)

    def _on_failure(self, exc: Exception) -> None:
        with self._lock:
            self._stats.total_failures       += 1
            self._stats.consecutive_failures += 1
            self._stats.last_failure_time     = time.time()

            logger.warning(
                "[CircuitBreaker:%s] failure #%d/%d — %s",
                self.name,
                self._stats.consecutive_failures,
                self.failure_threshold,
                exc,
            )

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN immediately reopens the circuit
                self._transition(CircuitState.OPEN)
            elif (
                self._state == CircuitState.CLOSED
                and self._stats.consecutive_failures >= self.failure_threshold
            ):
                self._transition(CircuitState.OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        """Must be called with self._lock held."""
        old_state   = self._state
        self._state = new_state
        self._stats.record_state_change(old_state, new_state)
        logger.warning(
            "[CircuitBreaker:%s] state %s → %s (failures=%d)",
            self.name,
            old_state.value,
            new_state.value,
            self._stats.consecutive_failures,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────
# One circuit breaker for all OpenAI calls across the process.

def _build_openai_cb() -> CircuitBreaker:
    from openai import APIStatusError, APIConnectionError, RateLimitError, APITimeoutError

    failure_threshold = int(getattr(settings, "CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5))
    recovery_timeout  = float(getattr(settings, "CIRCUIT_BREAKER_RECOVERY_TIMEOUT", 60.0))
    half_open_calls   = int(getattr(settings, "CIRCUIT_BREAKER_HALF_OPEN_CALLS", 2))

    return CircuitBreaker(
        name                = "openai",
        failure_threshold   = failure_threshold,
        recovery_timeout    = recovery_timeout,
        half_open_max_calls = half_open_calls,
        expected_exceptions = (
            APIStatusError,
            APIConnectionError,
            RateLimitError,
            APITimeoutError,
            Exception,         # catch-all so network errors also count
        ),
    )


# Lazily initialised to avoid importing openai at module-import time
_openai_cb: Optional[CircuitBreaker] = None
_cb_lock = threading.Lock()


def get_openai_circuit_breaker() -> CircuitBreaker:
    """Return the process-wide OpenAI circuit breaker (lazy init)."""
    global _openai_cb
    if _openai_cb is None:
        with _cb_lock:
            if _openai_cb is None:
                _openai_cb = _build_openai_cb()
    return _openai_cb


# Convenience alias
openai_circuit_breaker = get_openai_circuit_breaker
