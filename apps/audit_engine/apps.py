"""The pipeline that runs an audit — jobs, results, issues.

Owns AuditJob (one queued run), AuditResult (its outcome and score), AuditIssue
and AIAnalysisLog. This is orchestration: what to run, whether it finished, how
long it took, what it cost.

NOT this app:
  · apps.auditing — the rules and the reading of documents
  · apps.audit    — the ISA workpapers built on the conclusions

`dashboard_selectors.py` here came from `apps/reporting/`, an app that was
never in INSTALLED_APPS. Its metrics query these models; no view calls them
yet.
"""
from django.apps import AppConfig


class AuditEngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit_engine"
    verbose_name = "Audit Engine"
