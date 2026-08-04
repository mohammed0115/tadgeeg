"""Engagement-level audit under ISA — the auditor's own workpapers.

Owns the artefacts a firm produces while auditing a client: engagements,
assessed risks (ISA 315), procedures (ISA 330), evidence requests (ISA 500),
external confirmations (ISA 505), control deficiencies (ISA 265), the summary
of audit differences, sign-off and the engagement report. Plus AuditFinding,
the rule-engine finding an auditor gives a verdict on.

NOT this app:
  · apps.auditing     — the AI document auditor that reads uploaded files
  · apps.audit_engine — the async job pipeline that runs an audit
  · apps.reports      — rendering a finished report to PDF/Excel

Three apps share the word "audit" and each owns a different stage: what the
machine reads (auditing), what runs it (audit_engine), what the auditor
concludes (here). Merging them would be a data migration across 43 models
holding live tenant rows, not a rename.
"""
from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    verbose_name = "Audit"

    def ready(self):
        # Wire HashChainMixin pre_save / pre_delete signals.
        from apps.audit import signals  # noqa: F401
