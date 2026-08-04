"""Rendering a finished report — PDF, Excel, HTML.

Owns Report, the saved output of a generation run, and the views that render
it. This app is about *presentation*: taking data another app produced and
turning it into a document a person receives.

NOT this app:
  · apps.audit / apps.auditing / apps.audit_engine — producing the findings
  · apps.analytics — computing the metrics

There used to be an `apps/reporting/` one character away from this name, doing
something unrelated. It was never in INSTALLED_APPS, had no tables, and was
deleted; the only live module in it moved to apps.audit_engine.
"""
from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
    verbose_name = "Reports"
