"""Celery application configuration for Tadgeeg AI."""

import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")

app = Celery("finai_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

import core.services.notification_service

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
