from django.apps import AppConfig


class OrganizationAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.organization_admin"
    label = "organization_admin"
    verbose_name = "Organization Admin"
