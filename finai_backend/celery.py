"""Celery application configuration for FinAI."""

import os
from celery import Celery, signals
from celery.schedules import crontab
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")

app = Celery("finai_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

import core.services.notification_service


# ── Correlation ID propagation ────────────────────────────────────────────────
# Tasks receive the request_id via task headers so every log line produced
# inside a worker carries the same correlation ID as the originating HTTP request.

@signals.task_prerun.connect
def _task_prerun(task_id, task, *args, **kwargs):
    """Set correlation ID from task header before task body runs."""
    from core.utils.logging import set_correlation_id
    request_id = (task.request or {}).get("request_id", "") or task_id
    set_correlation_id(str(request_id))


@signals.task_postrun.connect
def _task_postrun(task_id, task, *args, **kwargs):
    """Clear correlation ID after task completes."""
    from core.utils.logging import set_correlation_id
    set_correlation_id("")


@signals.task_failure.connect
def _task_failure(task_id, exception, traceback, einfo, *args, **kwargs):
    """Log structured task failure to Sentry if configured."""
    import logging
    logger = logging.getLogger("finai.celery")
    logger.error(
        "Task failed",
        extra={
            "task_id":   task_id,
            "exception": str(exception),
        },
        exc_info=True,
    )

# Scheduled tasks
app.conf.beat_schedule = {
    "nightly-anomaly-scan": {
        "task": "apps.documents.tasks.run_nightly_anomaly_scan",
        "schedule": crontab(hour=2, minute=0),  # 2 AM daily
    },
    "weekly-kpi-report": {
        "task": "apps.documents.tasks.generate_weekly_kpi_report",
        "schedule": crontab(day_of_week="monday", hour=6, minute=0),  # Monday 6 AM
    },
    "weekly-summary": {
        "task": "notifications.weekly_summary",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),
    },
}
app.conf.beat_schedule.update(getattr(settings, "CELERY_BEAT_SCHEDULE", {}))
