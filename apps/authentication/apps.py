from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.authentication"
    label = "authentication"

    def ready(self):
        # Register signal handlers defined in signals.py.
        import apps.authentication.signals  # noqa: F401

        # Validate email configuration on startup (raises ImproperlyConfigured
        # in production if SMTP env vars are missing).
        from core.utils.startup_checks import check_email_configuration
        check_email_configuration()
