import logging
from django.core.exceptions import ImproperlyConfigured
from django.conf import settings

logger = logging.getLogger("finai")


def check_email_configuration():
    # Test settings deliberately use Django's in-memory mail backend and never
    # deliver OTPs.  Treating them as production merely because DEBUG=False
    # makes a clean pytest/CI run depend on fake SMTP environment variables.
    if getattr(settings, "TESTING", False):
        return

    if getattr(settings, "DEBUG", True):
        if not getattr(settings, "EMAIL_HOST_USER", None):
            logger.warning(
                "EMAIL_HOST_USER not set — OTP emails will print to console only. "
                "Set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in .env for real delivery."
            )
        return

    required = ["EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "EMAIL_HOST"]
    missing = [k for k in required if not getattr(settings, k, None)]
    if missing:
        raise ImproperlyConfigured(
            f"Production email not configured. Missing: {', '.join(missing)}. "
            "OTP delivery will fail. Set these in .env immediately."
        )
