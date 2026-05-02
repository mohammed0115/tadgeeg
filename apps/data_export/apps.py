from django.apps import AppConfig


class DataExportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.data_export"
    label = "data_export"
    verbose_name = "Data Export (GDPR)"
