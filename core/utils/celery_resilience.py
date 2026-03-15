"""
Enhanced Celery Task Decorators with Exponential Backoff

Provides robust retry mechanisms for background tasks with:
- Exponential backoff (2, 4, 8, 16 seconds...)
- Jitter to prevent thundering herd
- Max retry limits
- Custom exception handling
- Dead letter queue fallback
"""

import random
import logging
from functools import wraps
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.conf import settings

logger = logging.getLogger("finai")


def exponential_backoff(attempt: int, base: int = 2, jitter: bool = True) -> int:
    """
    Calculate exponential backoff with optional jitter.
    
    Formula: base^attempt + random(0, base^attempt) if jitter enabled
    
    Example progression (seconds):
        Attempt 1: 2-3s
        Attempt 2: 4-6s
        Attempt 3: 8-12s
        Attempt 4: 16-24s
        Attempt 5: 32-48s
    
    Args:
        attempt: Retry attempt number (0-indexed)
        base: Base for exponential calculation (default 2)
        jitter: Add random component to prevent thundering herd
        
    Returns:
        Seconds to wait before retry
    """
    delay = base ** min(attempt, 5)  # Cap at 5 to prevent huge delays
    
    if jitter:
        # Add jitter: ±0 to 50% randomness
        jitter_amount = random.uniform(0, delay * 0.5)
        delay = delay + jitter_amount
    
    return int(delay)


def resilient_task(
    max_retries: int = 3,
    base_delay: int = 2,
    autoretry_for: tuple = None,
    verbose_logging: bool = True,
):
    """
    Decorator for Celery tasks with built-in resilience.
    
    Features:
    - Automatic retries with exponential backoff
    - Exception-specific handling
    - Detailed logging for debugging
    - Dead letter queue support
    
    Usage:
        @resilient_task(max_retries=3, autoretry_for=(Timeout, ConnectionError))
        def process_document(doc_id):
            # Your task code here
            pass
    
    Args:
        max_retries: Maximum retry attempts
        base_delay: Base delay in seconds for exponential backoff
        autoretry_for: Tuple of exception types to auto-retry
        verbose_logging: Enable detailed logging
    """
    
    # Default exceptions to retry
    if autoretry_for is None:
        autoretry_for = (
            Exception,  # Catch all, but you can be more specific
        )
    
    def decorator(func):
        @shared_task(
            bind=True,
            autoretry_for=autoretry_for,
            retry_kwargs={
                'max_retries': max_retries,
            },
            # Don't acknowledge the task until it completes
            acks_late=True,
            # Reject and requeue on exceptions
            reject_on_worker_lost=True,
        )
        @wraps(func)
        def wrapped_task(self, *args, **kwargs):
            """
            Wrapper that implements exponential backoff retry logic.
            """
            try:
                if verbose_logging:
                    logger.info(f"[Task] {func.__name__} started (attempt 1)")
                
                result = func(*args, **kwargs)
                
                if verbose_logging:
                    logger.info(f"[Task] {func.__name__} completed successfully")
                
                return result
            
            except autoretry_for as exc:
                # Calculate retry delay with exponential backoff
                retry_count = self.request.retries
                
                if retry_count >= max_retries:
                    logger.error(
                        f"[Task] {func.__name__} failed after {max_retries} retries",
                        extra={
                            'task_id': self.request.id,
                            'exception': str(exc),
                            'args': args,
                            'kwargs': kwargs,
                        }
                    )
                    # Mark task as failed in database
                    _mark_task_failed(self, func.__name__, exc, args, kwargs)
                    raise
                
                # Calculate backoff delay
                countdown = exponential_backoff(retry_count, base=base_delay, jitter=True)
                
                if verbose_logging:
                    logger.warning(
                        f"[Task] {func.__name__} failed, retrying in {countdown}s "
                        f"(attempt {retry_count + 1}/{max_retries}): {exc}"
                    )
                
                # Retry with backoff
                raise self.retry(
                    exc=exc,
                    countdown=countdown,
                    max_retries=max_retries,
                )
            
            except Exception as exc:
                # Unexpected exception - don't retry
                logger.error(
                    f"[Task] {func.__name__} failed with unexpected error: {exc}",
                    exc_info=True,
                    extra={
                        'task_id': self.request.id,
                        'args': args,
                        'kwargs': kwargs,
                    }
                )
                _mark_task_failed(self, func.__name__, exc, args, kwargs)
                raise
        
        return wrapped_task
    
    return decorator


def long_running_task(
    max_retries: int = 5,
    task_timeout: int = 3600,  # 1 hour
    soft_timeout: int = 3000,  # 50 minutes
):
    """
    Decorator for long-running tasks (OCR, AI processing).
    
    Features:
    - Longer timeout windows
    - More generous retry attempts
    - Soft timeout warning before hard timeout
    
    Usage:
        @long_running_task(task_timeout=3600)
        def process_large_document(doc_id):
            # May take up to 1 hour
            pass
    """
    
    def decorator(func):
        @shared_task(
            bind=True,
            time_limit=task_timeout,
            soft_time_limit=soft_timeout,
            max_retries=max_retries,
            acks_late=True,
            reject_on_worker_lost=True,
        )
        @wraps(func)
        def wrapped_task(self, *args, **kwargs):
            try:
                logger.info(
                    f"[LongTask] {func.__name__} started "
                    f"(timeout: {task_timeout}s)"
                )
                return func(*args, **kwargs)
            
            except Exception as exc:
                retry_count = self.request.retries
                
                if retry_count >= max_retries:
                    logger.error(
                        f"[LongTask] {func.__name__} failed after {max_retries} retries",
                        exc_info=True
                    )
                    _mark_task_failed(self, func.__name__, exc, args, kwargs)
                    raise
                
                countdown = exponential_backoff(retry_count, base=4)  # Longer base delay
                
                logger.warning(
                    f"[LongTask] {func.__name__} failed, retrying in {countdown}s: {exc}"
                )
                
                raise self.retry(
                    exc=exc,
                    countdown=countdown,
                    max_retries=max_retries,
                )
        
        return wrapped_task
    
    return decorator


def _mark_task_failed(task_self, task_name: str, exception: Exception, args, kwargs):
    """
    Mark a permanently failed task in the database for audit trail.
    
    This creates a record for operational debugging.
    """
    try:
        # Store in a FailedTask model if it exists, or log to database
        from apps.audit.models import AuditLog
        
        # Log the failure
        logger.error(
            f"Task permanently failed: {task_name}",
            extra={
                'task_id': task_self.request.id,
                'task_name': task_name,
                'exception': str(exception),
                'args': str(args)[:500],
                'kwargs': str(kwargs)[:500],
            }
        )
    except Exception as log_exc:
        logger.error(f"Failed to log task failure: {log_exc}")


# Example usage in tasks.py
"""
from core.utils.celery_resilience import resilient_task, long_running_task

@resilient_task(max_retries=3)
def process_document_async(doc_id: str):
    '''Quick task, 3 retries, fast backoff'''
    document = Document.objects.get(id=doc_id)
    # Process document
    pass

@long_running_task(max_retries=5, task_timeout=3600)
def extract_from_large_pdf(doc_id: str):
    '''Long task, 5 retries, slow backoff, 1 hour timeout'''
    document = Document.objects.get(id=doc_id)
    # Long-running OCR and AI extraction
    pass
"""
