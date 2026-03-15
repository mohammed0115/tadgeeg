"""
Sentry Configuration for FinAI
Real-time error tracking and monitoring in production.

Installation:
    pip install sentry-sdk django
    
Environment Variables Required:
    SENTRY_DSN: Your Sentry project DSN (leave blank to disable)
    SENTRY_ENVIRONMENT: production|staging|development
    SENTRY_TRACES_SAMPLE_RATE: 0.1 (10% of transactions)
"""

import os
import logging
from django.conf import settings

try:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    sentry_sdk = None


def init_sentry():
    """
    Initialize Sentry error tracking.
    
    Safely initializes Sentry if DSN configured, otherwise no-op.
    Should be called in manage.py or settings.py.
    """
    if not SENTRY_AVAILABLE:
        logging.warning(
            "Sentry SDK not installed. Install with: pip install sentry-sdk"
        )
        return False
    
    sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
    
    if not sentry_dsn:
        logging.debug("SENTRY_DSN not configured - Sentry disabled")
        return False
    
    environment = os.environ.get("SENTRY_ENVIRONMENT", "development")
    traces_sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    
    # Configure logging integration to avoid duplicate logs
    logging_integration = LoggingIntegration(
        level=logging.INFO,  # Capture info and above as breadcrumbs
        event_level=logging.ERROR  # Send errors as events
    )
    
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
            logging_integration,
        ],
        # Set traces_sample_rate to identify performance issues
        traces_sample_rate=traces_sample_rate,
        # If you wish to associate users to errors (requires `identify`)
        send_default_pii=False,  # Don't send PII by default
        environment=environment,
        release=os.environ.get("APP_VERSION", "unknown"),
        # Performance Monitoring
        profiles_sample_rate=0.1,  # Sample 10% of profiles for performance
        # Ignore specific errors that are expected
        ignore_errors=[
            "django.http.request.DisallowedHost",
            "django.core.exceptions.DisallowedHost",
            "rest_framework.exceptions.NotFound",
            "rest_framework.exceptions.ValidationError",
        ],
        # Custom before_send to filter sensitive data
        before_send=_sentry_before_send,
    )
    
    logging.info(f"Sentry initialized for environment: {environment}")
    return True


def _sentry_before_send(event, hint):
    """
    Sentry before_send hook to filter sensitive data.
    
    Removes potentially sensitive information from events before sending to Sentry.
    - Authorization headers
    - API keys
    - Passwords
    - Email addresses (optional)
    """
    # Remove sensitive headers
    if "request" in event:
        headers = event["request"].get("headers", {})
        
        # List of sensitive header names to redact
        sensitive_headers = [
            "Authorization",
            "X-API-Key",
            "X-Token",
            "Cookie",
            "Set-Cookie",
        ]
        
        for header in sensitive_headers:
            if header in headers:
                headers[header] = "[REDACTED]"
    
    # Remove sensitive POST data
    if "request" in event and "data" in event["request"]:
        data = event["request"]["data"]
        if isinstance(data, dict):
            sensitive_fields = ["password", "api_key", "token", "secret"]
            for field in sensitive_fields:
                if field in data:
                    data[field] = "[REDACTED]"
    
    return event


class SentryContextManager:
    """
    Utility to add context to Sentry events.
    
    Usage:
        with SentryContextManager(user_id="123", org_id="456"):
            process_document()  # Any errors will include this context
    """
    
    def __init__(self, **context):
        """Store context to add to Sentry"""
        self.context = context
    
    def __enter__(self):
        """Add context on entry"""
        if SENTRY_AVAILABLE and sentry_sdk:
            for key, value in self.context.items():
                sentry_sdk.set_context(key, {"value": str(value)})
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clear context on exit"""
        # Sentry manages context automatically
        pass


def capture_exception_with_context(exception, **context):
    """
    Capture an exception with additional context.
    
    Usage:
        try:
            risky_operation()
        except Exception as e:
            capture_exception_with_context(
                e,
                document_id="123",
                organization_id="456"
            )
    """
    if SENTRY_AVAILABLE and sentry_sdk:
        with sentry_sdk.push_scope() as scope:
            for key, value in context.items():
                scope.set_context(key, {"value": str(value)})
            sentry_sdk.capture_exception(exception)
    else:
        raise exception


def set_user_context(user_id: str, email: str = None, username: str = None):
    """
    Set user context for Sentry events.
    
    All subsequent errors will be associated with this user.
    
    Usage:
        set_user_context(user.id, email=user.email)
    """
    if SENTRY_AVAILABLE and sentry_sdk:
        sentry_sdk.set_user({
            "id": user_id,
            "email": email,
            "username": username,
        })


def clear_user_context():
    """Clear the current user context (e.g., on logout)"""
    if SENTRY_AVAILABLE and sentry_sdk:
        sentry_sdk.set_user(None)


def add_breadcrumb(message: str, level: str = "info", **data):
    """
    Add a breadcrumb to the next Sentry event.
    
    Breadcrumbs provide context for errors (e.g., recent user actions).
    
    Usage:
        add_breadcrumb("User uploaded document", document_id="123")
    """
    if SENTRY_AVAILABLE and sentry_sdk:
        sentry_sdk.add_breadcrumb(
            message=message,
            level=level,
            data=data
        )


# Django Middleware for automatic Sentry context
class SentryUserMiddleware:
    """
    Middleware to automatically set Sentry user context from Django auth.
    
    Add to MIDDLEWARE:
        'core.utils.sentry_integration.SentryUserMiddleware',
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        if SENTRY_AVAILABLE and sentry_sdk:
            if request.user.is_authenticated:
                set_user_context(
                    user_id=str(request.user.id),
                    email=request.user.email,
                    username=getattr(request.user, 'full_name', '')
                )
                
                # Add request context
                sentry_sdk.set_context("organization", {
                    "id": str(getattr(request.user.organization, 'id', 'unknown')),
                    "name": str(getattr(request.user.organization, 'name', 'unknown')),
                })
            else:
                clear_user_context()
        
        response = self.get_response(request)
        return response


# Celery integration for task monitoring
def init_sentry_for_celery(app):
    """
    Setup Sentry monitoring for Celery tasks.
    
    Usage in celery.py:
        from core.utils.sentry_integration import init_sentry_for_celery
        init_sentry_for_celery(app)
    """
    if SENTRY_AVAILABLE and sentry_sdk:
        sentry_sdk.init_celery_monitoring()
        logging.info("Sentry Celery monitoring initialized")
