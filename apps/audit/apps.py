from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    verbose_name = "Audit"

    def ready(self):
        # Wire HashChainMixin pre_save / pre_delete signals.
        from apps.audit import signals  # noqa: F401
