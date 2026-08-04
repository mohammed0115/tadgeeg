"""The AI document auditor — what the machine reads out of a file.

Owns AuditDocument (an uploaded file under analysis), the findings its rules
raise, accounting-rule evaluations, and the AI validation harness
(AIValidationDataset / AIValidationRun) that turns a labelled CSV into a
measured precision figure.

NOT this app:
  · apps.audit        — the auditor's ISA workpapers and conclusions
  · apps.audit_engine — the Celery pipeline that schedules and runs the work

The one-letter difference from `apps.audit` is a real maintenance cost; the
boundary is the stage, not the spelling. This app answers "what does this
document say"; apps.audit answers "what does the auditor conclude".
"""
from django.apps import AppConfig


class AuditingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auditing"
    verbose_name = "AI Auditor"

    def ready(self):
        from core.utils.startup_checks import check_email_configuration
        check_email_configuration()
