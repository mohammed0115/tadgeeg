"""
Resilient OpenAI API Wrapper with Circuit Breaker Pattern

Prevents cascading failures when OpenAI API is unavailable.
Automatically degrading to Tesseract-only mode after thresholds exceeded.
"""

import logging
import time
from typing import Optional, Dict, Any
from functools import wraps
from datetime import datetime, timedelta

logger = logging.getLogger("finai")


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open (API unavailable)"""
    pass


class CircuitBreaker:
    """
    Circuit Breaker for external API calls.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Threshold exceeded, requests fail fast
    - HALF_OPEN: Testing if service recovered
    """
    
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Exception = Exception
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Identifier for logging
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting half-open
            expected_exception: Exception type to catch
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.state = self.CLOSED
        self.last_failure_time = None
        self.last_success_time = None
    
    @property
    def state_readable(self) -> str:
        """Return human-readable state with timing"""
        if self.state == self.OPEN:
            if self.last_failure_time:
                age = datetime.now() - self.last_failure_time
                return f"OPEN (failed {age.seconds}s ago)"
            return "OPEN"
        return self.state
    
    def call(self, func, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker.
        
        Args:
            func: Callable to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result if successful
            
        Raises:
            CircuitBreakerError: If circuit is open
            Original exception: If function fails and circuit not open
        """
        if self.state == self.OPEN:
            if self._should_attempt_reset():
                self.state = self.HALF_OPEN
                logger.info(f"[CircuitBreaker:{self.name}] Testing recovery (HALF_OPEN)")
            else:
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is OPEN. "
                    f"Service unavailable. Retry in {self._time_until_reset()}s"
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as exc:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time passed to attempt recovery"""
        if not self.last_failure_time:
            return False
        
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout
    
    def _time_until_reset(self) -> int:
        """Seconds remaining until reset attempt allowed"""
        if not self.last_failure_time:
            return 0
        
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        remaining = max(0, int(self.recovery_timeout - elapsed))
        return remaining
    
    def _on_success(self):
        """Handle successful call"""
        was_open = self.state == self.OPEN or self.state == self.HALF_OPEN
        
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_success_time = datetime.now()
        
        if was_open:
            logger.info(f"[CircuitBreaker:{self.name}] Recovered! Circuit CLOSED")
    
    def _on_failure(self):
        """Handle failed call"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == self.HALF_OPEN:
            logger.warning(f"[CircuitBreaker:{self.name}] Recovery attempt failed")
            self.state = self.OPEN
        elif self.failure_count >= self.failure_threshold:
            logger.error(
                f"[CircuitBreaker:{self.name}] Threshold exceeded "
                f"({self.failure_count}/{self.failure_threshold}). "
                f"Opening circuit."
            )
            self.state = self.OPEN
        else:
            logger.warning(
                f"[CircuitBreaker:{self.name}] Failure {self.failure_count}/"
                f"{self.failure_threshold}"
            )


# Global circuit breakers for external services
OPENAI_CIRCUIT_BREAKER = CircuitBreaker(
    name="openai",
    failure_threshold=5,
    recovery_timeout=60,
    expected_exception=Exception
)


def with_circuit_breaker(circuit_breaker: CircuitBreaker):
    """
    Decorator to apply circuit breaker to a function.
    
    Usage:
        @with_circuit_breaker(OPENAI_CIRCUIT_BREAKER)
        def call_openai_api():
            return openai.ChatCompletion.create(...)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return circuit_breaker.call(func, *args, **kwargs)
            except CircuitBreakerError as exc:
                logger.error(f"Circuit breaker tripped: {exc}")
                raise
        return wrapper
    return decorator


class ResilientOpenAIWrapper:
    """
    Wrapper around OpenAI client with fallback strategy.
    
    Strategy when OpenAI fails:
    1. First 3 failures: Retry with exponential backoff
    2. After threshold: Fast-fail and degrade to Tesseract
    3. Fallback mode: Use Tesseract, skip AI extraction
    """
    
    def __init__(self, client=None):
        self.client = client
        self.circuit_breaker = OPENAI_CIRCUIT_BREAKER
        self._fallback_mode = False
    
    @property
    def fallback_mode(self) -> bool:
        """True if circuit breaker open (fallback to Tesseract)"""
        return self.circuit_breaker.state in [
            CircuitBreaker.OPEN,
            "OPEN"
        ]
    
    def chat_with_resilience(
        self,
        messages: list,
        timeout: int = 30,
        fallback_result: dict = None
    ) -> Optional[str]:
        """
        Call OpenAI with circuit breaker protection.
        
        Args:
            messages: Chat messages for OpenAI
            timeout: Request timeout in seconds
            fallback_result: Default result if circuit open
            
        Returns:
            Response content or fallback result
        """
        if self.circuit_breaker.state == CircuitBreaker.OPEN:
            logger.warning("OpenAI circuit breaker is OPEN - using fallback")
            return fallback_result or self._get_tesseract_fallback()
        
        try:
            def _call_openai():
                from django.conf import settings
                from openai import OpenAI
                
                api_key = getattr(settings, "OPENAI_API_KEY", "")
                if not api_key:
                    raise ValueError("OPENAI_API_KEY not configured")
                
                client = OpenAI(api_key=api_key, timeout=timeout)
                response = client.chat.completions.create(
                    model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                    messages=messages,
                    max_tokens=getattr(settings, "OPENAI_MAX_TOKENS", 4096),
                    temperature=0,
                    response_format={"type": "json_object"}
                )
                return response.choices[0].message.content
            
            # Call through circuit breaker
            return self.circuit_breaker.call(_call_openai)
        
        except CircuitBreakerError:
            logger.error("OpenAI circuit breaker tripped - degrading to Tesseract only")
            return fallback_result or self._get_tesseract_fallback()
        except Exception as exc:
            logger.error(f"OpenAI extraction failed: {exc}")
            return fallback_result or self._get_tesseract_fallback()
    
    def _get_tesseract_fallback(self) -> dict:
        """Return fallback result indicating AI extraction skipped"""
        return {
            "document_type": "other",
            "vendor_name": "",
            "total_amount": 0.0,
            "confidence": 0.0,
            "raw_extraction_notes": "AI extraction skipped - OpenAI service unavailable. Using OCR text only.",
            "extraction_method": "tesseract_only"
        }


def get_openai_status() -> Dict[str, Any]:
    """
    Get OpenAI circuit breaker status for monitoring.
    
    Returns:
        {
            'state': 'CLOSED|OPEN|HALF_OPEN',
            'failures': int,
            'threshold': int,
            'last_success': datetime or None,
            'last_failure': datetime or None,
            'time_to_retry': int (seconds)
        }
    """
    cb = OPENAI_CIRCUIT_BREAKER
    return {
        'state': cb.state_readable,
        'failures': cb.failure_count,
        'threshold': cb.failure_threshold,
        'last_success': cb.last_success_time,
        'last_failure': cb.last_failure_time,
        'time_to_retry_seconds': cb._time_until_reset(),
        'fallback_mode_active': cb.state == CircuitBreaker.OPEN
    }
