# Load Celery app when Django starts
from .celery import app as celery_app
__all__ = ("celery_app",)


def _run_startup_checks():
    try:
        from core.utils.startup_checks import check_email_configuration
        check_email_configuration()
    except Exception:
        pass

_run_startup_checks()
