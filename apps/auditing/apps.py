from django.apps import AppConfig


class AuditingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auditing"
    verbose_name = "AI Auditor"

    def ready(self):
        from core.utils.startup_checks import check_email_configuration
        check_email_configuration()
